/**
 * Apa yang SEBENARNYA dikembalikan `db.execute` saat tidak ada job pending.
 *
 *     npx tsx scripts/cek-claim.ts
 *
 * Jalankan hanya saat antrean kosong — perintahnya memang mengambil job.
 */
import { config } from "dotenv";
config({ path: [".env.local", ".env.vercel.local"] });

async function main() {
  // Impor DINAMIS: db/index.ts membaca DATABASE_URL saat modulnya dimuat, dan
  // impor statis dijalankan sebelum config() sempat mengisinya.
  const { db } = await import("../db");
  const { claimNextJobSql } = await import("../lib/queue-sql");

  const rows = await db.execute(claimNextJobSql());
  console.log("typeof        :", typeof rows);
  console.log("Array.isArray :", Array.isArray(rows));
  console.log("length        :", (rows as unknown as { length?: number }).length);
  console.log("kunci         :", Object.keys(rows as object).slice(0, 12));
  const nol = (rows as unknown as unknown[])[0];
  console.log("rows[0]       :", nol === undefined ? "undefined" : JSON.stringify(nol).slice(0, 300));
  console.log("rows[0] truthy:", Boolean(nol));
  process.exit(0);
}

main();
