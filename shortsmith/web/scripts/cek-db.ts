/**
 * Periksa apakah database masih menerima koneksi.
 *
 * Dipakai saat /api/jobs/next menggantung sementara halaman statis tetap
 * cepat — itu memisahkan "Vercel bermasalah" dari "database bermasalah", dan
 * keduanya butuh tindakan yang sangat berbeda.
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.vercel.local", ".env.local"] });

const url = process.env.DATABASE_URL?.trim();
if (!url) {
  console.error("[X] DATABASE_URL tidak ada");
  process.exit(1);
}

// Host disamarkan sebagian: cukup untuk tahu pooler mana yang dipakai, tanpa
// menaruh kredensial di layar.
const host = url.replace(/^.*@/, "").split("/")[0];
console.log(`host: ${host}`);

const sql = postgres(url, { max: 1, prepare: false, connect_timeout: 15 });

async function main() {
    const t0 = Date.now();
  try {
    const [r] = await sql<{ n: number }[]>`SELECT 1 AS n`;
    console.log(`[ok] SELECT 1 -> ${r.n}  (${Date.now() - t0} ms)`);

    const [c] = await sql<{ total: number; aktif: number }[]>`
    SELECT count(*)::int AS total,
           count(*) FILTER (WHERE state = 'active')::int AS aktif
    FROM pg_stat_activity
  `;
    console.log(`[ok] koneksi terpakai: ${c.total} (aktif: ${c.aktif})`);

    const [j] = await sql<{ pending: number; processing: number }[]>`
    SELECT count(*) FILTER (WHERE status = 'pending')::int AS pending,
           count(*) FILTER (WHERE status = 'processing')::int AS processing
    FROM jobs
  `;
    console.log(`[ok] job pending: ${j.pending}, processing: ${j.processing}`);
  } catch (err) {
    console.error(`[X] gagal setelah ${Date.now() - t0} ms:`, (err as Error).message);
    process.exitCode = 1;
  } finally {
    await sql.end();
}
}

main();
