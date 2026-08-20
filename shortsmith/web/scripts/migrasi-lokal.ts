/**
 * Tambahkan kolom `assets.lokal`.
 *
 * Ditulis manual karena `drizzle-kit push` jatuh oleh bug internalnya sendiri
 * saat membaca CHECK constraint dari database ini ("Cannot read properties of
 * undefined (reading 'replace')"). Perubahannya sendiri sederhana dan aditif.
 *
 *     npm run db:migrasi-lokal
 *
 * Aman diulang: IF NOT EXISTS membuat pemanggilan kedua tidak melakukan apa-apa.
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.vercel.local", ".env.local"] });

const url = process.env.DATABASE_URL?.trim();
if (!url) {
  console.error("[X] DATABASE_URL tidak ditemukan di .env.local maupun .env.vercel.local");
  process.exit(1);
}

// max: 1 — migrasi tidak butuh pool, dan koneksi tunggal membuat urutan
// perintahnya pasti. prepare: false karena Supabase memakai transaction pooler.
const sql = postgres(url, { max: 1, prepare: false });

async function main() {
  await sql`ALTER TABLE assets ADD COLUMN IF NOT EXISTS lokal boolean NOT NULL DEFAULT false`;
  console.log("[ok] kolom lokal siap");

  const kolom = await sql`
    SELECT column_name, data_type, column_default, is_nullable
    FROM information_schema.columns
    WHERE table_name = 'assets' AND column_name = 'lokal'
  `;
  console.log("[ok] dibaca kembali dari server:");
  console.table(kolom);

  // Baris lama semuanya lokal=false, jadi seluruh project yang sudah ada tetap
  // memakai jalur unggah persis seperti sebelumnya.
  const [{ count }] = await sql`
    SELECT count(*)::int AS count FROM assets WHERE jenis = 'raw'
  `;
  console.log(`[i] ${count} baris raw lama tetap lokal=false (jalur unggah, tidak berubah)`);
}

main()
  .catch((err) => {
    console.error("\n[X] gagal:", err?.message ?? err);
    process.exitCode = 1;
  })
  .finally(() => sql.end());
