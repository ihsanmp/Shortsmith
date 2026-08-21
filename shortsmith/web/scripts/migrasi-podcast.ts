/**
 * Tambahkan nilai 'podcast' ke enum video_jenis.
 *
 *     npm run db:migrasi-podcast
 *
 * Aman diulang: IF NOT EXISTS didukung ALTER TYPE ... ADD VALUE sejak PG 12.
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.local", ".env.vercel.local"] });
const url = process.env.DATABASE_URL?.trim();
if (!url) { console.error("[X] DATABASE_URL tidak ditemukan"); process.exit(1); }
const sql = postgres(url, { max: 1, prepare: false });

async function main() {
  await sql`ALTER TYPE video_jenis ADD VALUE IF NOT EXISTS 'podcast'`;
  console.log("[ok] nilai 'podcast' siap");
  const nilai = await sql`
    SELECT e.enumlabel AS jenis
    FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
    WHERE t.typname = 'video_jenis' ORDER BY e.enumsortorder
  `;
  console.table(nilai);
}
main().then(() => sql.end()).catch(async (e) => {
  console.error("[X]", e); await sql.end(); process.exit(1);
});
