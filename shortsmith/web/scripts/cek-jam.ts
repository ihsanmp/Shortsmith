/** Job yang tersentuh pada rentang jam tertentu. */
import { config } from "dotenv";
import postgres from "postgres";
config({ path: [".env.local", ".env.vercel.local"] });
const sql = postgres(process.env.DATABASE_URL!.trim(), { max: 1, prepare: false });
async function main() {
  try {
    const rows = await sql`
      SELECT id, tipe, status, retry_count, lepas_count, concept_id, project_id,
             to_char(created_at,  'MM-DD HH24:MI:SS') AS dibuat,
             to_char(started_at,  'MM-DD HH24:MI:SS') AS mulai,
             to_char(finished_at, 'MM-DD HH24:MI:SS') AS selesai,
             left(coalesce(error_message,''), 60) AS galat
        FROM jobs
       ORDER BY greatest(coalesce(started_at, created_at), created_at) DESC
       LIMIT 8
    `;
    for (const r of rows) {
      console.log(`${r.tipe.padEnd(18)} ${r.status.padEnd(11)} dibuat ${r.dibuat}  mulai ${r.mulai ?? "-"}  selesai ${r.selesai ?? "-"}`);
      console.log(`  ${r.id}  concept=${r.concept_id ? "ada" : "null"} project=${r.project_id ? "ada" : "null"}  ${r.galat}`);
    }
  } finally { await sql.end(); }
}
main();
