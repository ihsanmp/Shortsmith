"use client";

import { NavPil, type AksiNav, type ItemNav } from "@/components/ui/nav-pil";

/**
 * Isi navigasi utama.
 *
 * ## Kenapa "Keluar" ikut masuk ke dalam pil
 *
 * Ia bukan tautan halaman, tapi ia berdiri sejajar dengan "Project" dan
 * "Konsep" di mata pengguna: tiga hal yang bisa diklik di pojok yang sama.
 * Mengeluarkannya dari pil akan membuat satu-satunya item yang tampak berbeda
 * justru yang paling jarang dipakai.
 *
 * `NavPil` menerima item tanpa `href` sebagai `<button>`, jadi semantiknya tetap
 * benar — aksi tetap tombol, navigasi tetap tautan.
 */
/**
 * Daftar project dan Keluar tidak ada di navbar — keduanya hidup di menu
 * profil. Navbar menyimpan yang dibuka berulang kali sepanjang hari; menu
 * profil menyimpan yang dicari sesekali dan tahu di mana mencarinya.
 */
const DASHBOARD: ItemNav = {
  // Beranda tidak lagi memuat daftar project, jadi ia perlu pintunya sendiri.
  // Tanpa ini satu-satunya jalan pulang adalah logo di pojok kiri — tempat yang
  // tidak semua orang tahu bisa diklik.
  label: "Dashboard",
  href: "/",
  cocok: (p) => p === "/",
};

const BUAT: ItemNav = {
  label: "Buat Short",
  href: "/project/new",
  cocok: (p) => p.startsWith("/project/new"),
};

const ABOUT: ItemNav = {
  label: "About",
  href: "/about",
  cocok: (p) => p.startsWith("/about"),
};

/**
 * Tamu hanya boleh membaca. Server menolak pembuatan project dengan 403, jadi
 * "Buat Short" untuknya adalah pintu yang pasti tertutup — dan pintu semacam
 * itu baru ketahuan tertutup setelah seluruh form diisi.
 *
 * Sebagai gantinya ia mendapat "Get Started", yang menuju halaman masuk.
 * Keduanya berpasangan: yang satu muncul persis ketika yang lain tidak.
 */
const AKSI: AksiNav = { label: "Get Started", href: "/login?mulai=1" };

export function NavUtama({ tamu }: { tamu: boolean }) {
  const item = tamu ? [DASHBOARD, ABOUT] : [DASHBOARD, BUAT, ABOUT];
  return <NavPil items={item} aksi={tamu ? AKSI : undefined} />;
}
