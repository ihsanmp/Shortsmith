/**
 * Buat tabel `tugas` dan enum `tugas_tipe`.
 *
 *     npm run db:migrasi-tugas
 *
 * Antrean permintaan singkat ke agent yang bukan render: menulis prompt Google
 * Flow, dan memeriksa klip hasil generate terhadap bahan asli. Alasan ia tidak
 * ikut menumpang tabel `jobs` ada di komentar db/schema.ts.
 *
 * Ditulis sebagai skrip, bukan `drizzle-kit push`, mengikuti migrasi-migrasi
 * sebelumnya di folder ini — push jatuh oleh bug internalnya di database ini.
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.local", ".env.vercel.local"] });
const url = process.env.DATABASE_URL?.trim();
if (!url) { console.error("[X] DATABASE_URL tidak ditemukan"); process.exit(1); }
const sql = postgres(url, { max: 1, prepare: false });

async function main() {
  // Enum dibuat lebih dulu, dan idempoten: CREATE TYPE tidak punya
  // IF NOT EXISTS, jadi menjalankan skrip ini dua kali akan jatuh tanpa
  // penjagaan ini.
  await sql`
    DO $$ BEGIN
      CREATE TYPE tugas_tipe AS ENUM ('prompt', 'review');
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$
  `;
  console.log("[ok] enum tugas_tipe siap");

  await sql`
    CREATE TABLE IF NOT EXISTS tugas (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tipe tugas_tipe NOT NULL,
      status job_status NOT NULL DEFAULT 'pending',
      permintaan jsonb NOT NULL,
      hasil jsonb,
      error_message text,
      user_id uuid REFERENCES users(id) ON DELETE CASCADE,
      heartbeat_at timestamptz,
      finished_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now()
    )
  `;
  console.log("[ok] tabel tugas siap");

  await sql`
    CREATE INDEX IF NOT EXISTS tugas_queue_idx ON tugas (status, created_at)
  `;
  console.log("[ok] index tugas_queue_idx siap");

  const k = await sql`
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_schema='public' AND table_name='tugas'
    ORDER BY ordinal_position
  `;
  console.table(k);
}
main().then(() => sql.end()).catch(async (e) => {
  console.error("[X]", e); await sql.end(); process.exit(1);
});
