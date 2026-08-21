/**
 * Tambahkan kolom `projects.jenis`.
 *
 *     npm run db:migrasi-jenis
 *
 * Aman diulang: enum dan kolomnya sama-sama dibuat kalau belum ada.
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
  // CREATE TYPE tidak punya IF NOT EXISTS di semua versi Postgres, jadi
  // keberadaannya diperiksa lebih dulu.
  await sql`
    DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'video_jenis') THEN
        CREATE TYPE video_jenis AS ENUM ('short', 'cinematic', 'amv');
      END IF;
    END $$
  `;
  console.log("[ok] tipe video_jenis siap");

  // Project lama semuanya short — itulah satu-satunya yang pernah bisa dibuat,
  // jadi default ini bukan tebakan melainkan fakta.
  await sql`
    ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS jenis video_jenis NOT NULL DEFAULT 'short'
  `;
  console.log("[ok] kolom projects.jenis siap");

  const kolom = await sql`
    SELECT column_name, data_type, udt_name, column_default
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'projects' AND column_name = 'jenis'
  `;
  console.table(kolom);

  const sebaran = await sql`SELECT jenis, count(*)::int AS n FROM projects GROUP BY jenis`;
  console.log("[i] sebaran jenis pada project yang ada:");
  console.table(sebaran);
}

main().then(() => sql.end()).catch(async (e) => {
  console.error("[X]", e);
  await sql.end();
  process.exit(1);
});
