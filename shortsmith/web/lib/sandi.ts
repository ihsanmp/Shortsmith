/**
 * Penyimpanan kata sandi akun.
 *
 * ## Kenapa PBKDF2, bukan bcrypt atau argon2
 *
 * Rute login berjalan di runtime Node, tapi helper ini dipakai bersama kode yang
 * juga harus hidup di Edge. PBKDF2 tersedia lewat Web Crypto di keduanya;
 * bcrypt dan argon2 adalah paket native yang tidak bisa dimuat di Edge sama
 * sekali. Argon2id memang lebih tahan terhadap serangan berbasis GPU, tapi
 * PBKDF2 dengan iterasi yang cukup tetap dianggap layak oleh OWASP — dan
 * satu implementasi yang jalan di mana-mana lebih baik daripada dua yang
 * berbeda di dua runtime.
 *
 * ## Kenapa 210.000 iterasi
 *
 * Angka yang direkomendasikan OWASP untuk PBKDF2-HMAC-SHA256. Di Vercel ia
 * memakan ~100ms per verifikasi — cukup lambat untuk membuat penebakan massal
 * mahal, cukup cepat untuk tidak terasa saat login.
 *
 * ## Kenapa garamnya per-pengguna dan disimpan bersama hash-nya
 *
 * Tanpa garam, dua orang dengan kata sandi sama menghasilkan hash sama, dan satu
 * tabel pelangi membuka keduanya sekaligus. Garam tidak rahasia — tugasnya
 * hanya membuat tiap hash unik — jadi menyimpannya di baris yang sama tidak
 * melemahkan apa pun.
 */

const ITERASI = 210_000;
const PANJANG_GARAM = 16;
const PANJANG_KUNCI = 32;

const enc = new TextEncoder();

function keB64(b: ArrayBuffer | Uint8Array): string {
  const bytes = b instanceof Uint8Array ? b : new Uint8Array(b);
  let s = "";
  for (const byte of bytes) s += String.fromCharCode(byte);
  return btoa(s);
}

function dariB64(s: string): Uint8Array {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function turunkan(
  sandi: string,
  garam: Uint8Array,
  iterasi: number,
): Promise<Uint8Array> {
  const kunci = await crypto.subtle.importKey("raw", enc.encode(sandi), "PBKDF2", false, [
    "deriveBits",
  ]);
  const bit = await crypto.subtle.deriveBits(
    // BufferSource harus ArrayBuffer murni; Uint8Array dari .buffer bisa
    // membawa offset kalau ia irisan dari buffer lain.
    { name: "PBKDF2", salt: garam as unknown as BufferSource, iterations: iterasi, hash: "SHA-256" },
    kunci,
    PANJANG_KUNCI * 8,
  );
  return new Uint8Array(bit);
}

/** Bentuk tersimpan: `pbkdf2$<iterasi>$<garam-b64>$<hash-b64>`. */
export async function hashSandi(sandi: string): Promise<string> {
  const garam = crypto.getRandomValues(new Uint8Array(PANJANG_GARAM));
  const hash = await turunkan(sandi, garam, ITERASI);
  return `pbkdf2$${ITERASI}$${keB64(garam)}$${keB64(hash)}`;
}

/**
 * Perbandingan konstan-waktu atas byte hasil turunan.
 *
 * Keluar lebih awal saat byte pertama berbeda akan membocorkan informasi lewat
 * waktu eksekusi. Akumulasi XOR selalu memeriksa seluruh panjangnya.
 */
function samaKonstan(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let beda = 0;
  for (let i = 0; i < a.length; i++) beda |= a[i] ^ b[i];
  return beda === 0;
}

export async function sandiCocok(sandi: string, tersimpan: string): Promise<boolean> {
  const bagian = tersimpan.split("$");
  if (bagian.length !== 4 || bagian[0] !== "pbkdf2") return false;

  const iterasi = Number(bagian[1]);
  if (!Number.isFinite(iterasi) || iterasi < 1000) return false;

  try {
    const garam = dariB64(bagian[2]);
    const diharapkan = dariB64(bagian[3]);
    const dihitung = await turunkan(sandi, garam, iterasi);
    return samaKonstan(dihitung, diharapkan);
  } catch {
    // Hash yang rusak bentuknya diperlakukan sebagai tidak cocok, bukan error.
    // Satu baris rusak di database tidak boleh menjatuhkan seluruh rute login.
    return false;
  }
}
