/**
 * Uji apakah video hasil benar-benar bisa diunduh dari storage.
 *
 * Pemutar di halaman project yang diam di 0:00 tidak memberi tahu apa pun soal
 * penyebabnya — browser menyembunyikan status HTTP-nya. Skrip ini mengambil
 * key hasil terakhir, menandatanganinya persis seperti aplikasi, lalu memanggil
 * URL-nya dan menampilkan jawaban mentah dari B2.
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.vercel.local", ".env.local"] });

const url = process.env.DATABASE_URL?.trim();
if (!url) {
  console.error("[X] DATABASE_URL tidak ada");
  process.exit(1);
}

const sql = postgres(url, { max: 1, prepare: false, connect_timeout: 15 });

async function main() {
  const [aset] = await sql<{ storage_key: string; nama_file: string; ukuran_bytes: number | null }[]>`
    SELECT storage_key, nama_file, ukuran_bytes
    FROM assets WHERE jenis = 'output' ORDER BY created_at DESC LIMIT 1
  `;
  if (!aset) {
    console.log("belum ada hasil di database");
    return;
  }
  console.log(`hasil terakhir : ${aset.nama_file}`);
  console.log(`key            : ${aset.storage_key}`);
  console.log(`ukuran tercatat: ${aset.ukuran_bytes ? (aset.ukuran_bytes / 1e6).toFixed(1) + " MB" : "—"}`);

  const { presignDownload } = await import("../lib/storage");
  const tautan = await presignDownload(aset.storage_key);

  // Range 0-1023: cukup untuk tahu apakah unduhan diizinkan, tanpa menghabiskan
  // kuota yang justru sedang diperiksa.
  const res = await fetch(tautan, { headers: { Range: "bytes=0-1023" } });
  console.log(`\nHTTP ${res.status} ${res.statusText}`);
  if (!res.ok) {
    console.log((await res.text()).trim());
  } else {
    console.log(`content-length: ${res.headers.get("content-length")}`);
    console.log(`content-type  : ${res.headers.get("content-type")}`);
    console.log("[ok] storage mengizinkan unduhan");
  }
}

main()
  .catch((e) => {
    console.error("[X] gagal:", (e as Error).message);
    process.exitCode = 1;
  })
  .finally(() => sql.end());
