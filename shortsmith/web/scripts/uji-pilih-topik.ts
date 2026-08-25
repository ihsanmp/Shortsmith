/**
 * Taruh satu job SEMENTARA di keadaan "menunggu pilihan topik", supaya panelnya
 * bisa dilihat di peramban, lalu kembalikan persis seperti semula.
 *
 *     npx tsx scripts/uji-pilih-topik.ts pasang
 *     npx tsx scripts/uji-pilih-topik.ts lepas
 *
 * Keadaan aslinya disimpan ke berkas, bukan diingat di kepala: kalau skrip ini
 * mati di tengah, `lepas` tetap tahu harus mengembalikan ke apa. Job yang
 * tertinggal berstatus `processing` tanpa agent yang mengerjakannya akan
 * terlihat seperti render yang menggantung selamanya.
 */
import { readFileSync, writeFileSync, existsSync, unlinkSync } from "node:fs";

import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.local", ".env.vercel.local"] });
const url = process.env.DATABASE_URL?.trim();
if (!url) {
  console.error("[X] DATABASE_URL tidak ditemukan");
  process.exit(1);
}
const sql = postgres(url, { max: 1, prepare: false });
const SIMPAN = ".uji-topik.json";

const CONTOH = [
  "Kenapa IHSG bisa turun tajam padahal fundamental emitennya tidak berubah",
  "Cara membedakan koreksi sehat dari awal pasar beruang",
  "Peran rupiah yang melemah terhadap keputusan investor asing",
  "Aset digital sebagai pelindung nilai: yang benar dan yang mitos",
];

async function main() {
  try {
    if (process.argv[2] === "lepas") {
      if (!existsSync(SIMPAN)) {
        console.log("tidak ada yang perlu dikembalikan");
        return;
      }
      const asli = JSON.parse(readFileSync(SIMPAN, "utf-8"));
      await sql`
        UPDATE jobs
           SET status = ${asli.status}, progress = ${asli.progress},
               tahap = ${asli.tahap}, topik_usul = NULL, topik_pilih = NULL
         WHERE id = ${asli.id}
      `;
      unlinkSync(SIMPAN);
      console.log(`[ok] job ${asli.id} dikembalikan ke '${asli.status}'`);
      return;
    }

    const [job] = await sql<
      { id: string; project_id: string; status: string; progress: number; tahap: string }[]
    >`
      SELECT id, project_id, status, progress, tahap
        FROM jobs
       WHERE tipe = 'render' AND project_id IS NOT NULL
       ORDER BY created_at DESC
       LIMIT 1
    `;
    if (!job) {
      console.error("[X] tidak ada job render sama sekali");
      process.exitCode = 1;
      return;
    }

    writeFileSync(SIMPAN, JSON.stringify(job), "utf-8");
    await sql`
      UPDATE jobs
         SET status = 'processing', progress = 42,
             tahap = 'menunggu kamu memilih topik',
             topik_usul = ${sql.json(CONTOH)}, topik_pilih = NULL
       WHERE id = ${job.id}
    `;
    console.log(`[ok] job ${job.id} dipasang menunggu ${CONTOH.length} topik`);
    console.log(`     buka: /project/${job.project_id}/proses`);
    console.log(`     kembalikan dengan: npx tsx scripts/uji-pilih-topik.ts lepas`);
  } finally {
    await sql.end();
  }
}

main();
