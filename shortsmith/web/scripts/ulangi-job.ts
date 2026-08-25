/**
 * Kembalikan job yang gagal ke antrean.
 *
 * Dipakai setelah bug di agent diperbaiki: job yang gagal permanen karena bug
 * itu tidak salah apa-apa, dan menyuruh pengguna mengisi ulang formnya berarti
 * mengunggah lagi bahan yang sudah ada di server.
 *
 * `retry_count` ikut dinolkan. Tanpa itu job langsung gagal permanen lagi pada
 * percobaan berikutnya, karena hitungannya sudah mentok di batas.
 *
 * Tanpa argumen: menampilkan job gagal terbaru tanpa mengubah apa pun. Baru
 * dengan id-nya ia benar-benar diantre ulang — supaya tidak ada job yang
 * terlanjur diulang hanya karena skripnya dijalankan untuk melihat-lihat.
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
const id = process.argv[2];

async function main() {
  try {
  if (!id) {
    const rows = await sql`
      SELECT id, status, retry_count,
             left(coalesce(error_message, ''), 90) AS galat,
             coalesce(finished_at, created_at) AS waktu
        FROM jobs
       WHERE status = 'failed'
       ORDER BY coalesce(finished_at, created_at) DESC
       LIMIT 5
    `;
    if (!rows.length) {
      console.log("tidak ada job yang gagal");
    } else {
      console.log("job gagal terbaru:\n");
      for (const r of rows) {
        console.log(`  ${r.id}  retry=${r.retry_count}  ${r.waktu.toISOString()}`);
        console.log(`    ${r.galat}\n`);
      }
      console.log("jalankan ulang dengan: npx tsx scripts/ulangi-job.ts <id>");
    }
  } else {
    const [row] = await sql`
      UPDATE jobs
         SET status = 'pending', retry_count = 0, error_message = NULL,
             heartbeat_at = NULL, progress = 0, tahap = '',
             started_at = NULL, finished_at = NULL
       WHERE id = ${id} AND status = 'failed'
      RETURNING id, status, retry_count
    `;
    if (!row) {
      console.error(`[X] job ${id} tidak ada, atau statusnya bukan 'failed'`);
      process.exit(1);
    }
    console.log(`[OK] ${row.id} -> ${row.status} (retry ${row.retry_count})`);
  }
  } finally {
    await sql.end();
  }
}

main();
