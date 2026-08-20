/**
 * Tambahkan projects.bahan_folder dan tabel agent_info.
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
  await sql`
    ALTER TABLE assets ADD COLUMN IF NOT EXISTS bahan_folder text NOT NULL DEFAULT ''
  `;
  console.log("[ok] kolom assets.bahan_folder siap");

  // Kolom di projects dibuang: folder disimpan per BERKAS sekarang, karena
  // rekaman suara dan klip B-roll punya peran berbeda dan wajar berada di
  // folder berbeda. Aman dibuang — belum pernah terisi oleh project mana pun.
  const [sisa] = await sql`
    SELECT count(*)::int AS n FROM information_schema.columns
    WHERE table_name = 'projects' AND column_name = 'bahan_folder'
  `;
  if (sisa.n > 0) {
    const [terpakai] = await sql`
      SELECT count(*)::int AS n FROM projects WHERE bahan_folder <> ''
    `;
    if (terpakai.n > 0) {
      console.log(`[!] ${terpakai.n} project memakai projects.bahan_folder — TIDAK dibuang`);
    } else {
      await sql`ALTER TABLE projects DROP COLUMN bahan_folder`;
      console.log("[ok] projects.bahan_folder dibuang (belum pernah terpakai)");
    }
  }

  await sql`
    CREATE TABLE IF NOT EXISTS agent_info (
      kunci text PRIMARY KEY,
      data jsonb NOT NULL,
      updated_at timestamptz NOT NULL DEFAULT now()
    )
  `;
  console.log("[ok] tabel agent_info siap");

  const kolom = await sql`
    SELECT column_name, data_type, column_default, is_nullable
    FROM information_schema.columns
    WHERE table_name = 'assets' AND column_name = 'bahan_folder'
  `;
  console.log("[ok] dibaca kembali dari server:");
  console.table(kolom);

  // Baris lama semuanya lokal=false, jadi seluruh project yang sudah ada tetap
  // memakai jalur unggah persis seperti sebelumnya.
  const [{ count }] = await sql`SELECT count(*)::int AS count FROM agent_info`;
  console.log(`[i] ${count} baris di agent_info (diisi agent saat melapor)`);
}

main()
  .catch((err) => {
    console.error("\n[X] gagal:", err?.message ?? err);
    process.exitCode = 1;
  })
  .finally(() => sql.end());
