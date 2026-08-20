import { config } from "dotenv";
import postgres from "postgres";

config({ path: ".env.local" });

async function main() {
  const sql = postgres(process.env.DATABASE_URL!, { max: 1, prepare: false });

  const tabel = await sql`
    SELECT t.table_name,
           (SELECT count(*) FROM information_schema.columns c
             WHERE c.table_name = t.table_name AND c.table_schema='public') AS kolom
      FROM information_schema.tables t
     WHERE t.table_schema='public' AND t.table_type='BASE TABLE'
     ORDER BY t.table_name`;

  const enums = await sql`
    SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder) AS nilai
      FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid
     GROUP BY t.typname ORDER BY t.typname`;

  const idx = await sql`
    SELECT indexname FROM pg_indexes
     WHERE schemaname='public' AND indexname LIKE '%_idx' ORDER BY indexname`;

  console.log("TABEL:");
  for (const r of tabel) console.log(`  ${r.table_name}  (${r.kolom} kolom)`);
  console.log("\nENUM:");
  for (const r of enums) console.log(`  ${r.typname} = ${(r.nilai as string[]).join(", ")}`);
  console.log("\nINDEKS:");
  for (const r of idx) console.log(`  ${r.indexname}`);

  await sql.end();
}

main().catch((e) => { console.error(e.message); process.exit(1); });
