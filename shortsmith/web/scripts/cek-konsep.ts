/**
 * Tampilkan isi concept profile yang tersimpan.
 *
 * Yang dilihat bukan "apakah barisnya ada", melainkan APA yang terukur di
 * dalamnya — karena konsep yang tersimpan setengah jadi terlihat sama saja
 * dengan yang lengkap sampai hasil rendernya keluar salah.
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.vercel.local", ".env.local"] });

const url = process.env.DATABASE_URL?.trim();
if (!url) {
  console.error("[X] DATABASE_URL tidak ada");
  process.exit(1);
}

const sql = postgres(url, { max: 1, prepare: false, connect_timeout: 15 });

type Baris = {
  nama: string;
  siap: boolean;
  is_default: boolean;
  profile_json: Record<string, any> | null;
  created_at: Date;
};

async function main() {
  const rows = await sql<Baris[]>`
    SELECT nama, siap, is_default, profile_json, created_at
    FROM concept_profiles ORDER BY created_at DESC LIMIT 8
  `;

  for (const r of rows) {
    const p = r.profile_json ?? {};
    const m = p.metrik ?? {};
    const angka = (k: string) => (m[k]?.mean != null ? String(m[k].mean) : "—");
    console.log(`\n=== ${r.nama} ${r.siap ? "(siap)" : "(BELUM SIAP)"}${r.is_default ? " [default]" : ""}`);
    console.log(`    dibuat        : ${r.created_at.toISOString().slice(0, 16).replace("T", " ")}`);
    console.log(`    format        : ${p.format ?? "— (auto)"}`);
    console.log(`    rasio         : ${p.aspect_ratio ?? "—"}`);
    console.log(`    porsi pembicara: ${p.porsi_pembicara != null ? `${Math.round(p.porsi_pembicara * 100)}%` : "—"}`);
    console.log(`    durasi target : ${angka("durasi_total")} detik`);
    console.log(`    shot rata-rata: ${angka("avg_shot_length")} detik`);
    console.log(`    penggal suara : ${angka("penggal_suara")}   <- jumlah sambungan AUDIO`);
    console.log(`    jumlah shot   : ${angka("jumlah_cut")}   <- pergantian GAMBAR`);
    const c = p.caption;
    console.log(
      `    caption       : ${
        c ? `${c.ada === false ? "mati" : `${c.gaya ?? "?"} @ ${c.posisi ?? "?"}`}` : "— (belum dibaca)"
      }`,
    );
  }
}

main()
  .catch((e) => {
    console.error("[X] gagal:", (e as Error).message);
    process.exitCode = 1;
  })
  .finally(() => sql.end());
