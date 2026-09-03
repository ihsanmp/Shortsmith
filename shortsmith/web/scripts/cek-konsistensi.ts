/**
 * Keadaan data yang seharusnya tidak pernah terjadi.
 *
 * Bukan pemeriksa skema — Drizzle sudah menjaga bentuknya. Yang dicari di sini
 * adalah kombinasi yang sah menurut skema tapi tidak masuk akal menurut
 * aplikasinya: project yang selesai tanpa hasil, aset yang project-nya sudah
 * hilang, konsep yang tersangkut setengah jadi.
 *
 * Bentuk kegagalan seperti itu tidak melempar galat di mana pun. Ia cuma
 * membuat satu halaman terlihat aneh, dan baru ketemu kalau ada yang menghitung.
 *
 *     npx tsx scripts/cek-konsistensi.ts
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

async function main() {
  try {
    const job = await sql`SELECT status, count(*)::int AS n FROM jobs GROUP BY status ORDER BY n DESC`;
    console.log("job per status     :", job.map((r) => `${r.status}=${r.n}`).join("  ") || "(kosong)");

    const proj = await sql`SELECT status, count(*)::int AS n FROM projects GROUP BY status ORDER BY n DESC`;
    console.log("project per status :", proj.map((r) => `${r.status}=${r.n}`).join("  ") || "(kosong)");

    // Project selesai tanpa satu pun klip: halaman project-nya menampilkan
    // "Hasil" yang kosong, dan tidak ada apa pun yang menjelaskan kenapa.
    const [tanpaHasil] = await sql`
      SELECT count(*)::int AS n FROM projects p
      WHERE p.status = 'done'
        AND NOT EXISTS (SELECT 1 FROM assets a WHERE a.project_id = p.id AND a.jenis = 'output')`;

    // Aset yang project-nya sudah dihapus: byte di storage yang tidak akan
    // pernah dibuka siapa pun, dan tetap dihitung kuota.
    //
    // `project_id IS NOT NULL` bukan kehati-hatian berlebih. Video contoh
    // konsep memang menyimpan NULL di situ — ia milik konsep, bukan project —
    // dan tanpa syarat ini keenamnya terhitung yatim. Pemeriksa yang menuduh
    // keadaan sehat lebih buruk daripada tidak ada pemeriksa: ia mengirim orang
    // memburu sesuatu yang tidak rusak.
    const [asetYatim] = await sql`
      SELECT count(*)::int AS n FROM assets a
      WHERE a.project_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM projects p WHERE p.id = a.project_id)`;

    // Konsep yang ekstraksinya tidak pernah selesai: ia muncul di daftar
    // sebagai "menganalisis" selamanya, dan tidak bisa dipakai.
    const [konsepGantung] = await sql`
      SELECT count(*)::int AS n FROM concept_profiles WHERE siap = false`;

    const [klip] = await sql`SELECT count(*)::int AS n FROM assets WHERE jenis = 'output'`;
    const [berketerangan] = await sql`
      SELECT count(*)::int AS n FROM assets WHERE jenis = 'output' AND keterangan IS NOT NULL`;
    const [berarahan] = await sql`SELECT count(*)::int AS n FROM projects WHERE arahan IS NOT NULL`;

    console.log("");
    console.log(`project selesai tanpa hasil : ${tanpaHasil.n}`);
    console.log(`aset tanpa project          : ${asetYatim.n}`);
    console.log(`konsep belum siap           : ${konsepGantung.n}`);
    console.log(`klip hasil / berketerangan  : ${klip.n} / ${berketerangan.n}`);
    console.log(`project dengan arahan       : ${berarahan.n}`);

    // Project "processing" yang tidak punya job aktif: status yang tertinggal,
    // dan halaman prosesnya akan menjajak tanpa akhir.
    const [timpang] = await sql`
      SELECT count(*)::int AS n FROM projects p
       WHERE p.status = 'processing'
         AND NOT EXISTS (
           SELECT 1 FROM jobs j
            WHERE j.project_id = p.id AND j.status IN ('pending', 'processing'))`;
    console.log(`project 'processing' tanpa job : ${timpang.n}`);

    const buruk = tanpaHasil.n + asetYatim.n + timpang.n;
    console.log("");
    console.log(buruk === 0 ? "[ok] tidak ada keadaan yang menggantung" : `[!] ${buruk} baris perlu dilihat`);
  } finally {
    await sql.end();
  }
}

main();
