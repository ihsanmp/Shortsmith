/**
 * Cari sintaks JavaScript yang BOCOR jadi teks di dalam JSX.
 *
 *     npx tsx scripts/cek-jsx.ts
 *
 * ## Kenapa ini perlu ada terpisah dari tsc
 *
 * `!konsepDimuat ? (` yang kehilangan kurung kurawal pembukanya bukan galat
 * TypeScript — ia teks biasa di dalam JSX, dan sah menurut tipe. Yang terjadi
 * adalah kalimat itu dicetak apa adanya ke halaman.
 *
 * Terjadi sungguhan: satu penyuntingan membuang `{sumber === "pustaka" ? (` dan
 * meninggalkan rantai ternary di bawahnya, sehingga form menampilkan
 *
 *     !konsepDimuat ? (
 *     ) : konsepGagal ? (
 *     ) : concepts.length === 0 ? (
 *
 * sebagai teks kepada pengguna. `tsc --noEmit` bersih, `next build` lolos, dan
 * cacatnya baru ketahuan dari tangkapan layar.
 *
 * ## Kenapa memakai parser, bukan pola baris
 *
 * Percobaan pertama mencocokkan pola per baris, dan ia menandai `) : (` yang
 * SAH — lanjutan ternary yang memang dibuka dengan `{`. Dua belas temuan,
 * seluruhnya palsu. Yang membedakan sah dari bocor bukan bentuk barisnya
 * melainkan apakah ia berada di dalam ekspresi atau di posisi teks, dan itu
 * hanya bisa dijawab dengan mengurai berkasnya.
 *
 * Jadi yang diperiksa di sini adalah simpul JsxText — teks yang benar-benar
 * akan tampil — dan ditolak kalau ia memuat tanda yang tidak pernah muncul di
 * kalimat untuk manusia.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import ts from "typescript";

const AKAR = ["app", "components"];

// Tanda yang tidak pernah ada di kalimat yang ditujukan untuk dibaca orang.
//
// `?` dan `:` sendirian TIDAK masuk daftar: keduanya wajar di kalimat Indonesia
// ("Topik apa saja yang mau dibuat?"). Yang dicari pasangannya dengan kurung
// dan operator, yang hanya muncul kalau kodenya bocor.
const MENCURIGAKAN: [RegExp, string][] = [
  [/\?\s*\($/m, "ternary yang dibuka tanpa kurawal"],
  [/\)\s*:\s*\(/, "cabang ternary di posisi teks"],
  [/=>/, "panah fungsi"],
  [/===|!==/, "pembanding ketat"],
  [/\.\w+\(\)/, "pemanggilan metode"],
];

function berkas(dir: string): string[] {
  const keluar: string[] = [];
  for (const nama of readdirSync(dir)) {
    const p = join(dir, nama);
    if (statSync(p).isDirectory()) keluar.push(...berkas(p));
    else if (p.endsWith(".tsx")) keluar.push(p);
  }
  return keluar;
}

let temuan = 0;
let diperiksa = 0;

for (const akar of AKAR) {
  for (const p of berkas(akar)) {
    diperiksa++;
    const isi = readFileSync(p, "utf-8");
    const sf = ts.createSourceFile(p, isi, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

    const kunjungi = (n: ts.Node): void => {
      if (ts.isJsxText(n)) {
        const teks = n.text.trim();
        if (teks) {
          for (const [pola, sebab] of MENCURIGAKAN) {
            if (pola.test(teks)) {
              const { line } = sf.getLineAndCharacterOfPosition(n.getStart());
              const cuplik = teks.split("\n")[0].slice(0, 70);
              console.log(`  ${p}:${line + 1}  ${sebab}\n      ${cuplik}`);
              temuan++;
              break;
            }
          }
        }
      }
      ts.forEachChild(n, kunjungi);
    };
    kunjungi(sf);
  }
}

console.log(`\n${diperiksa} berkas .tsx diperiksa`);
if (temuan) {
  console.error(`[X] ${temuan} sintaks bocor jadi teks JSX`);
  process.exitCode = 1;
} else {
  console.log("[ok] tidak ada sintaks yang bocor jadi teks JSX");
}
