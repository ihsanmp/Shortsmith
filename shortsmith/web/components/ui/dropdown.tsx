"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";

/**
 * Dropdown pilihan tunggal, menggantikan `<select>` bawaan.
 *
 * ## Kenapa tidak memakai `<select>` saja
 *
 * Daftar pilihannya digambar sistem operasi, bukan halaman ini. Ia mengabaikan
 * seluruh warna, sudut, dan jarak yang dipakai di sisa aplikasi — dan tidak bisa
 * memuat baris kedua, padahal ukuran berkas dan keterangan konsep justru yang
 * paling menentukan saat memilih.
 *
 * ## Yang harus ditulis ulang karena meninggalkan `<select>`
 *
 * Semua yang dulu gratis: navigasi panah, Home/End, Escape, pengumuman ke
 * pembaca layar, dan menutup saat menekan di luar. Itu ongkos yang nyata, dan
 * dibayar di sini supaya tidak ada satu pun yang hilang diam-diam.
 *
 * Pola ARIA-nya `combobox` + `listbox`: pemicu menyatakan dirinya combobox yang
 * mengendalikan sebuah listbox, tiap baris jadi `option`, dan yang sedang
 * disorot ditunjuk `aria-activedescendant` — bukan dengan memindahkan fokus,
 * karena fokus yang berpindah ke baris membuat pemicunya kehilangan hubungan
 * dengan labelnya.
 */

export type OpsiDropdown = {
  nilai: string;
  judul: string;
  /** Baris kedua, lebih redup. Ukuran berkas, jumlah potongan, dan sejenisnya. */
  ket?: string;
  /** Nama kelompok. Opsi dengan grup sama akan dikumpulkan di bawah satu judul. */
  grup?: string;
  nonaktif?: boolean;
};

function Chevron({ terbuka }: { terbuka: boolean }) {
  return (
    <svg
      className={`dd-chevron${terbuka ? " dd-chevron-naik" : ""}`}
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

export function Dropdown({
  nilai,
  opsi,
  onPilih,
  placeholder = "— pilih —",
  disabled = false,
  id,
  className = "",
}: {
  nilai: string;
  opsi: OpsiDropdown[];
  onPilih: (nilai: string) => void;
  placeholder?: string;
  disabled?: boolean;
  id?: string;
  className?: string;
}) {
  const [terbuka, setTerbuka] = useState(false);
  const [sorot, setSorot] = useState(-1);
  const wadahRef = useRef<HTMLDivElement | null>(null);
  const daftarRef = useRef<HTMLUListElement | null>(null);
  const pemicuRef = useRef<HTMLButtonElement | null>(null);
  const idOtomatis = useId();
  const idDaftar = `${id ?? idOtomatis}-daftar`;

  const bisaDipilih = useMemo(() => opsi.filter((o) => !o.nonaktif), [opsi]);
  const terpilih = opsi.find((o) => o.nilai === nilai) ?? null;

  // Baris dan judul kelompoknya dirangkai sekali di sini, jadi penomoran indeks
  // untuk panah keyboard tidak perlu memperhitungkan judul kelompok yang bukan
  // pilihan.
  const baris = useMemo(() => {
    const keluar: { grup?: string; opsi: OpsiDropdown; indeks: number }[] = [];
    let grupTerakhir: string | undefined;
    let i = 0;
    for (const o of opsi) {
      const grupBaru = o.grup !== grupTerakhir ? o.grup : undefined;
      grupTerakhir = o.grup;
      keluar.push({ grup: grupBaru, opsi: o, indeks: o.nonaktif ? -1 : i++ });
    }
    return keluar;
  }, [opsi]);

  function buka() {
    if (disabled) return;
    setTerbuka(true);
    const i = bisaDipilih.findIndex((o) => o.nilai === nilai);
    setSorot(i >= 0 ? i : 0);
  }

  function tutup(kembalikanFokus = true) {
    setTerbuka(false);
    setSorot(-1);
    if (kembalikanFokus) pemicuRef.current?.focus();
  }

  function pilih(o: OpsiDropdown) {
    if (o.nonaktif) return;
    onPilih(o.nilai);
    tutup();
  }

  useEffect(() => {
    if (!terbuka) return;
    function diLuar(e: MouseEvent) {
      if (!wadahRef.current?.contains(e.target as Node)) tutup(false);
    }
    document.addEventListener("mousedown", diLuar);
    return () => document.removeEventListener("mousedown", diLuar);
  }, [terbuka]);

  // Baris yang disorot digulirkan ke dalam pandangan. Tanpa ini, menekan panah
  // di daftar panjang menggerakkan sorotan ke tempat yang tidak terlihat.
  useEffect(() => {
    if (!terbuka || sorot < 0) return;
    const el = daftarRef.current?.querySelector<HTMLElement>(`[data-i="${sorot}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [terbuka, sorot]);

  function tombol(e: React.KeyboardEvent) {
    if (disabled) return;

    if (!terbuka) {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
        e.preventDefault();
        buka();
      }
      return;
    }

    if (e.key === "Escape") {
      e.preventDefault();
      tutup();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setSorot((i) => Math.min(bisaDipilih.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSorot((i) => Math.max(0, i - 1));
    } else if (e.key === "Home") {
      e.preventDefault();
      setSorot(0);
    } else if (e.key === "End") {
      e.preventDefault();
      setSorot(bisaDipilih.length - 1);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      const o = bisaDipilih[sorot];
      if (o) pilih(o);
    } else if (e.key === "Tab") {
      tutup(false);
    }
  }

  return (
    <div className={`dd ${className}`} ref={wadahRef}>
      <button
        ref={pemicuRef}
        id={id}
        type="button"
        role="combobox"
        aria-expanded={terbuka}
        aria-controls={idDaftar}
        aria-haspopup="listbox"
        aria-activedescendant={
          terbuka && sorot >= 0 ? `${idDaftar}-${sorot}` : undefined
        }
        disabled={disabled}
        className={`dd-pemicu${terbuka ? " dd-pemicu-terbuka" : ""}`}
        onClick={() => (terbuka ? tutup() : buka())}
        onKeyDown={tombol}
      >
        <span className={`dd-nilai${terpilih ? "" : " dd-nilai-kosong"}`}>
          {terpilih ? terpilih.judul : placeholder}
        </span>
        <Chevron terbuka={terbuka} />
      </button>

      {terbuka && (
        <ul className="dd-panel" role="listbox" id={idDaftar} ref={daftarRef}>
          {baris.map(({ grup, opsi: o, indeks }) => (
            <li key={`${o.grup ?? ""}/${o.nilai}`}>
              {grup !== undefined && grup !== "" && (
                <div className="dd-grup" role="presentation">
                  {grup}
                </div>
              )}
              <div
                id={indeks >= 0 ? `${idDaftar}-${indeks}` : undefined}
                data-i={indeks}
                role="option"
                aria-selected={o.nilai === nilai}
                aria-disabled={o.nonaktif || undefined}
                className={
                  "dd-opsi" +
                  (indeks === sorot ? " dd-opsi-sorot" : "") +
                  (o.nilai === nilai ? " dd-opsi-terpilih" : "") +
                  (o.nonaktif ? " dd-opsi-mati" : "")
                }
                // mousedown, bukan click: penangan "tekan di luar" berjalan pada
                // mousedown juga, dan tanpa ini panel sudah tertutup sebelum
                // click sempat terjadi.
                onMouseDown={(e) => {
                  e.preventDefault();
                  pilih(o);
                }}
                onMouseEnter={() => indeks >= 0 && setSorot(indeks)}
              >
                <span className="dd-opsi-judul">{o.judul}</span>
                {o.ket && <span className="dd-opsi-ket">{o.ket}</span>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default Dropdown;
