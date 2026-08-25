"use client";

import { useState } from "react";

import { galatDari } from "@/lib/galat";

/**
 * Daftar centang topik, muncul di tengah job yang topiknya dikosongkan.
 *
 * ## Kenapa di tengah job, bukan di form
 *
 * Topik hanya bisa dibaca setelah ada transkrip, dan transkrip baru ada setelah
 * analisis berjalan. Diukur pada rekaman podcast 55 menit: 24-36 menit untuk
 * bahan baru, 0 detik untuk bahan yang sudah pernah dipakai.
 *
 * Menaruh pertanyaannya di form berarti pengguna menatap layar diam selama
 * setengah jam sebelum ada yang bisa dipilih. Di sini analisisnya adalah
 * pekerjaan yang memang harus dilakukan job itu juga, progresnya terlihat
 * berjalan, dan pertanyaannya muncul tepat saat jawabannya sudah ada.
 *
 * ## Kenapa tidak menjawab tetap menghasilkan video
 *
 * Agent menunggu setengah jam, lalu membuat SELURUH topik — perilaku otomatis
 * yang sama dengan sebelum panel ini ada. Orang yang menyalakan job lalu pergi
 * tidak boleh pulang ke tangan kosong.
 */

export function PilihTopik({
  jobId,
  topik,
  onKirim,
}: {
  jobId: string;
  topik: string[];
  /** Dipanggil setelah pilihan tersimpan, supaya halaman berhenti bertanya. */
  onKirim: (dipilih: string[]) => void;
}) {
  // Bawaannya SEMUA tercentang, bukan kosong.
  //
  // Yang sampai di sini adalah orang yang memang tidak menentukan topik, jadi
  // "buatkan semuanya" adalah maksud yang paling mungkin. Mengosongkan
  // centangan berarti menuntut pekerjaan tambahan sebelum ia mendapat apa pun
  // yang ia sudah setuju dapatkan.
  const [pilih, setPilih] = useState<Set<number>>(
    () => new Set(topik.map((_, i) => i)),
  );
  const [sibuk, setSibuk] = useState(false);
  const [error, setError] = useState("");

  function toggle(i: number) {
    setPilih((lama) => {
      const baru = new Set(lama);
      if (baru.has(i)) baru.delete(i);
      else baru.add(i);
      return baru;
    });
  }

  async function kirim() {
    setError("");
    setSibuk(true);
    // Urutan aslinya dipertahankan, bukan urutan pengguna mencentang: agent
    // membuat klip sesuai urutan daftar, dan topik-topiknya sengaja disebar
    // sepanjang rekaman.
    const dipilih = topik.filter((_, i) => pilih.has(i));
    try {
      const res = await fetch(`/api/jobs/${jobId}/topik`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ topik: dipilih }),
      });
      if (!res.ok) throw new Error(await galatDari(res, "Gagal mengirim pilihan"));
      onKirim(dipilih);
    } catch (e) {
      setError((e as Error).message);
      setSibuk(false);
    }
  }

  return (
    <div className="pilih-topik">
      <h2 className="pilih-topik-judul">Topik apa saja yang mau dibuat?</h2>
      <p className="pilih-topik-catatan">
        Kamu tidak menulis topik, jadi rekamannya sudah dibaca dulu. Satu klip
        dibuat untuk setiap topik yang dicentang.
      </p>

      <ul className="pilih-topik-daftar">
        {topik.map((t, i) => (
          <li key={t}>
            <label className="pilih-topik-baris">
              <input
                type="checkbox"
                checked={pilih.has(i)}
                onChange={() => toggle(i)}
                disabled={sibuk}
              />
              <span>{t}</span>
            </label>
          </li>
        ))}
      </ul>

      {error && (
        <div className="notice err" role="alert">
          {error}
        </div>
      )}

      <div className="pilih-topik-aksi">
        <button
          type="button"
          className="btn primary"
          onClick={kirim}
          disabled={sibuk}
        >
          {sibuk
            ? "Mengirim…"
            : pilih.size === 0
              ? "Lanjut tanpa memilih"
              : `Buat ${pilih.size} klip`}
        </button>
        {/* Jumlahnya disebut di tombol, bukan cuma "Lanjut". Perbedaan antara
            satu klip dan lima klip adalah selisih setengah jam render, dan itu
            pantas terlihat sebelum ditekan, bukan sesudah. */}
      </div>
    </div>
  );
}
