import React from "react";

type TProgressType = "default" | "success" | "warning" | "error" | "secondary";

interface ProgressProps {
  value: number;
  max?: number;
  colors?: { [key: string]: string };
  type?: TProgressType;
  className?: string;
}

/**
 * Bilah progres tipis berbasis elemen `<progress>` bawaan.
 *
 * ## Bedanya dengan `progress-bar.tsx`
 *
 * `ProgressBar` besar dan bersuara: gerak pegas, label yang menyilang, keadaan
 * indeterminate, pengumuman aria-live. Ia dipakai di halaman proses, tempat
 * satu bilah itu memang isi halamannya.
 *
 * Yang di sini kebalikannya — setinggi 10 piksel, tanpa teks, tanpa animasi
 * masuk. Dipakai di dalam kartu yang sudah punya judul dan keterangannya
 * sendiri, tempat bilah bergerak-gerak dengan label justru berebut perhatian
 * dengan isi kartunya.
 *
 * ## Dua perbaikan atas komponen aslinya
 *
 * 1. **Warna isiannya tidak pernah muncul.** Aslinya menyetel
 *    `--ds-progress-color` lewat `style`, tapi tidak ada satu aturan pun yang
 *    memakainya — `::-webkit-progress-value` dan `::-moz-progress-bar` tidak
 *    pernah diberi `background`. Hasilnya bilah berwarna bawaan peramban, dan
 *    seluruh prop `colors`/`type` tidak berpengaruh. Aturannya ditambahkan di
 *    globals.css, di bawah `.progress-ds`.
 *
 * 2. **Palet gandanya dibuang.** Aslinya membawa `--ds-*` dan `--geist-*`
 *    sendiri. Aplikasi ini sudah punya token yang dipakai seluruh halaman, dan
 *    dua palet dalam satu berkas berarti dua tempat yang harus diingat setiap
 *    kali warna berubah. `--ds-*` sekarang alias ke token yang sudah ada, jadi
 *    API komponen ini utuh tanpa menambah sumber kebenaran kedua.
 */

const getColor = (value: number, type: TProgressType, colors?: ProgressProps["colors"]) => {
  if (colors) {
    // Ambang dibaca dari besar ke kecil supaya yang tertinggi menang. Kuncinya
    // diurutkan dulu secara ANGKA: urutan kunci objek JavaScript mengikuti
    // urutan sisip untuk kunci non-integer, dan "100" sebelum "25" akan
    // membuat perbandingannya berhenti di ambang yang salah.
    const ambang = Object.keys(colors)
      .map(Number)
      .filter((n) => !Number.isNaN(n))
      .sort((a, b) => b - a);
    for (const n of ambang) {
      if (value >= n) return colors[String(n)];
    }
    return undefined;
  }
  switch (type) {
    case "success":
      return "var(--ds-blue-700)";
    case "error":
      return "var(--ds-red-700)";
    case "warning":
      return "var(--ds-amber-700)";
    case "secondary":
      return "var(--ds-gray-700)";
    default:
      return "var(--ds-gray-1000)";
  }
};

export const Progress = ({
  value,
  max = 100,
  colors,
  type = "default",
  className = "",
}: ProgressProps) => {
  return (
    <progress
      value={value}
      max={max}
      className={`progress-ds h-2.5 w-full appearance-none border-none ${className}`.trim()}
      style={{ "--ds-progress-color": getColor(value, type, colors) } as React.CSSProperties}
    />
  );
};
