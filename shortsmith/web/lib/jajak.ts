"use client";

import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";

import { galatDari } from "./galat";

/**
 * Menanyakan keadaan satu project berulang kali, sampai selesai.
 *
 * ## Bug yang diperbaikinya
 *
 * Dua halaman menjalankan loop yang sama, dan keduanya berhenti SELAMANYA pada
 * satu permintaan yang gagal:
 *
 *     } catch (err) {
 *       if (alive) setError((err as Error).message);
 *     }
 *
 * Tidak ada `setTimeout` di cabang itu, jadi rantainya putus di situ. Satu
 * gangguan jaringan sekejap — dan log daemon di mesin ini memuat puluhan
 * kegagalan DNS — membuat layar tunggu membeku pada angka terakhirnya. Render
 * di PC pengguna tetap selesai, tapi halaman tidak pernah tahu, tidak pernah
 * pindah ke hasilnya, dan janji yang tertulis persis di bawah bilah progresnya
 * ("Halaman ini memperbarui sendiri dan akan pindah ke hasilnya begitu selesai
 * — tidak perlu ditunggu di sini") menjadi tidak benar.
 *
 * ## Kenapa galatnya tidak langsung ditampilkan
 *
 * Satu permintaan meleset adalah kejadian biasa, bukan kerusakan. Menampilkan
 * kotak merah untuknya membuat gangguan setengah detik terlihat seperti sesuatu
 * yang perlu ditindak — padahal yang dibutuhkan cuma menunggu sebentar dan
 * bertanya lagi. Pesannya baru muncul setelah tiga kegagalan beruntun, dan
 * hilang sendiri begitu satu jawaban berhasil masuk.
 *
 * ## Kenapa dijadikan satu tempat
 *
 * Loopnya identik di kedua halaman, dan bugnya juga identik di keduanya — dua
 * salinan berarti perbaikan yang harus diingat dua kali.
 */

const JEDA_MS = 4000;

/**
 * Jeda setelah kegagalan ke-1, ke-2, dan seterusnya. Mundur perlahan supaya
 * server yang sedang bermasalah tidak dihujani, lalu berhenti di 15 detik:
 * lebih lama dari itu, halaman terasa sudah menyerah.
 */
const JEDA_GAGAL_MS = [1000, 2000, 5000, 10000, 15000];

const GAGAL_SEBELUM_LAPOR = 3;

export function useJajakProject<T>(
  id: string,
  /**
   * Dipanggil untuk tiap jawaban. `true` menghentikan penjajakan.
   *
   * Boleh melakukan efek samping — halaman proses memakainya untuk berpindah ke
   * halaman hasil. Alternatifnya adalah menyalin syarat "sudah selesai" ke
   * pemanggil supaya predikatnya murni, dan syarat yang ditulis dua kali adalah
   * syarat yang cepat atau lambat berbeda di kedua tempat.
   */
  selesai: (d: T) => boolean,
): {
  data: T | null;
  error: string;
  /**
   * Menambal jawaban terakhir tanpa menunggu jajakan berikutnya.
   *
   * Dipakai halaman proses setelah pengguna memilih topik: server sudah
   * menerimanya, dan menunggu empat detik sebelum pertanyaannya hilang membuat
   * klik terasa tidak diterima. Jajakan berikutnya menimpanya dengan keadaan
   * dari server, yang saat itu sudah sama.
   */
  setData: Dispatch<SetStateAction<T | null>>;
} {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");

  // Pemanggil menulis ulang predikatnya tiap render. Sebagai dependensi efek,
  // ia akan memulai ulang seluruh penjajakan setiap kali halaman menggambar.
  const selesaiRef = useRef(selesai);
  useEffect(() => {
    selesaiRef.current = selesai;
  });

  useEffect(() => {
    let hidup = true;
    let timer: ReturnType<typeof setTimeout>;
    let gagal = 0;

    async function jajak() {
      try {
        const res = await fetch(`/api/projects/${id}`, { cache: "no-store" });
        if (!res.ok) throw new Error(await galatDari(res, "Gagal memuat"));
        const d = (await res.json()) as T;
        if (!hidup) return;

        gagal = 0;
        setError("");
        setData(d);
        if (selesaiRef.current(d)) return;
        timer = setTimeout(jajak, JEDA_MS);
      } catch (err) {
        if (!hidup) return;
        gagal += 1;
        if (gagal >= GAGAL_SEBELUM_LAPOR) setError((err as Error).message);
        const jeda = JEDA_GAGAL_MS[Math.min(gagal - 1, JEDA_GAGAL_MS.length - 1)];
        timer = setTimeout(jajak, jeda);
      }
    }

    jajak();
    return () => {
      hidup = false;
      clearTimeout(timer);
    };
  }, [id]);

  return { data, error, setData };
}
