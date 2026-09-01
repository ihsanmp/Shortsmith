"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

import { MenuProfil } from "@/components/ui/menu-profil";
import { bolehDilihatTamu } from "@/lib/tamu";
import { NavUtama } from "./nav-utama";

/**
 * Navbar yang menanyakan sesinya sendiri dari peramban.
 *
 * ## Kenapa bukan dibaca di server seperti sebelumnya
 *
 * Root layout dulu membaca `cookies()` untuk tahu pengguna tamu atau bukan. Itu
 * satu baris, tapi akibatnya menyeluruh: begitu ada `cookies()` di layout,
 * Next.js tidak bisa menyiapkan halaman APA PUN di muka -- cookie berbeda tiap
 * orang, jadi setiap halaman harus dirender ulang per permintaan, termasuk
 * halaman yang isinya sama untuk semua orang.
 *
 * Terukur dari Jakarta, pada koneksi yang dipakai ulang seperti peramban
 * sungguhan::
 *
 *     aset statis dari CDN     38 ms
 *     halaman dinamis         329 ms
 *
 * Selisihnya hampir seluruhnya render server, dan ia dibayar di setiap
 * perpindahan halaman.
 *
 * ## Kenapa keadaan "belum tahu" digambar sebagai kekosongan
 *
 * Cara mudahnya adalah menganggap semua orang tamu sampai jawabannya datang.
 * Itu membuat navbar menampilkan "Get Started" lalu berganti jadi foto profil
 * beberapa ratus milidetik kemudian -- terbaca seperti aplikasi yang berubah
 * pikiran, dan lebih mengganggu daripada menunggu.
 *
 * Selama `tamu` masih null, tempatnya dikosongkan tapi tingginya dipertahankan.
 * Yang terlihat cuma navbar yang terisi sesaat setelah halaman muncul, bukan
 * navbar yang meralat dirinya.
 *
 * ## Kenapa gagal bertanya TIDAK lagi berarti tamu
 *
 * Sebelumnya satu permintaan gagal langsung menjadikan orangnya tamu, dengan
 * alasan itu keadaan berhak paling sedikit. Alasan itu keliru di sini: navbar
 * tidak memberi hak apa pun. Setiap halaman yang ditautkannya dijaga sendiri
 * oleh middleware dan oleh server, jadi yang dihasilkan kesimpulan itu bukan
 * keamanan tambahan — melainkan pemilik yang sedang menunggu videonya selesai
 * disodori tombol "Get Started" dan kehilangan "Buat Video".
 *
 * Yang terjadi sekarang:
 *
 *   - 401 dijawab apa adanya. Itu bukan kegagalan, itu jawaban: tidak ada sesi.
 *   - Kegagalan lain diulang tiga kali. Satu gangguan sesaat tidak boleh
 *     mengubah tampilan aplikasi sampai halaman dimuat ulang, dan permintaan
 *     inilah satu-satunya yang menentukan bentuk navbar.
 *   - Kalau tetap gagal, perannya DISIMPULKAN dari alamat halaman. Ini bukan
 *     tebakan: middleware sudah menolak tamu dari semua halaman di luar daftar
 *     `lib/tamu.ts`, jadi berada di `/project/...` sudah membuktikan sesinya
 *     milik pemilik. Kesimpulan yang sama, dari bukti yang sama.
 */

type Sesi = {
  peran?: string;
  username?: string | null;
  avatarUrl?: string | null;
};

const PERCOBAAN = 3;
/** Jeda sebelum percobaan ke-2 dan ke-3. Pendek: navbar ditunggu mata. */
const JEDA_MS = [400, 1200];

const tidur = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function NavBar() {
  const [tamu, setTamu] = useState<boolean | null>(null);
  const [akun, setAkun] = useState<Sesi | null>(null);

  // Alamat halaman hanya dibaca kalau bertanya ke server gagal, jadi ia
  // disimpan di ref alih-alih jadi dependensi: sebagai dependensi, setiap
  // perpindahan halaman akan menanyakan sesi lagi — tiga kueri database untuk
  // jawaban yang tidak berubah.
  const jalur = usePathname();
  const jalurRef = useRef(jalur);
  useEffect(() => {
    jalurRef.current = jalur;
  }, [jalur]);

  useEffect(() => {
    let hidup = true;
    (async () => {
      for (let i = 0; i < PERCOBAAN; i++) {
        try {
          const r = await fetch("/api/sesi", { cache: "no-store" });
          if (r.status === 401) {
            // Bukan kegagalan: server menjawab bahwa tidak ada sesi.
            if (hidup) setTamu(true);
            return;
          }
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          const d = (await r.json()) as Sesi;
          if (!hidup) return;
          setAkun(d);
          setTamu(d.peran === "tamu");
          return;
        } catch (err) {
          if (!hidup) return;
          if (i < PERCOBAAN - 1) {
            await tidur(JEDA_MS[i]);
            if (!hidup) return;
            continue;
          }
          console.warn(
            `[navbar] sesi tidak terbaca setelah ${PERCOBAAN} percobaan; ` +
              "peran disimpulkan dari alamat halaman",
            err,
          );
          setTamu(bolehDilihatTamu(jalurRef.current));
        }
      }
    })();
    return () => {
      hidup = false;
    };
  }, []);

  return (
    <>
      <div className="nav-tengah">
        {/* Tinggi dipertahankan walau isinya belum ada, supaya isi halaman di
            bawahnya tidak melompat saat navbar terisi. */}
        {tamu === null ? <div className="nav-kosong" /> : <NavUtama tamu={tamu} />}
      </div>
      <div className="nav-kanan">
        {tamu === null ? (
          <div className="nav-kosong" />
        ) : (
          <MenuProfil
            awalUsername={akun?.username ?? null}
            awalAvatarUrl={akun?.avatarUrl ?? null}
          />
        )}
      </div>
    </>
  );
}
