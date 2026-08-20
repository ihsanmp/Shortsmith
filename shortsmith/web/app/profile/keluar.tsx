"use client";

/**
 * Tombol keluar untuk halaman profil.
 *
 * Dipisah jadi komponen klien sendiri supaya halaman profilnya tetap komponen
 * server — seluruh datanya (hitungan project, konsep, kedaluwarsa sesi) dibaca
 * langsung dari database dan cookie, tanpa satu pun permintaan tambahan dari
 * browser.
 */
export function TombolKeluar() {
  return (
    <button
      type="button"
      className="profil-halaman-tombol profil-halaman-tombol-keluar"
      onClick={async () => {
        await fetch("/api/login", { method: "DELETE" });
        // Muat ulang penuh: seluruh cache halaman harus ikut hilang bersama
        // sesinya.
        window.location.href = "/login";
      }}
    >
      Keluar
    </button>
  );
}
