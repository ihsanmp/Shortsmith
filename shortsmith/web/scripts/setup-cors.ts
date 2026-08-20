/**
 * Pasang aturan CORS di bucket Backblaze B2.
 *
 * Kenapa Native API, bukan S3 PutBucketCors: bucket ini sudah punya aturan CORS
 * native, dan B2 menolak keduanya dipakai bersamaan —
 * "The bucket contains B2 Native CORS rules. Please use B2 Native API instead."
 *
 * Kenapa skrip, bukan klik di dashboard: aturan CORS harus persis sama dengan
 * yang dilakukan browser (metode PUT, header content-type, origin produksi DAN
 * localhost). Mengetiknya ulang di form adalah tempat salah ketik berubah jadi
 * "koneksi terputus" yang membingungkan selama setengah jam.
 *
 * Kredensial B2 hanya ada di Vercel. Tarik dulu, lalu jalankan — dua-duanya
 * dari folder web/:
 *
 *     vercel env pull .env.vercel.local --environment=production
 *     npm run storage:cors
 *
 * Skrip ini tidak pernah mencetak nilai kredensial.
 * Aman diulang: b2_update_bucket mengganti seluruh aturan, bukan menumpuk.
 */
import { config } from "dotenv";

// Urutan menentukan: yang lebih dulu menang. File dari Vercel didahulukan
// karena di sanalah kredensial B2 yang sebenarnya berada.
config({ path: [".env.vercel.local", ".env.local"] });

/**
 * Nama bucket dan endpoint BUKAN rahasia — keduanya muncul apa adanya di setiap
 * presigned URL yang dikirim ke browser. Karena `vercel env pull` mengembalikan
 * nilai sensitif sebagai string kosong, keduanya dipakai sebagai default di
 * sini. Env tetap menang kalau memang terisi.
 */
const BUCKET = process.env.S3_BUCKET?.trim() || "shortsmith-edits23";

const ORIGINS = ["https://shortsmith-ten.vercel.app", "http://localhost:3000"];

const NAMA_ATURAN = "shortsmith-browser-upload";

// Unggahan dari browser memakai presigned S3, bukan native. Nama operasi S3
// disertakan karena itu yang sebenarnya dipakai; nama native ikut supaya
// agent Python yang memakai jalur native juga tercakup.
const OPERASI_S3 = ["s3_put", "s3_get", "s3_head", "s3_post"];
const OPERASI_NATIVE = [
  "b2_upload_file",
  "b2_upload_part",
  "b2_download_file_by_name",
  "b2_download_file_by_id",
];

function rahasia(nama: string): string {
  const v = process.env[nama]?.trim();
  if (!v) {
    console.error(`[X] ${nama} tidak ditemukan.`);
    console.error("    Tarik dulu dari Vercel, lalu ulangi:");
    console.error("    vercel env pull .env.vercel.local --environment=production");
    process.exit(1);
  }
  return v;
}

type Auth = { apiUrl: string; token: string; accountId: string };

async function authorize(): Promise<Auth> {
  const keyId = rahasia("S3_ACCESS_KEY_ID");
  const appKey = rahasia("S3_SECRET_ACCESS_KEY");
  const basic = Buffer.from(`${keyId}:${appKey}`).toString("base64");

  const res = await fetch("https://api.backblazeb2.com/b2api/v3/b2_authorize_account", {
    headers: { Authorization: `Basic ${basic}` },
  });
  if (!res.ok) {
    throw new Error(`b2_authorize_account gagal (HTTP ${res.status}): ${await res.text()}`);
  }
  const j = (await res.json()) as Record<string, any>;

  // Bentuk respons berbeda antar versi API: v2 menaruh apiUrl di akar, v3
  // memindahkannya ke apiInfo.storageApi. Keduanya ditangani supaya skrip tidak
  // pecah kalau akun ini kebetulan dilayani versi lain.
  const apiUrl = j.apiInfo?.storageApi?.apiUrl ?? j.apiUrl;
  if (!apiUrl) throw new Error("Respons b2_authorize_account tidak memuat apiUrl.");

  return { apiUrl, token: j.authorizationToken, accountId: j.accountId };
}

async function panggil(auth: Auth, fungsi: string, body: unknown): Promise<any> {
  const res = await fetch(`${auth.apiUrl}/b2api/v3/${fungsi}`, {
    method: "POST",
    headers: { Authorization: auth.token, "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const teks = await res.text();
  if (!res.ok) {
    const err: any = new Error(`${fungsi} gagal (HTTP ${res.status}): ${teks}`);
    err.status = res.status;
    err.body = teks;
    throw err;
  }
  return JSON.parse(teks);
}

function aturan(operasi: string[]) {
  return [
    {
      corsRuleName: NAMA_ATURAN,
      allowedOrigins: ORIGINS,
      allowedOperations: operasi,
      // Browser mengirim content-type di preflight; menolaknya menggagalkan
      // seluruh unggahan sebelum byte pertama terkirim.
      allowedHeaders: ["*"],
      exposeHeaders: ["etag"],
      maxAgeSeconds: 3600,
    },
  ];
}

async function main() {
  console.log(`bucket  : ${BUCKET}`);
  console.log(`origins : ${ORIGINS.join(", ")}\n`);

  const auth = await authorize();

  const daftar = await panggil(auth, "b2_list_buckets", {
    accountId: auth.accountId,
    bucketName: BUCKET,
  });
  const bucket = daftar.buckets?.[0];
  if (!bucket) {
    throw new Error(
      `Bucket '${BUCKET}' tidak ditemukan di akun ini. Periksa namanya, atau ` +
        "application key-mu mungkin dibatasi ke bucket lain.",
    );
  }

  // Aturan lama dicetak apa adanya. Inilah yang menjelaskan kenapa unggahan
  // ditolak, dan sekaligus contoh nyata nama operasi yang diterima B2.
  console.log("aturan CORS yang ADA SEKARANG:");
  console.dir(bucket.corsRules ?? [], { depth: null });
  console.log();

  const perbarui = (operasi: string[]) =>
    panggil(auth, "b2_update_bucket", {
      accountId: auth.accountId,
      bucketId: bucket.bucketId,
      corsRules: aturan(operasi),
    });

  let hasil: any;
  try {
    hasil = await perbarui([...OPERASI_S3, ...OPERASI_NATIVE]);
  } catch (err: any) {
    // Kalau B2 menolak salah satu nama operasi, ia menyebutkannya di pesan
    // error. Mundur ke set native saja, lalu laporkan apa yang terjadi —
    // lebih berguna daripada gagal total karena satu nama tidak dikenal.
    if (err.status === 400) {
      console.warn("set lengkap ditolak B2:", err.body);
      console.warn("mencoba ulang dengan operasi native saja...\n");
      hasil = await perbarui(OPERASI_NATIVE);
    } else {
      throw err;
    }
  }

  console.log("[ok] aturan CORS dipasang:");
  console.dir(hasil.corsRules, { depth: null });
}

main().catch((err) => {
  console.error("\n[X] gagal:", err?.message ?? err);
  if (String(err?.message).includes("401")) {
    console.error(
      "    401 berarti kredensialnya ditolak. Application key B2 juga butuh " +
        "kapabilitas writeBuckets untuk mengubah aturan CORS — key yang hanya " +
        "bisa baca/tulis objek tidak cukup.",
    );
  }
  process.exit(1);
});
