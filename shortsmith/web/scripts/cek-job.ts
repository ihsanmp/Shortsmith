/**
 * Keadaan satu job, untuk memeriksa cepat tanpa membuka dashboard database.
 *
 *     npx tsx scripts/cek-job.ts <id>
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.local", ".env.vercel.local"] });
const url = process.env.DATABASE_URL?.trim();
if (!url) { console.error("[X] DATABASE_URL tidak ada"); process.exit(1); }
const sql = postgres(url, { max: 1, prepare: false, connect_timeout: 15 });

async function main() {
  try {
    const id = process.argv[2];
    const rows = await sql`
      SELECT id, status, retry_count, progress, tahap,
             jsonb_array_length(coalesce(topik_usul, '[]'::jsonb)) AS usul,
             CASE WHEN topik_pilih IS NULL THEN -1
                  ELSE jsonb_array_length(topik_pilih) END AS pilih,
             left(coalesce(error_message, ''), 80) AS galat
        FROM jobs
       ${id ? sql`WHERE id = ${id}` : sql`ORDER BY created_at DESC LIMIT 3`}
    `;
    for (const r of rows) console.log(r);
    console.log("\n(pilih = -1 berarti belum dijawab)");
  } finally {
    await sql.end();
  }
}

main();
