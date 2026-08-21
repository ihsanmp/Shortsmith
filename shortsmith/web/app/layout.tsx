import type { Metadata } from "next";
import type { ReactNode } from "react";
import { cookies } from "next/headers";

import { COOKIE_NAME, bacaIsiSesi } from "@/lib/session";
import { akunSekarang } from "@/lib/akun";

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

  // Nama dan foto disiapkan DI SERVER, bukan diambil menu profil belakangan.
  //
  // Avatar kecil di navbar terlihat sejak halaman muncul, sementara isi menunya
  // baru diambil saat dibuka. Kalau keduanya mengandalkan pengambilan yang
  // sama, avatarnya menampilkan gambar bawaan sampai seseorang membuka menu —
  // dan bagi yang baru saja mengunggah foto, itu terbaca seperti unggahannya
  // gagal.
  //
  // Ongkosnya satu pembacaan berindeks per render halaman. Itu jauh lebih murah
  // daripada tulisan yang dulu ada di sini, dan ia hanya berjalan untuk sesi
  // yang memang punya akun.
  const akun = tamu ? null : await akunSekarang(sesi);

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
              <MenuProfil
                awalUsername={akun?.username ?? null}
                awalAvatarUrl={akun?.avatarUrl ?? null}
              />
            </div>
          </nav>
          {children}
        </div>
      </body>
    </html>
  );
}
