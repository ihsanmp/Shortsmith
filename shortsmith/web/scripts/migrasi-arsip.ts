/**
 * Tambah kolom `arsip` ke concept_profiles.
 *
 *     npx tsx scripts/migrasi-arsip.ts
 *
 * Konsep yang masih dipakai project TIDAK BISA dihapus — `projects.concept_id`
 * memakai onDelete: "restrict", supaya merapikan daftar konsep tidak pernah
 * melenyapkan project beserta hasil rendernya.
 *
 * Tapi yang sebenarnya diinginkan pengguna saat menekan Hapus biasanya bukan
 * "musnahkan", melainkan "jangan tampilkan lagi". Arsip memberikan itu tanpa
 * menyentuh satu pun project: barisnya tetap ada, project yang menunjuknya
 * tetap utuh, dan ia hilang dari daftar pilihan.
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.local", ".env.vercel.local"] });
const url = process.env.DATABASE_URL?.trim();
if (!url) { console.error("[X] DATABASE_URL tidak ditemukan"); process.exit(1); }
const sql = postgres(url, { max: 1, prepare: false });

async function main() {
  try {
    await sql`
      ALTER TABLE concept_profiles
        ADD COLUMN IF NOT EXISTS arsip boolean NOT NULL DEFAULT false
    `;
    // Dibaca ULANG dari server: ALTER yang sukses tanpa efek terlihat sama
    // dengan yang berhasil.
    const [k] = await sql<{ data_type: string; column_default: string }[]>`
      SELECT data_type, column_default
        FROM information_schema.columns
       WHERE table_name = 'concept_profiles' AND column_name = 'arsip'
    `;
    if (!k) { console.error("[X] kolom arsip tidak ada setelah migrasi"); process.exitCode = 1; return; }
    console.log(`[ok] concept_profiles.arsip (${k.data_type}, default ${k.column_default})`);
  } finally {
    await sql.end();
  }
}

main();
