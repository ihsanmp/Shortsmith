/**
 * Tambah kolom `keterangan` ke assets.
 *
 *     npx tsx scripts/migrasi-keterangan.ts
 *
 * Teks yang ditempel saat mengunggah klip: pembuka, ringkas isinya, tagar.
 * Ditulis agent dari ucapan di dalam klip itu sendiri.
 *
 * Namanya bukan "caption" dengan sengaja. Di aplikasi ini "caption" sudah
 * berarti SUBTITLE yang dibakar ke gambar (lihat CaptionStyle), dan dua hal
 * berbeda dengan satu nama adalah cara paling mudah menyalakan bug yang tidak
 * terlihat.
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.local", ".env.vercel.local"] });
const url = process.env.DATABASE_URL?.trim();
if (!url) { console.error("[X] DATABASE_URL tidak ditemukan"); process.exit(1); }
const sql = postgres(url, { max: 1, prepare: false });

async function main() {
  try {
    await sql`ALTER TABLE assets ADD COLUMN IF NOT EXISTS keterangan text`;
    const [k] = await sql<{ data_type: string }[]>`
      SELECT data_type FROM information_schema.columns
       WHERE table_name = 'assets' AND column_name = 'keterangan'
    `;
    if (!k) { console.error("[X] kolom keterangan tidak ada"); process.exitCode = 1; return; }
    console.log(`[ok] assets.keterangan (${k.data_type})`);
  } finally {
    await sql.end();
  }
}

main();
