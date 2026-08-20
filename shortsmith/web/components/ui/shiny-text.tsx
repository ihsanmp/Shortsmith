/**
 * Teks dengan kilau yang menyapu terus-menerus dari kiri ke kanan.
 *
 * ## Cara kerjanya
 *
 * Gradien dipasang sebagai LATAR, lalu dipotong mengikuti bentuk huruf dengan
 * `background-clip: text` sementara isian hurufnya dibuat tembus pandang. Yang
 * bergerak karena itu bukan teksnya, melainkan posisi latarnya.
 *
 * Latarnya 250% selebar kotaknya supaya pita kilau punya ruang untuk masuk dan
 * keluar sepenuhnya. Kalau selebar kotaknya, kilaunya sudah terlihat sejak awal
 * lalu berhenti mendadak di ujung.
 *
 * ## Kenapa keyframe CSS, bukan framer-motion seperti yang diminta
 *
 * `background-position` bukan properti yang bisa diserahkan motion ke mesin
 * animasi browser, jadi motion menggerakkannya lewat requestAnimationFrame —
 * satu putaran JavaScript yang berjalan selamanya untuk elemen terbesar di
 * halaman, dan berhenti setiap kali tabnya tidak dilukis.
 *
 * Keyframe CSS diserahkan ke mesin gaya browser: tidak ada JavaScript yang
 * dikirim untuk ini sama sekali, komponennya bisa tetap komponen server, dan
 * animasinya benar-benar terdaftar di browser sehingga bisa diperiksa. Hasil di
 * layar sama persis; yang berbeda hanya siapa yang menggerakkannya.
 *
 * ## Kenapa arah sapuannya dari 100% ke 0%
 *
 * `background-position: 100%` menempelkan tepi KANAN gambar ke tepi kanan
 * kotak, jadi pita kilau yang duduk di tengah gambar berada di sisi kiri.
 * Menurunkannya ke 0% menggeser gambar ke kanan relatif terhadap kotaknya, dan
 * kilaunya berjalan kiri ke kanan. Menaikkannya membalik arah.
 */

/**
 * Biru inti Shortsmith.
 *
 * Diekspor karena dipakai di dua tempat yang harus selalu sewarna: baris kedua
 * judul dashboard, dan partikel di halaman masuk. Menuliskannya dua kali berarti
 * suatu hari salah satunya diubah sendirian.
 */
export const BIRU = "#64CEFB";

export function ShinyText({
  children,
  baseColor = BIRU,
  shineColor = "#ffffff",
  speed = 3,
  spread = 100,
  className = "",
}: {
  children: React.ReactNode;
  /** Warna teks di luar pita kilau. */
  baseColor?: string;
  /** Warna puncak kilaunya. */
  shineColor?: string;
  /** Lama satu sapuan penuh, dalam detik. */
  speed?: number;
  /** Sudut gradiennya, dalam derajat. */
  spread?: number;
  className?: string;
}) {
  return (
    <span
      className={`shiny ${className}`}
      style={
        {
          "--shiny-dasar": baseColor,
          "--shiny-kilau": shineColor,
          "--shiny-lama": `${speed}s`,
          "--shiny-sudut": `${spread}deg`,
        } as React.CSSProperties
      }
    >
      {children}
    </span>
  );
}

export default ShinyText;
