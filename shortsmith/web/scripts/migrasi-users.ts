/**
 * Buat tabel `users`.
 *
 * Ditulis manual mengikuti pola migrasi lain di folder ini — `drizzle-kit push`
 * jatuh oleh bug internalnya sendiri saat membaca CHECK constraint dari database
 * ini ("Cannot read properties of undefined (reading 'replace')").
 *
 *     npm run db:migrasi-users
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

const sql = postgres(url, { max: 1, prepare: false });

async function main() {
  await sql`
    CREATE TABLE IF NOT EXISTS users (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      email text NOT NULL UNIQUE,
      password_hash text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      last_login_at timestamptz
    )
  `;
  console.log("[ok] tabel users siap");

  // Email disimpan huruf kecil oleh aplikasi, tapi indeks ini membuat aturannya
  // ditegakkan database — bukan hanya disepakati kode yang menulisnya.
  await sql`
    CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_idx ON users (lower(email))
  `;
  console.log("[ok] indeks unik lower(email) siap");

  const kolom = await sql`
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_name = 'users'
    ORDER BY ordinal_position
  `;
  console.log("[ok] dibaca kembali dari server:");
  console.table(kolom);

  const [{ count }] = await sql`SELECT count(*)::int AS count FROM users`;
  console.log(`[i] ${count} akun terdaftar`);
}

main()
  .then(() => sql.end())
  .catch(async (e) => {
    console.error("[X]", e);
    await sql.end();
    process.exit(1);
  });
