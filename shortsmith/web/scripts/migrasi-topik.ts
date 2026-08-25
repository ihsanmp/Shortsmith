/**
 * Tambah kolom pilihan topik ke tabel `jobs`.
 *
 *     npx tsx scripts/migrasi-topik.ts
 *
 * Saat kolom topik dikosongkan pengguna, agent membaca dulu topik apa saja yang
 * ada di rekaman, lalu MENUNGGU pengguna mencentang yang mau dibuat.
 *
 * ## Kenapa tanpa status baru
 *
 * Menambah nilai ke enum `job_status` akan menyentuh semua yang membaca status:
 * penghitung antrean, pembebas job terlantar, dan halaman project. Padahal
 * selama menunggu, job itu memang masih `processing` dalam arti yang paling
 * penting: agent-nya hidup dan terus berdenyut, jadi pembebas job terlantar
 * BENAR untuk tidak merebutnya.
 *
 * Yang dibutuhkan cuma dua kotak: apa yang diusulkan agent, dan apa yang
 * dicentang pengguna. `topik_pilih` yang masih NULL berarti belum dijawab.
 *
 * Ditulis sebagai skrip mengikuti migrasi lain di folder ini — `drizzle-kit
 * push` jatuh oleh bug internalnya di database ini.
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.local", ".env.vercel.local"] });
const url = process.env.DATABASE_URL?.trim();
if (!url) {
  console.error("[X] DATABASE_URL tidak ditemukan");
  process.exit(1);
}
const sql = postgres(url, { max: 1, prepare: false });

async function main() {
  try {
    await sql`ALTER TABLE jobs ADD COLUMN IF NOT EXISTS topik_usul jsonb`;
    await sql`ALTER TABLE jobs ADD COLUMN IF NOT EXISTS topik_pilih jsonb`;

    // Dibaca ULANG dari server, bukan dipercaya dari perintah yang tidak
    // melempar. ALTER yang sukses tanpa efek (mis. karena menyentuh database
    // yang salah) terlihat persis sama dengan yang berhasil.
    const kolom = await sql<{ column_name: string; data_type: string }[]>`
      SELECT column_name, data_type
        FROM information_schema.columns
       WHERE table_name = 'jobs' AND column_name IN ('topik_usul', 'topik_pilih')
       ORDER BY column_name
    `;
    if (kolom.length !== 2) {
      console.error(`[X] hanya ${kolom.length} dari 2 kolom yang ada`);
      process.exitCode = 1;
      return;
    }
    for (const k of kolom) console.log(`[ok] jobs.${k.column_name} (${k.data_type})`);
  } finally {
    await sql.end();
  }
}

main();
