/** Tampilkan daftar folder bahan yang dilaporkan agent. */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.vercel.local", ".env.local"] });
const sql = postgres(process.env.DATABASE_URL!.trim(), {
  max: 1,
  prepare: false,
  connect_timeout: 15,
});

async function main() {
  const [row] = await sql<{ data: any; updated_at: Date }[]>`
    SELECT data, updated_at FROM agent_info WHERE kunci = 'folder_bahan'
  `;
  if (!row) {
    console.log("belum ada laporan dari agent");
    return;
  }
  console.log(`root     : ${row.data.root}`);
  console.log(`dilapor  : ${row.updated_at.toISOString().slice(0, 19).replace("T", " ")}`);
  console.log("folder   :");
  for (const f of row.data.folders) {
    console.log(`  ${(f.path || "(folder utama)").padEnd(20)} ${f.jumlahVideo} video`);
  }
}

main()
  .catch((e) => {
    console.error("[X]", (e as Error).message);
    process.exitCode = 1;
  })
  .finally(() => sql.end());
