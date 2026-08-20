/**
 * Uji cookie sesi: tanda tangan, kedaluwarsa, dan penolakan pemalsuan.
 *
 *   npx tsx test/session.test.ts
 */
import {
  bacaIsiSesi,
  createSessionToken,
  passwordCocok,
  verifySessionToken,
  SESSION_TTL_MS,
} from "../lib/session";

let lulus = 0;
let gagal = 0;

function cek(nama: string, kondisi: boolean, detail = "") {
  if (kondisi) {
    lulus++;
    console.log(`  ok    ${nama}`);
  } else {
    gagal++;
    console.log(`  GAGAL ${nama}  ${detail}`);
  }
}

async function main() {
  const secret = "rahasia-yang-cukup-panjang-untuk-hmac";
  const lain = "kunci-yang-berbeda-sama-sekali";

  console.log("\n1. token yang sah");
  const token = await createSessionToken(secret);
  cek("token diterima oleh secret yang sama", !!(await verifySessionToken(secret, token)));
  cek(
    "berbentuk <exp>|<peran>|<uid>|<sesi>.<hmac>",
    /^\d+\|pemilik\|\|\.[0-9a-f]{64}$/.test(token),
    token.slice(0, 40),
  );

  console.log("\n2. penolakan");
  cek("token kosong ditolak", !(await verifySessionToken(secret, undefined)));
  cek("string sembarang ditolak", !(await verifySessionToken(secret, "bukan-token")));
  cek(
    "token dari secret LAIN ditolak",
    !(await verifySessionToken(secret, await createSessionToken(lain))),
  );

  console.log("\n3. pemalsuan tanda tangan");
  const [exp, sig] = token.split(".");
  const rusak = `${exp}.${sig.slice(0, -1)}${sig.at(-1) === "a" ? "b" : "a"}`;
  cek("tanda tangan diubah satu karakter -> ditolak",
      !(await verifySessionToken(secret, rusak)));

  // Ini yang paling penting: memperpanjang masa berlaku tanpa tanda tangan baru.
  const diperpanjang = `${Date.now() + SESSION_TTL_MS * 10}|pemilik||.${sig}`;
  cek("expiry dipanjangkan tapi tanda tangan lama -> ditolak",
      !(await verifySessionToken(secret, diperpanjang)));

  console.log("\n4. kedaluwarsa");
  // Tanda tangan sah, tapi waktunya sudah lewat.
  const kadaluwarsa = await createSessionToken(secret);
  const sigValid = kadaluwarsa.slice(kadaluwarsa.lastIndexOf(".") + 1);
  cek(
    "token dengan expiry di masa lalu ditolak",
    !(await verifySessionToken(secret, `${Date.now() - 1000}|pemilik||.${sigValid}`)),
  );

  console.log("\n4b. peran dan identitas ikut ditandatangani");
  const tamu = await createSessionToken(secret, { peran: "tamu" });
  const isiTamu = await verifySessionToken(secret, tamu);
  cek("sesi tamu terbaca sebagai tamu", isiTamu?.peran === "tamu");

  // Yang paling penting dari seluruh berkas ini: tamu tidak boleh bisa menaikkan
  // dirinya sendiri jadi pemilik hanya dengan menyunting cookie-nya.
  const naikPangkat = tamu.replace("|tamu|", "|pemilik|");
  cek(
    "tamu diubah jadi pemilik -> ditolak",
    !(await verifySessionToken(secret, naikPangkat)),
  );

  const berakun = await createSessionToken(secret, { userId: "abc-123" });
  cek("userId terbawa", (await verifySessionToken(secret, berakun))?.userId === "abc-123");
  cek(
    "userId diubah -> ditolak",
    !(await verifySessionToken(secret, berakun.replace("abc-123", "abc-124"))),
  );

  console.log("\n4c. cookie terbitan lama tetap sah");
  // Bentuk lama: muatan hanya <exp>, tanpa peran maupun userId. Kalau ini
  // ditolak, semua yang sedang login terlempar keluar saat versi ini naik.
  const { createHmac } = await import("node:crypto");
  const expLama = String(Date.now() + SESSION_TTL_MS);
  const sigLama = createHmac("sha256", secret).update(expLama).digest("hex");
  const tokenLama = `${expLama}.${sigLama}`;
  const isiLama = await verifySessionToken(secret, tokenLama);
  cek("token bentuk lama diterima", !!isiLama);
  cek("token bentuk lama dibaca sebagai pemilik", isiLama?.peran === "pemilik");
  cek("token bentuk lama tidak punya userId", isiLama?.userId === "");

  console.log("\n4d. bacaIsiSesi");
  cek("sampah dikembalikan null", bacaIsiSesi("bukan-token") === null);
  cek("tanpa token dikembalikan null", bacaIsiSesi(undefined) === null);

  console.log("\n5. perbandingan password");
  cek("password benar cocok", passwordCocok("hunter2", "hunter2"));
  cek("password salah tidak cocok", !passwordCocok("hunter3", "hunter2"));
  cek("panjang berbeda tidak cocok", !passwordCocok("hunter", "hunter2"));
  cek("string kosong tidak cocok dengan yang terisi", !passwordCocok("", "hunter2"));

  console.log(`\n${lulus} lolos, ${gagal} gagal`);
  process.exit(gagal === 0 ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
