"use client";

import { useEffect, useState } from "react";

/**
 * Teks unggahan untuk satu klip, siap disalin.
 *
 * ## Kenapa bisa disunting
 *
 * Yang ditulis agent adalah draf yang bagus, bukan jawaban akhir. Menguncinya
 * berarti pengguna yang ingin mengubah satu kata harus menyalin ke tempat lain,
 * menyuntingnya di sana, lalu kembali — untuk satu kata.
 *
 * Suntingannya sengaja TIDAK disimpan ke server. Ini kotak kerja sesaat sebelum
 * menempel ke aplikasi lain, dan menyimpannya menuntut jawaban untuk pertanyaan
 * yang belum ditanyakan siapa pun: apa yang terjadi kalau klipnya dirender ulang.
 *
 * ## Kenapa tombol salinnya berubah, bukan memunculkan pesan
 *
 * Menyalin berhasil atau tidak sama sekali, dan hasilnya langsung terlihat di
 * tempat yang sedang dilihat mata. Notifikasi terpisah menarik perhatian ke
 * sudut layar untuk mengabarkan sesuatu yang sudah jelas.
 */
export function Keterangan({ teks }: { teks: string }) {
  const [isi, setIsi] = useState(teks);
  const [disalin, setDisalin] = useState(false);

  // Klip lain bisa menggantikan komponen ini tanpa melepasnya dari DOM kalau
  // React memakai ulang simpulnya. Tanpa ini, keterangan klip lama bertahan.
  useEffect(() => setIsi(teks), [teks]);

  useEffect(() => {
    if (!disalin) return;
    const t = setTimeout(() => setDisalin(false), 1800);
    return () => clearTimeout(t);
  }, [disalin]);

  async function salin() {
    try {
      await navigator.clipboard.writeText(isi);
      setDisalin(true);
    } catch {
      // Clipboard ditolak (izin, atau halaman bukan konteks aman). Teksnya
      // tetap ada di kotak dan tetap bisa disalin manual, jadi tidak ada yang
      // perlu dilaporkan sebagai kegagalan.
      setDisalin(false);
    }
  }

  return (
    <div className="keterangan">
      <div className="keterangan-atas">
        <span className="keterangan-label">Keterangan unggahan</span>
        <button type="button" className="btn ghost keterangan-salin" onClick={salin}>
          {disalin ? "Tersalin" : "Salin"}
        </button>
      </div>
      <textarea
        className="keterangan-teks"
        value={isi}
        rows={Math.min(10, isi.split("\n").length + 2)}
        onChange={(e) => setIsi(e.target.value)}
        aria-label="Keterangan unggahan"
      />
    </div>
  );
}
