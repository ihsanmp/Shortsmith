/**
 * Diagnostik: kunci apa saja yang benar-benar ada di .env.vercel.local.
 *
 * Sengaja HANYA memeriksa file hasil `vercel env pull`, tidak menyentuh
 * .env.local sama sekali. Sudah terbukti lewat uji terpisah bahwa dotemv
 * memenangkan file pertama, jadi kalau sebuah kunci ada di file ini, ia pasti
 * yang terpakai — memeriksa file kedua tidak akan mengubah kesimpulan.
 *
 * Hanya mencetak NAMA kunci dan panjang nilainya. Nilai aslinya tidak pernah
 * ditampilkan; panjang saja sudah cukup untuk membedakan "tidak ada" dari
 * "ada tapi kosong", dan itulah dua kemungkinan yang perlu dipisahkan.
 */
import { existsSync, readFileSync } from "node:fs";

const FILE = ".env.vercel.local";
const DICARI = [
  "S3_BUCKET",
  "S3_ENDPOINT",
  "S3_REGION",
  "S3_ACCESS_KEY_ID",
  "S3_SECRET_ACCESS_KEY",
  "S3_FORCE_PATH_STYLE",
];

if (!existsSync(FILE)) {
  console.error(`[X] ${FILE} tidak ada. Jalankan dulu:`);
  console.error("    vercel env pull .env.vercel.local --environment=production");
  process.exit(1);
}

const ada = new Map<string, number>();
for (const baris of readFileSync(FILE, "utf8").split(/\r?\n/)) {
  const t = baris.trim();
  if (!t || t.startsWith("#")) continue;
  const eq = t.indexOf("=");
  if (eq < 1) continue;
  const nama = t.slice(0, eq).replace(/^export\s+/, "").trim();
  const nilai = t.slice(eq + 1).trim().replace(/^["']|["']$/g, "");
  ada.set(nama, nilai.length);
}

console.log(`${FILE}: ${ada.size} kunci total\n`);
for (const nama of DICARI) {
  const panjang = ada.get(nama);
  console.log(
    `  ${nama.padEnd(22)} ${panjang === undefined ? "TIDAK ADA" : `ada (${panjang} karakter)`}`,
  );
}

const lain = [...ada.keys()].filter((k) => !DICARI.includes(k)).sort();
if (lain.length) {
  console.log(`\nkunci lain di file ini: ${lain.join(", ")}`);
}
