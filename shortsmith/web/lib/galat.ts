"use client";

/**
 * Membaca pesan error dari sebuah Response yang gagal, tanpa mengandaikan
 * badannya JSON.
 *
 * ## Masalah yang diperbaikinya
 *
 * Pola yang tersebar di seluruh aplikasi ini dulu berbunyi:
 *
 *     if (!res.ok) throw new Error((await res.json()).error ?? "Gagal ...");
 *
 * Itu benar selama yang menjawab adalah route handler kita sendiri, yang memang
 * selalu mengembalikan JSON. Tapi tidak semua kegagalan sampai ke sana. Kalau
 * fungsi serverless-nya jatuh, kehabisan waktu, atau permintaannya berhenti di
 * lapisan platform, yang kembali adalah halaman error berupa teks biasa —
 * "An error occurred with this deployment" dan sejenisnya.
 *
 * `res.json()` pada badan seperti itu melempar SyntaxError, dan pesan yang
 * akhirnya dilihat pengguna berbunyi:
 *
 *     Unexpected token 'A', "An error o"... is not valid JSON
 *
 * Pesan itu bukan cuma tidak membantu — ia MENGGANTI pesan yang sebenarnya, dan
 * membuat kegagalan server terlihat seperti kesalahan penguraian di browser.
 * Sesuatu yang membuang bukti tentang dirinya sendiri adalah yang paling mahal
 * untuk dilacak nanti.
 *
 * ## Kenapa `text()` lalu `JSON.parse`, bukan `json()` dengan try/catch
 *
 * Badan sebuah Response hanya bisa dibaca SEKALI. Kalau `res.json()` gagal,
 * badannya sudah terpakai dan teks aslinya hilang untuk selamanya — jadi
 * penanganan galatnya pun tidak bisa menyebut apa yang sebenarnya diterima.
 * Membaca teks lebih dulu menyisakan keduanya.
 */

/** Berapa karakter badan non-JSON yang ikut ditampilkan. */
const CUPLIK = 140;

export async function galatDari(res: Response, bawaan: string): Promise<string> {
  let teks = "";
  try {
    teks = await res.text();
  } catch {
    // Badan tidak terbaca sama sekali (koneksi putus di tengah). Statusnya
    // masih memberi tahu sesuatu, jadi itu yang dipakai.
    return `${bawaan} (HTTP ${res.status})`;
  }

  try {
    const d = JSON.parse(teks) as { error?: string; detail?: string };
    const pesan = [d.error, d.detail].filter(Boolean).join(" — ");
    if (pesan) return pesan;
  } catch {
    // Bukan JSON. Jatuh ke penanganan di bawah.
  }

  const bersih = teks.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
  if (!bersih) return `${bawaan} (HTTP ${res.status})`;

  // Status ikut disebut walau ada teksnya. Halaman error platform sering
  // berbunyi sama untuk sebab yang berbeda, dan kodenya yang membedakan
  // kehabisan waktu dari fungsi yang jatuh.
  const potong =
    bersih.length > CUPLIK ? `${bersih.slice(0, CUPLIK)}...` : bersih;
  return `${bawaan} (HTTP ${res.status}): ${potong}`;
}
