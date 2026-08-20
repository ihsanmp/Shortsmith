/**
 * Tailwind v4 dipasang lewat plugin PostCSS-nya sendiri.
 *
 * Tidak ada tailwind.config.js: v4 dikonfigurasi dari CSS (`@theme`,
 * `@custom-variant`), dan konfigurasinya ada di app/globals.css bersama token
 * yang sudah dipakai seluruh aplikasi — satu tempat, bukan dua.
 */
const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;
