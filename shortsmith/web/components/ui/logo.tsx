/**
 * Lambang Shortsmith untuk dipakai DI DALAM aplikasi.
 *
 * ## Kenapa bukan `<img src="/logo.svg">`
 *
 * Berkas di public/ memakai warna tetap: pita gelap, lubang putih. Itu benar
 * untuk lambang yang berdiri sendiri di latar putih, dan salah di sini — navbar
 * beralas #0b0d18, dan pita #1f2024 di atasnya praktis tidak terlihat.
 *
 * Versi ini mengambil warna pitanya dari `currentColor`, jadi ia mengikuti warna
 * teks di sekitarnya: terang di navbar gelap, gelap di dalam panel terang. Satu
 * berkas, dua tema, tanpa satu pun aturan tambahan.
 *
 * ## Kenapa lubangnya mask, bukan diisi warna latar
 *
 * Mengisi lubang dengan warna latar menuntut lambang ini tahu apa yang ada di
 * belakangnya. Ia tidak tahu, dan tidak seharusnya tahu: navbar-nya
 * semi-transparan, dan lambang yang menebak akan menempelkan bercak buram di
 * setiap lubangnya.
 *
 * Dengan mask, lubangnya benar-benar berlubang — apa pun yang ada di belakang
 * terlihat menembus, termasuk video latar di beranda.
 *
 * ## Kenapa perforasinya tidak digambar satu per satu
 *
 * Ketiga sapuan memakai path yang sama: satu selebar pita, satu putus-putus
 * untuk melubangi kedua tepi, satu lagi lebih tipis untuk mengembalikan saluran
 * tengahnya. Dash mengikuti panjang path, jadi lubangnya melengkung sendiri
 * mengikuti huruf S dan mengubah bentuk hurufnya tidak menuntut menata ulang
 * lubangnya.
 *
 * `stroke-linecap` sapuan kedua harus `butt`. Dengan `round`, tiap dash
 * memanjang setengah lebar sapuan di kedua ujungnya — 7,5 unit, sementara
 * celahnya 5 — sehingga dash-nya bersentuhan dan yang tergambar bukan deretan
 * lubang melainkan satu garis bergelombang mengelilingi hurufnya.
 */

const PITA =
  "M45.5 17 C45.5 11 38.5 8 31 9 C21.5 10 16 16.5 19 22.5 C22 28.5 34 30.5 41 34.5 C48 38.5 50.5 46.5 44 52 C37.5 57.5 26 56 21 49.5";

export function Logo({ ukuran = 20 }: { ukuran?: number }) {
  return (
    <svg
      width={ukuran}
      height={ukuran}
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden
      focusable="false"
    >
      <defs>
        <mask id="lubang-film" maskUnits="userSpaceOnUse" x="0" y="0" width="64" height="64">
          <path d={PITA} stroke="#fff" strokeWidth="15" strokeLinecap="round" />
          <path
            d={PITA}
            stroke="#000"
            strokeWidth="15"
            strokeLinecap="butt"
            strokeDasharray="2.8 5"
          />
          <path d={PITA} stroke="#fff" strokeWidth="9" strokeLinecap="round" />
        </mask>
      </defs>

      <rect width="64" height="64" fill="currentColor" mask="url(#lubang-film)" />

      {/* Segitiga putar, duduk di pinggang huruf S tempat kedua lengkungnya
          bersilang. Ungu ini warna fokus yang sudah dipakai aplikasi, bukan
          ungu baru yang cuma hidup di lambang. */}
      <path
        d="M26.5 22.5 L44 32 L26.5 41.5 Z"
        fill="var(--focus, #b567c2)"
        stroke="currentColor"
        strokeWidth="2.6"
        strokeLinejoin="round"
      />
    </svg>
  );
}
