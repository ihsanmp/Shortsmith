"use client";

import { useEffect, useState } from "react";

import { MenuProfil } from "@/components/ui/menu-profil";
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
 */

type Sesi = {
  peran?: string;
  username?: string | null;
  avatarUrl?: string | null;
};

export function NavBar() {
  const [tamu, setTamu] = useState<boolean | null>(null);
  const [akun, setAkun] = useState<Sesi | null>(null);

  useEffect(() => {
    let hidup = true;
    (async () => {
      try {
        const r = await fetch("/api/sesi", { cache: "no-store" });
        if (!r.ok) throw new Error(String(r.status));
        const d = (await r.json()) as Sesi;
        if (!hidup) return;
        setAkun(d);
        setTamu(d.peran === "tamu");
      } catch {
        // Gagal menanyakan sesi TIDAK boleh menyembunyikan navigasi. Yang
        // paling mungkin sedang terjadi adalah jaringan bermasalah, dan saat
        // itulah pengguna paling butuh bisa berpindah halaman. Diperlakukan
        // sebagai tamu: itu keadaan dengan hak paling sedikit, jadi tidak ada
        // pintu yang dibukakan untuk orang yang belum terbukti berhak.
        if (hidup) setTamu(true);
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
