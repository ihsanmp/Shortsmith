/**
 * Kolom profil di `users`, dan tabel `sessions`.
 *
 *     npm run db:migrasi-profil
 *
 * Aman diulang: IF NOT EXISTS di semua perintahnya.
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.vercel.local", ".env.local"] });

const url = process.env.DATABASE_URL?.trim();
if (!url) {
  console.error("[X] DATABASE_URL tidak ditemukan");
  process.exit(1);
}

const sql = postgres(url, { max: 1, prepare: false });

async function main() {
  await sql`ALTER TABLE users ADD COLUMN IF NOT EXISTS username text NOT NULL DEFAULT 'user'`;
  await sql`ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_key text`;
  console.log("[ok] kolom username & avatar_key siap");

  await sql`
    CREATE TABLE IF NOT EXISTS sessions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      user_agent text NOT NULL DEFAULT '',
      created_at timestamptz NOT NULL DEFAULT now(),
      last_seen_at timestamptz NOT NULL DEFAULT now()
    )
  `;
  await sql`CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id)`;
  console.log("[ok] tabel sessions siap");

  const kolom = await sql`
    SELECT column_name, data_type, column_default
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'users'
    ORDER BY ordinal_position
  `;
  console.log("[ok] public.users:");
  console.table(kolom);

  const s = await sql`
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'sessions'
    ORDER BY ordinal_position
  `;
  console.log("[ok] public.sessions:");
  console.table(s);
}

main().then(() => sql.end()).catch(async (e) => {
  console.error("[X]", e);
  await sql.end();
  process.exit(1);
});
