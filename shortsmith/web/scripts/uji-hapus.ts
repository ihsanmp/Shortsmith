/**
 * Buktikan penghapusan benar-benar melenyapkan objek dari B2 — termasuk versi
 * lamanya — dan tidak menyentuh objek lain yang key-nya berawalan sama.
 *
 * Dijalankan terhadap objek uji yang dibuat sendiri, lalu dibersihkan. Tidak
 * pernah menyentuh berkas project yang sesungguhnya.
 */
import { ListObjectVersionsCommand, PutObjectCommand } from "@aws-sdk/client-s3";
import { config } from "dotenv";

config({ path: [".env.vercel.local", ".env.local"] });

async function main() {
  const { s3, BUCKET, hapusObjek } = await import("../lib/storage");

  const dasar = `uji-hapus/${Date.now()}`;
  const target = `${dasar}/berkas.txt`;
  const tetangga = `${dasar}/berkas.txt.lain`; // key BERAWALAN sama

  async function tulis(key: string, isi: string) {
    await s3.send(new PutObjectCommand({ Bucket: BUCKET, Key: key, Body: isi }));
  }
  // Keberadaan diperiksa lewat ListObjectVersions, BUKAN HeadObject.
  //
  // HeadObject termasuk transaksi Class B — cap yang justru sedang tertutup di
  // akun ini. Memakainya membuat setiap objek terlihat "tidak ada", dan uji ini
  // sempat melaporkan GAGAL padahal penghapusannya benar.
  async function ada(key: string) {
    const d = await s3.send(
      new ListObjectVersionsCommand({ Bucket: BUCKET, Prefix: key }),
    );
    return (d.Versions ?? []).some((v) => v.Key === key);
  }

  console.log("menyiapkan objek uji...");
  await tulis(target, "versi-1");
  await tulis(target, "versi-2"); // versi kedua: inilah yang biasanya tertinggal
  await tulis(tetangga, "jangan-tersentuh");

  console.log(`  ${target}      : ${await ada(target)}`);
  console.log(`  ${tetangga} : ${await ada(tetangga)}`);

  const n = await hapusObjek([target]);
  console.log(`\nhapusObjek() menghapus ${n} versi`);

  const sisaTarget = await ada(target);
  const sisaTetangga = await ada(tetangga);
  console.log(`  target masih ada   : ${sisaTarget}   (harus false)`);
  console.log(`  tetangga masih ada : ${sisaTetangga}   (harus true)`);

  const lolos = n >= 2 && !sisaTarget && sisaTetangga;
  console.log(`\n${lolos ? "[ok] LOLOS" : "[X] GAGAL"} — dua versi terhapus, tetangga aman`);

  await hapusObjek([tetangga]);
  if (!lolos) process.exitCode = 1;
}

main().catch((e) => {
  console.error("[X] gagal:", (e as Error).message);
  process.exitCode = 1;
});
