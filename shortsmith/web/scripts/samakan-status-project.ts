/**
 * Menyamakan status project dengan status job terakhirnya.
 *
 * Sebelum `finishJobSql` menulis keduanya dalam satu pernyataan, penyelesaian
 * job dilakukan dua langkah: UPDATE ke jobs, lalu UPDATE ke projects. Kalau
 * yang kedua tidak sampai, job selesai sementara project-nya tertinggal
 * berstatus "processing" — dan tidak ada yang pernah memperbaikinya, karena
 * tidak ada lagi job yang akan selesai untuk project itu.
 *
 * Akibatnya terlihat: project tampil "sedang diproses" di daftar selamanya, dan
 * halaman prosesnya menjajak tanpa akhir karena syarat berhentinya menuntut
 * KEDUA status keluar dari processing.
 *
 *     npx tsx scripts/samakan-status-project.ts          # lihat saja
 *     npx tsx scripts/samakan-status-project.ts --tulis  # perbaiki
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.local", ".env.vercel.local"] });
const url = process.env.DATABASE_URL?.trim();
if (!url) {
  console.error("[X] DATABASE_URL tidak ada");
  process.exit(1);
}
const sql = postgres(url, { max: 1, prepare: false, connect_timeout: 15 });
const tulis = process.argv.includes("--tulis");

async function main() {
  try {
    // Hanya project yang TIDAK punya satu pun job aktif. Selama masih ada job
    // pending atau processing, "processing" adalah status yang benar dan
    // menyentuhnya justru merusak.
    const timpang = await sql`
      SELECT p.id, p.judul, p.status AS status_project,
             (SELECT j.status FROM jobs j
               WHERE j.project_id = p.id
               ORDER BY j.created_at DESC LIMIT 1) AS status_job
        FROM projects p
       WHERE p.status = 'processing'
         AND NOT EXISTS (
           SELECT 1 FROM jobs j
            WHERE j.project_id = p.id AND j.status IN ('pending', 'processing'))
    `;

    if (!timpang.length) {
      console.log("[ok] tidak ada project yang statusnya tertinggal");
      return;
    }

    for (const r of timpang) {
      console.log(
        `  ${r.id}  ${String(r.judul).slice(0, 40)}  project=${r.status_project} job=${r.status_job ?? "(tidak ada job)"}`,
      );
    }

    if (!tulis) {
      console.log(`\n${timpang.length} project timpang. Jalankan lagi dengan --tulis untuk memperbaiki.`);
      return;
    }

    for (const r of timpang) {
      // Tanpa job sama sekali, "failed" adalah kesimpulan yang jujur: tidak ada
      // yang akan mengerjakannya, dan membiarkannya "processing" menjanjikan
      // sesuatu yang tidak akan datang.
      const baru = r.status_job ?? "failed";
      await sql`UPDATE projects SET status = ${baru}::job_status WHERE id = ${r.id}`;
      console.log(`  [ok] ${r.id} -> ${baru}`);
    }

    const [{ n }] = await sql`
      SELECT count(*)::int AS n FROM projects p
       WHERE p.status = 'processing'
         AND NOT EXISTS (
           SELECT 1 FROM jobs j
            WHERE j.project_id = p.id AND j.status IN ('pending', 'processing'))`;
    console.log(`\nsisa yang timpang setelah perbaikan: ${n}`);
  } finally {
    await sql.end();
  }
}

main();
