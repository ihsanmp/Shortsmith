import type { Metadata } from "next";
import type { ReactNode } from "react";
import { cookies } from "next/headers";

import { COOKIE_NAME, bacaIsiSesi } from "@/lib/session";

import "./globals.css";
import { NavUtama } from "./nav-utama";
import { MenuProfil } from "@/components/ui/menu-profil";

export const metadata: Metadata = {
  title: "Shortsmith",
  description: "Dari rekaman panjang ke short video, otomatis.",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const sesi = bacaIsiSesi((await cookies()).get(COOKIE_NAME)?.value);
  // Satu fakta, dua akibat di navbar: tamu tidak melihat "Buat Short", dan
  // hanya tamu yang melihat "Get Started". Diturunkan sebagai satu prop supaya
  // keduanya tidak bisa berbeda pendapat.
  const tamu = !sesi || sesi.peran === "tamu";

  return (
    <html lang="id">
      <body>
        <div className="shell">
          <nav className="nav">
            <a href="/" className="brand">
              Shortsmith
            </a>
            {/* Tiga sel terpisah, bukan dua. Nav pil harus berada di tengah
                HALAMAN, bukan di tengah ruang sisa antara logo dan menu profil —
                keduanya beda lebar, jadi menaruhnya di satu kelompok kanan akan
                membuatnya meleset dari poros. */}
            <div className="nav-tengah">
              <NavUtama tamu={tamu} />
            </div>
            <div className="nav-kanan">
              <MenuProfil />
            </div>
          </nav>
          {children}
        </div>
      </body>
    </html>
  );
}
