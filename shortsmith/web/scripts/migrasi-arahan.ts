/**
 * Tambah kolom `arahan` ke tabel projects.
 *
 * Empat komponen brief yang wajib terpenuhi kalau diisi: narasi, kesan, tujuan
 * campaign, dan CTA. NULL berarti tidak diisi — keadaan biasa, dan seluruh alur
 * lama berjalan seperti sebelumnya.
 *
 *     npx tsx scripts/migrasi-arahan.ts
 *
 * Ditulis sebagai skrip, bukan `drizzle-kit push`, mengikuti pola
 * migrasi-urutan.ts: push jatuh oleh bug internalnya di database ini.
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.local", ".env.vercel.local"] });
const url = process.env.DATABASE_URL?.trim();
if (!url) {
  console.error("[X] DATABASE_URL tidak ada");
  process.exit(1);
}
const sql = postgres(url, { max: 1, prepare: false, connect_timeout: 15 });

async function main() {
  try {
    await sql`ALTER TABLE projects ADD COLUMN IF NOT EXISTS arahan jsonb`;
    console.log("[ok] kolom arahan ditambahkan");

    // Dibaca ULANG dari server, bukan disimpulkan dari perintah yang tidak
    // melempar galat. Yang membuktikan kolomnya ada cuma kolomnya sendiri.
    const [kolom] = await sql`
      SELECT data_type, is_nullable
      FROM information_schema.columns
      WHERE table_name = 'projects' AND column_name = 'arahan'
    `;
    if (!kolom) {
      console.error("[X] kolom tidak terbaca setelah migrasi");
      process.exit(1);
    }
    console.log(`[ok] terbaca: ${kolom.data_type}, nullable=${kolom.is_nullable}`);

    const [{ n }] = await sql`SELECT count(*)::int AS n FROM projects`;
    console.log(`[ok] ${n} project ada; semuanya arahan NULL (belum diisi)`);
  } finally {
    await sql.end();
  }
}

main();
