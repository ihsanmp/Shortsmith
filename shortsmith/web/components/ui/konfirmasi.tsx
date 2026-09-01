"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/**
 * Dialog konfirmasi untuk tindakan yang tidak bisa dibatalkan.
 *
 * Menggantikan `confirm()` bawaan browser, yang tidak bisa ditata sama sekali
 * dan menampilkan nama domain di judulnya — terlihat seperti peringatan sistem,
 * bukan bagian dari aplikasi.
 *
 * Yang dijaga di sini bukan cuma tampilannya:
 *
 * - **Fokus dipindahkan ke tombol Batal**, bukan ke tombol merah. Dialog untuk
 *   tindakan permanen tidak boleh membuat Enter refleks berarti "ya".
 * - **Escape membatalkan**, dan klik di luar kartu juga. Keduanya jalan keluar
 *   yang dicari orang lebih dulu sebelum mencari tombolnya.
 * - **Fokus dikembalikan** ke tombol yang membuka dialog setelah ditutup,
 *   supaya pengguna keyboard tidak terlempar ke awal halaman.
 * - **Scroll halaman dikunci** selama dialog terbuka.
 *
 * ## Kenapa dirender lewat portal ke <body>
 *
 * `position: fixed` TIDAK relatif terhadap viewport kalau ada leluhur yang
 * punya `transform` — ia jadi relatif terhadap leluhur itu. Aturan CSS yang
 * mudah dilupakan, dan akibatnya terlihat jelas.
 *
 * Terjadi sungguhan: tombol Hapus konsep berada di dalam kartu, dan kartu itu
 * punya `transform: translateY(-2px)` saat hover. Selama kursor masih di atas
 * kartu — yaitu tepat setelah tombolnya diklik — dialognya berhenti jadi modal
 * dan menyusut jadi kotak sempit di dalam kartu, lengkap dengan latar gelap
 * yang cuma menutupi kartu itu.
 *
 * Portal memindahkannya ke <body>, di luar jangkauan transform mana pun. Ini
 * bukan kerapian: selama dialog ini dipakai di dalam kartu yang bisa bergerak,
 * `fixed` saja memang tidak cukup.
 */
export function Konfirmasi({
  terbuka,
  judul,
  pesan,
  labelYa = "Ya",
  labelBatal = "Batal",
  busy = false,
  onYa,
  onBatal,
}: {
  terbuka: boolean;
  judul: string;
  pesan: string;
  labelYa?: string;
  labelBatal?: string;
  busy?: boolean;
  onYa: () => void;
  onBatal: () => void;
}) {
  const batalRef = useRef<HTMLButtonElement>(null);
  const pemicuRef = useRef<Element | null>(null);
  // Portal butuh `document`, yang tidak ada saat render di server. Dipasang
  // setelah komponen menempel, jadi render pertama di server tetap kosong —
  // dan itu benar: dialog tertutup memang tidak menghasilkan apa-apa.
  const [menempel, setMenempel] = useState(false);
  useEffect(() => setMenempel(true), []);

  useEffect(() => {
    if (!terbuka) return;

    pemicuRef.current = document.activeElement;
    batalRef.current?.focus();

    const semula = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onBatal();
    };
    document.addEventListener("keydown", onKey);

    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = semula;
      (pemicuRef.current as HTMLElement | null)?.focus?.();
    };
  }, [terbuka, busy, onBatal]);

  if (!terbuka || !menempel) return null;

  return createPortal(
    <div
      className="modal-latar"
      onClick={() => !busy && onBatal()}
      role="presentation"
    >
      <div
        className="modal-kartu"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="modal-judul"
        aria-describedby="modal-pesan"
        // Klik di dalam kartu tidak boleh ikut menutup dialog.
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="modal-judul" className="modal-judul">
          {judul}
        </h2>
        <p id="modal-pesan" className="modal-pesan">
          {pesan}
        </p>

        <div className="modal-aksi">
          <button
            ref={batalRef}
            className="btn ghost"
            type="button"
            disabled={busy}
            onClick={onBatal}
          >
            {labelBatal}
          </button>
          <button
            className="btn modal-bahaya"
            type="button"
            disabled={busy}
            onClick={onYa}
          >
            {busy ? "Menghapus…" : labelYa}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
