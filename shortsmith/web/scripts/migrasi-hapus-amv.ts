/**
 * Buang nilai 'amv' dari enum `video_jenis`.
 *
 *     npm run db:migrasi-hapus-amv
 *
 * Postgres tidak punya `ALTER TYPE ... DROP VALUE`, jadi satu-satunya cara
 * adalah membangun ulang tipenya. Urutannya tidak boleh ditukar: kolom
 * `projects.jenis` punya DEFAULT yang bertipe enum lama, dan mengubah tipe
 * kolom sementara default-nya masih menunjuk ke tipe itu akan ditolak.
 *
 * Dijalankan di dalam SATU transaksi. Kalau ada langkah yang gagal di tengah,
 * tabelnya tidak boleh tertinggal tanpa tipe atau tanpa default.
 *
 * Penjagaan yang paling penting ada di awal: kalau ternyata ADA baris yang
 * memakai 'amv', skrip ini berhenti tanpa mengubah apa pun. Membuang nilai
 * enum yang masih dipakai berarti kehilangan data project seseorang.
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.local", ".env.vercel.local"] });
const url = process.env.DATABASE_URL?.trim();
if (!url) { console.error("[X] DATABASE_URL tidak ditemukan"); process.exit(1); }
const sql = postgres(url, { max: 1, prepare: false });

async function main() {
  const [{ n }] = await sql<{ n: number }[]>`
    SELECT count(*)::int AS n FROM projects WHERE jenis = 'amv'
  `;
  if (n > 0) {
    console.error(`[X] ${n} project masih berjenis 'amv'. Tidak ada yang diubah.`);
    console.error("    Ubah dulu jenisnya, atau hapus project-nya, lalu jalankan lagi.");
    process.exitCode = 1;
    return;
  }
  console.log("[ok] tidak ada project berjenis 'amv'");

  const sebelum = await sql`SELECT unnest(enum_range(NULL::video_jenis))::text AS nilai`;
  console.log("     sebelum:", sebelum.map((r) => r.nilai).join(", "));

  await sql.begin(async (tx) => {
    await tx`ALTER TABLE projects ALTER COLUMN jenis DROP DEFAULT`;
    await tx`ALTER TYPE video_jenis RENAME TO video_jenis_lama`;
    await tx`CREATE TYPE video_jenis AS ENUM ('short', 'cinematic', 'podcast')`;
    await tx`
      ALTER TABLE projects
        ALTER COLUMN jenis TYPE video_jenis USING jenis::text::video_jenis
    `;
    await tx`ALTER TABLE projects ALTER COLUMN jenis SET DEFAULT 'short'`;
    await tx`DROP TYPE video_jenis_lama`;
  });

  const sesudah = await sql`SELECT unnest(enum_range(NULL::video_jenis))::text AS nilai`;
  console.log("     sesudah:", sesudah.map((r) => r.nilai).join(", "));

  const cek = await sql`
    SELECT column_default, is_nullable FROM information_schema.columns
     WHERE table_name = 'projects' AND column_name = 'jenis'
  `;
  console.table(cek);
  const isi = await sql`SELECT jenis, count(*)::int AS n FROM projects GROUP BY jenis`;
  console.table(isi);
}
main().then(() => sql.end()).catch(async (e) => {
  console.error("[X]", e); await sql.end(); process.exit(1);
});
