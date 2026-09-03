import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";
import { Logo } from "@/components/ui/logo";
import { NavBar } from "./nav-bar";

export const metadata: Metadata = {
  title: "Shortsmith",
  description: "Dari rekaman panjang ke short video, otomatis.",
};

/**
 * Layout ini SENGAJA tidak membaca cookie.
 *
 * Dulu ia membacanya untuk tahu pengguna tamu atau bukan, lalu meneruskannya ke
 * navbar. Satu baris, tapi akibatnya menyeluruh: `cookies()` di layout membuat
 * Next.js tidak bisa menyiapkan halaman apa pun di muka -- setiap halaman harus
 * dirender per permintaan, termasuk /about dan /video/baru yang isinya sama
 * untuk semua orang.
 *
 * Terukur dari Jakarta pada koneksi yang dipakai ulang: aset statis dari CDN 38
 * ms, halaman dinamis 329 ms. Selisihnya dibayar di setiap perpindahan halaman.
 *
 * Sesi sekarang ditanyakan navbar sendiri dari peramban -- lihat nav-bar.tsx
 * untuk cara keadaan "belum tahu" digambar tanpa membuat navbar terlihat
 * berubah pikiran.
 *
 * Halaman yang isinya MEMANG bergantung pada database (/projects, /project/[id],
 * /concepts) tetap dinamis, dan itu benar: isinya berbeda tiap orang.
 */
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="id">
      <body>
        <div className="shell">
          <nav className="nav">
            <a href="/" className="brand">
              <Logo ukuran={22} />
              Shortsmith
            </a>
            {/* Tiga sel terpisah, bukan dua. Nav pil harus berada di tengah
                HALAMAN, bukan di tengah ruang sisa antara logo dan menu profil —
                keduanya beda lebar, jadi menaruhnya di satu kelompok kanan akan
                membuatnya meleset dari poros. */}
            <NavBar />
          </nav>
          {children}
        </div>
      </body>
    </html>
  );
}
