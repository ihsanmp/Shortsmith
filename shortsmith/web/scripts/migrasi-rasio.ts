/**
 * Tambahkan kolom `projects.rasio`.
 *
 *     npm run db:migrasi-rasio
 *
 * Nilainya string rasio ("9:16", "16:9", ...) atau "auto" yang berarti
 * serahkan pada jenis dan konsep. Disimpan sebagai text, bukan enum: daftar
 * rasio hidup di agent (RASIO di models.py) dan menambah satu di sana tidak
 * boleh menuntut migrasi database.
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.local", ".env.vercel.local"] });
const url = process.env.DATABASE_URL?.trim();
if (!url) { console.error("[X] DATABASE_URL tidak ditemukan"); process.exit(1); }
const sql = postgres(url, { max: 1, prepare: false });

async function main() {
  await sql`ALTER TABLE projects ADD COLUMN IF NOT EXISTS rasio text NOT NULL DEFAULT 'auto'`;
  console.log("[ok] kolom projects.rasio siap");
  const k = await sql`
    SELECT column_name, data_type, column_default
    FROM information_schema.columns
    WHERE table_schema='public' AND table_name='projects' AND column_name='rasio'
  `;
  console.table(k);
  const s = await sql`SELECT rasio, count(*)::int AS n FROM projects GROUP BY rasio`;
  console.table(s);
}
main().then(() => sql.end()).catch(async (e) => {
  console.error("[X]", e); await sql.end(); process.exit(1);
});
