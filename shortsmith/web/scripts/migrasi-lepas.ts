/**
 * Pisahkan "agent hilang" dari "job gagal" di tabel `jobs`.
 *
 *     npx tsx scripts/migrasi-lepas.ts
 *
 * ## Kenapa dua hitungan, bukan satu
 *
 * `retry_count` ada untuk menghentikan job yang MEMANG rusak supaya tidak
 * berputar selamanya. Ia dinaikkan saat agent melaporkan kegagalan — itu bukti
 * tentang job-nya.
 *
 * Agent yang hilang bukan bukti apa pun tentang job-nya. PC-nya tidur, listrik
 * padam, atau daemonnya di-restart untuk memasang versi baru. Menaikkan
 * `retry_count` di situ berarti menghukum job untuk sesuatu yang tidak ada
 * hubungannya dengannya.
 *
 * Terjadi sungguhan dan mahal: satu job podcast menunggu pengguna mencentang
 * topik — duduk di `processing` tanpa menghitung apa pun, keadaan yang paling
 * lama dan paling rentan — lalu daemon di-restart untuk memasang perbaikan.
 * Server membacanya sebagai percobaan gagal ketiga, dan job itu ditandai gagal
 * permanen padahal tidak ada satu pun yang salah dengannya.
 *
 * Hitungannya tetap DIBATASI, cuma jauh lebih longgar: job yang benar-benar
 * membuat agent-nya mati tiap kali (kehabisan memori, driver jatuh) harus tetap
 * berhenti sendiri, bukan mengulang analisis satu jam berkali-kali selamanya.
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.local", ".env.vercel.local"] });
const url = process.env.DATABASE_URL?.trim();
if (!url) {
  console.error("[X] DATABASE_URL tidak ditemukan");
  process.exit(1);
}
const sql = postgres(url, { max: 1, prepare: false });

async function main() {
  try {
    await sql`
      ALTER TABLE jobs
        ADD COLUMN IF NOT EXISTS lepas_count integer NOT NULL DEFAULT 0
    `;

    // Dibaca ULANG dari server. ALTER yang sukses tanpa efek — misalnya karena
    // menyentuh database yang salah — terlihat persis sama dengan yang berhasil.
    const [kolom] = await sql<{ data_type: string; column_default: string }[]>`
      SELECT data_type, column_default
        FROM information_schema.columns
       WHERE table_name = 'jobs' AND column_name = 'lepas_count'
    `;
    if (!kolom) {
      console.error("[X] kolom lepas_count tidak ada setelah migrasi");
      process.exitCode = 1;
      return;
    }
    console.log(`[ok] jobs.lepas_count (${kolom.data_type}, default ${kolom.column_default})`);
  } finally {
    await sql.end();
  }
}

main();
