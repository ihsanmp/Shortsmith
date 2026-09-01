/**
 * Keadaan antrean job: apa yang pending, apa yang tersangkut processing.
 *
 *     npx tsx scripts/cek-antrean.ts
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.local", ".env.vercel.local"] });
const url = process.env.DATABASE_URL?.trim();
if (!url) { console.error("[X] DATABASE_URL tidak ada"); process.exit(1); }
const sql = postgres(url, { max: 1, prepare: false, connect_timeout: 15 });

async function main() {
  try {
    const rows = await sql`
      SELECT id, tipe, status, retry_count, lepas_count, concept_id, project_id,
             tahap, heartbeat_at,
             round(extract(epoch from (now() - coalesce(heartbeat_at, created_at)))) AS diam_detik
        FROM jobs
       WHERE status IN ('pending', 'processing')
       ORDER BY created_at
    `;
    if (!rows.length) { console.log("antrean kosong"); return; }
    for (const r of rows) {
      console.log(`${r.tipe.padEnd(18)} ${r.status.padEnd(11)} retry=${r.retry_count} lepas=${r.lepas_count}`);
      console.log(`  id         ${r.id}`);
      console.log(`  concept_id ${r.concept_id ?? "(null)"}`);
      console.log(`  project_id ${r.project_id ?? "(null)"}`);
      console.log(`  tahap      ${r.tahap || "(kosong)"}   diam ${r.diam_detik}s\n`);
    }
  } finally {
    await sql.end();
  }
}

main();
