/**
 * Sesi login berbasis cookie bertanda tangan.
 *
 * Sengaja memakai Web Crypto (`crypto.subtle`), bukan `node:crypto`: middleware
 * Next.js berjalan di Edge runtime, dan `node:crypto` tidak tersedia di sana.
 * Web Crypto ada di keduanya, jadi satu helper ini dipakai baik oleh middleware
 * maupun oleh route handler.
 *
 * Isi cookie: `<muatan>.<hmac-sha256(muatan)>`, dengan muatan
 * `<expiry-ms>|<peran>|<user-id>`. Tidak ada data sesi yang disimpan server —
 * tanda tangannya sendiri yang membuktikan cookie itu terbit dari kita dan
 * belum kedaluwarsa.
 *
 * ## Kenapa peran ikut ditandatangani, bukan disimpan terpisah
 *
 * Peran menentukan apa yang boleh diubah. Kalau ia hidup di cookie lain atau di
 * localStorage, siapa pun bisa menaikkan dirinya sendiri dari `tamu` ke
 * `pemilik` dengan mengetik satu baris di konsol. Di dalam muatan yang
 * ditandatangani, mengubahnya berarti merusak tanda tangannya.
 *
 * ## Kenapa cookie lama tetap sah
 *
 * Muatan dipisahkan dari tanda tangan di titik TERAKHIR, dan yang
 * ditandatangani adalah seluruh muatan apa adanya. Cookie terbitan lama
 * bermuatan `<expiry-ms>` saja — ia tetap terverifikasi dengan aturan yang sama,
 * dan dibaca sebagai sesi pemilik tanpa akun. Tanpa itu, setiap orang yang
 * sedang login akan terlempar keluar saat versi ini naik.
 */

export const COOKIE_NAME = "shortsmith_session";
export const SESSION_TTL_MS = 1000 * 60 * 60 * 24 * 14; // 14 hari

const encoder = new TextEncoder();

async function hmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
}

async function sign(secret: string, payload: string): Promise<string> {
  const key = await hmacKey(secret);
  const buf = await crypto.subtle.sign("HMAC", key, encoder.encode(payload));
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Perbandingan konstan-waktu untuk string.
 *
 * `a === b` keluar lebih cepat saat karakter pertama berbeda, yang secara teori
 * membocorkan informasi lewat waktu eksekusi. Akumulasi XOR selalu memeriksa
 * seluruh panjang string.
 */
function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let beda = 0;
  for (let i = 0; i < a.length; i++) {
    beda |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return beda === 0;
}

/**
 * `pemilik` boleh mengubah apa pun. `tamu` hanya boleh membaca — pembatasannya
 * ditegakkan di middleware, bukan di antarmuka, karena tombol yang disembunyikan
 * tidak menghalangi siapa pun memanggil API-nya langsung.
 */
export type Peran = "pemilik" | "tamu";

export type IsiSesi = {
  kedaluwarsa: number;
  peran: Peran;
  /** Kosong untuk sesi kata sandi bersama dan sesi tamu. */
  userId: string;
  /**
   * Baris di tabel `sessions` yang mewakili perangkat ini. Kosong untuk sesi
   * tanpa akun. Dipakai halaman "Kelola akun" untuk menandai mana yang sedang
   * dipakai — bukan untuk memutuskan sesinya sah.
   */
  sesiId: string;
};

export async function createSessionToken(
  secret: string,
  opsi: { peran?: Peran; userId?: string; sesiId?: string } = {},
): Promise<string> {
  const exp = Date.now() + SESSION_TTL_MS;
  const muatan = `${exp}|${opsi.peran ?? "pemilik"}|${opsi.userId ?? ""}|${opsi.sesiId ?? ""}`;
  return `${muatan}.${await sign(secret, muatan)}`;
}

/**
 * Baca isi token TANPA memverifikasi tanda tangannya.
 *
 * Hanya boleh dipakai di belakang middleware, yang sudah menolak token tak sah
 * sebelum permintaan sampai ke sana. Untuk keputusan izin, pakai
 * `verifySessionToken` — fungsi ini percaya begitu saja pada isinya.
 */
export function bacaIsiSesi(token: string | undefined): IsiSesi | null {
  if (!token) return null;

  const pisah = token.lastIndexOf(".");
  if (pisah <= 0) return null;

  const [expStr, peranStr = "pemilik", userId = "", sesiId = ""] = token
    .slice(0, pisah)
    .split("|");
  const kedaluwarsa = Number(expStr);
  if (!Number.isFinite(kedaluwarsa)) return null;

  return {
    kedaluwarsa,
    peran: peranStr === "tamu" ? "tamu" : "pemilik",
    userId,
    sesiId,
  };
}

/**
 * Mengembalikan isi sesi kalau tokennya sah dan belum kedaluwarsa, `null` kalau
 * tidak. Mengembalikan isinya, bukan boolean, supaya pemanggil tidak tergoda
 * membaca peran dari sumber lain yang tidak ikut ditandatangani.
 */
export async function verifySessionToken(
  secret: string,
  token: string | undefined,
): Promise<IsiSesi | null> {
  if (!token) return null;

  const pisah = token.lastIndexOf(".");
  if (pisah <= 0) return null;

  const muatan = token.slice(0, pisah);
  const sig = token.slice(pisah + 1);

  if (!safeEqual(sig, await sign(secret, muatan))) return null;

  // Tanda tangan diperiksa LEBIH DULU, baru kedaluwarsanya. Urutan sebaliknya
  // memberi tahu penyerang kapan tebakan muatannya berbentuk benar.
  const isi = bacaIsiSesi(token);
  if (!isi || isi.kedaluwarsa < Date.now()) return null;

  return isi;
}

/** Cek password login, juga konstan-waktu. */
export function passwordCocok(diberikan: string, benar: string): boolean {
  return safeEqual(diberikan, benar);
}
