/**
 * Object storage S3-compatible (Cloudflare R2, AWS S3, MinIO).
 *
 * Kenapa S3-compatible, bukan Vercel Blob:
 *
 *  - Presigned URL adalah HTTP PUT/GET biasa. Browser bisa, agent Python bisa,
 *    curl bisa. Tidak ada protokol SDK khusus yang harus diimplementasikan dua kali.
 *  - Video besar dan Vercel Blob tier gratis habis cepat. R2 tidak menagih
 *    biaya egress sama sekali, yang cocok untuk file yang diunduh agent lalu
 *    diunggah lagi.
 *  - Bisa ditukar ke MinIO lokal saat development tanpa mengubah kode.
 *
 * Video BESAR tidak pernah melewati serverless function. API route di sini hanya
 * menerbitkan URL bertanda tangan; byte-nya mengalir langsung browser <-> storage.
 */
import {
  DeleteObjectsCommand,
  GetObjectCommand,
  ListObjectVersionsCommand,
  PutObjectCommand,
  S3Client,
} from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

const endpoint = process.env.S3_ENDPOINT?.trim();
const bucket = process.env.S3_BUCKET?.trim();

if (!bucket) throw new Error("S3_BUCKET belum diset.");

export const s3 = new S3Client({
  region: process.env.S3_REGION?.trim() ?? "auto",
  endpoint,
  // R2 dan MinIO butuh path-style; AWS S3 asli tidak.
  forcePathStyle: process.env.S3_FORCE_PATH_STYLE?.trim() === "true",

  // Checksum fleksibel dimatikan kecuali kalau operasinya memang mewajibkan.
  //
  // Sejak SDK v3.729, `getSignedUrl(GetObjectCommand)` menyelipkan
  // `x-amz-checksum-mode=ENABLED` ke query string dan IKUT MENANDATANGANINYA.
  // Backblaze B2 tidak mengenali parameter itu, sehingga tanda tangan yang ia
  // hitung berbeda dari yang ada di URL, dan setiap unduhan agent ditolak 403 —
  // meski kredensialnya benar dan URL-nya belum kedaluwarsa.
  //
  // Unggahan tidak terpengaruh, jadi gejalanya menyesatkan: upload lancar,
  // download gagal. Nilai "WHEN_REQUIRED" mengembalikan perilaku lama tanpa
  // mematikan checksum untuk operasi yang benar-benar membutuhkannya.
  requestChecksumCalculation: "WHEN_REQUIRED",
  responseChecksumValidation: "WHEN_REQUIRED",

  credentials: {
    accessKeyId: process.env.S3_ACCESS_KEY_ID?.trim() ?? "",
    secretAccessKey: process.env.S3_SECRET_ACCESS_KEY?.trim() ?? "",
  },
});

export const BUCKET = bucket;

/**
 * Masa berlaku URL unggah harus melebihi durasi transfer TERLAMA yang masuk akal,
 * bukan sekadar "cukup lama". Kalau URL kedaluwarsa di tengah jalan, upload gagal
 * di menit ke-30 tanpa cara melanjutkan — seluruh file harus diulang dari nol.
 *
 * Enam jam membuat kecepatan koneksi tidak lagi jadi penentu: bahkan di 5 Mbps,
 * 5 GB (batas satu kali unggah Backblaze) selesai jauh sebelum kedaluwarsa.
 * URL-nya tetap rahasia dan hanya berlaku untuk satu objek, jadi memperpanjang
 * masa berlakunya tidak memperluas apa yang bisa diakses.
 */
const UPLOAD_TTL = 60 * 60 * 6;
const DOWNLOAD_TTL = 60 * 60 * 6;

/** Bersihkan nama file dari path traversal dan karakter yang menyulitkan. */
export function sanitizeFilename(name: string): string {
  const base = name.split(/[\\/]/).pop() ?? "file";
  const cleaned = base.replace(/[^\w.\-]+/g, "_").slice(-120);
  return cleaned || "file";
}

export function buildKey(prefix: string, filename: string): string {
  const stamp = new Date().toISOString().slice(0, 10);
  const rand = crypto.randomUUID().slice(0, 8);
  return `${prefix}/${stamp}/${rand}-${sanitizeFilename(filename)}`;
}

export function presignUpload(key: string, contentType: string): Promise<string> {
  return getSignedUrl(
    s3,
    new PutObjectCommand({ Bucket: BUCKET, Key: key, ContentType: contentType }),
    { expiresIn: UPLOAD_TTL },
  );
}

export function presignDownload(key: string): Promise<string> {
  return getSignedUrl(s3, new GetObjectCommand({ Bucket: BUCKET, Key: key }), {
    expiresIn: DOWNLOAD_TTL,
  });
}

/**
 * Hapus objek beserta SELURUH versinya, lalu kembalikan jumlah versi terhapus.
 *
 * Bucket Backblaze B2 selalu berversi. `DeleteObject` biasa hanya menandai versi
 * terkini sebagai tersembunyi — versi lamanya tetap ada dan TETAP DITAGIH. Tombol
 * hapus yang memakai jalan itu akan berbohong: berkasnya lenyap dari tampilan
 * sementara biaya penyimpanannya jalan terus, dan pengguna baru menyadarinya
 * saat melihat tagihan.
 *
 * Maka tiap key didaftar versinya lebih dulu, baru semuanya dihapus eksplisit.
 */
export async function hapusObjek(keys: string[]): Promise<number> {
  const unik = [...new Set(keys.filter(Boolean))];
  if (unik.length === 0) return 0;

  const sasaran: { Key: string; VersionId?: string }[] = [];

  for (const key of unik) {
    let penanda: string | undefined;
    let penandaVersi: string | undefined;

    do {
      const daftar = await s3.send(
        new ListObjectVersionsCommand({
          Bucket: BUCKET,
          Prefix: key,
          KeyMarker: penanda,
          VersionIdMarker: penandaVersi,
        }),
      );

      // Prefix bisa mengenai key lain yang kebetulan berawalan sama, jadi
      // kecocokannya diperiksa persis. Menghapus berdasarkan prefix saja adalah
      // cara satu klik menghapus berkas milik project lain.
      for (const v of [...(daftar.Versions ?? []), ...(daftar.DeleteMarkers ?? [])]) {
        if (v.Key === key) sasaran.push({ Key: v.Key, VersionId: v.VersionId });
      }

      penanda = daftar.IsTruncated ? daftar.NextKeyMarker : undefined;
      penandaVersi = daftar.IsTruncated ? daftar.NextVersionIdMarker : undefined;
    } while (penanda || penandaVersi);
  }

  if (sasaran.length === 0) return 0;

  // DeleteObjects membatasi 1000 objek per panggilan.
  let terhapus = 0;
  for (let i = 0; i < sasaran.length; i += 1000) {
    const hasil = await s3.send(
      new DeleteObjectsCommand({
        Bucket: BUCKET,
        Delete: { Objects: sasaran.slice(i, i + 1000), Quiet: true },
      }),
    );
    terhapus += sasaran.slice(i, i + 1000).length - (hasil.Errors?.length ?? 0);
    for (const e of hasil.Errors ?? []) {
      console.error(`gagal menghapus ${e.Key}: ${e.Code} ${e.Message}`);
    }
  }
  return terhapus;
}
