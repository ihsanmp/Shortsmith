import { ShinyText } from "@/components/ui/shiny-text";
import { sesiSekarang } from "@/lib/akun";

/**
 * Dashboard: hero layar penuh dengan latar video.
 *
 * ## Kenapa teksnya bukan salinan dari spesifikasi
 *
 * Rancangannya diikuti persis — video latar, keterangan di atas, judul raksasa
 * dengan baris kedua berkilau, tombol ajakan berbentuk pil. Yang
 * TIDAK disalin adalah kata-katanya, karena kata-kata itu milik produk lain:
 * "DesignPro", sekolah desain produk, dan angka "8000+ Talented Designers
 * Launched". Memasangnya di sini berarti menaruh nama dan klaim yang bukan
 * milik Shortsmith di halaman pertamanya sendiri.
 *
 * ## Kenapa navigasinya tidak dibuat ulang
 *
 * Spesifikasinya memuat navbar lengkap dengan logo dan pil tautan. Shortsmith
 * sudah punya itu di layout, di setiap halaman: nav pil, slider tema, dan menu
 * profil. Membuat yang kedua khusus untuk halaman ini akan menampilkan dua
 * navigasi bertumpuk.
 */

/**
 * Video latar, disajikan dari project ini sendiri.
 *
 * Aslinya menumpang CloudFront milik orang lain di path `user_38xzZ…` — kalau
 * berkas itu dihapus, latar dashboard ini ikut mati tanpa ada yang bisa
 * dilakukan dari sini.
 *
 * Berkasnya juga dikecilkan lebih dulu: 1924px 7,08 MB menjadi 1600px 0,93 MB.
 * Ia hiasan di balik tirai gelap — resolusi penuh tidak menambah apa pun yang
 * terlihat, sementara 7 MB per kunjungan sangat terasa.
 */
const VIDEO = "/hero-dashboard.mp4";

/**
 * Versi potret untuk layar sempit.
 *
 * Berkas lanskap 1600x894 yang dipaksa `object-fit: cover` ke layar 375x812
 * hanya menyisakan sepotong selebar 375px dari tengah bingkai yang direntangkan
 * setinggi 812px — komposisinya hilang sama sekali dan yang tampak cuma serpihan.
 *
 * Versi ini dipotong 9:16 dari bagian bingkai yang isinya paling kuat, lalu
 * diskalakan ke 720x1280. Karena potongannya sudah seukuran layarnya, `cover`
 * nyaris tidak membuang apa pun.
 */
const VIDEO_POTRET = "/hero-dashboard-potret.mp4";

function Panah() {
  return (
    <svg
      className="hero-panah"
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M5 12h13M13 6l6 6-6 6" />
    </svg>
  );
}

export default async function Dashboard() {
  // Tamu belum punya akun, dan server menolak pembuatan project darinya dengan
  // 403. Tombolnya tidak dihilangkan — hero tanpa ajakan terbaca setengah jadi
  // — melainkan diarahkan ke satu-satunya langkah yang memang terbuka untuknya.
  const sesi = await sesiSekarang();
  const tamu = !sesi || sesi.peran === "tamu";

  return (
    <section className="hero">
      {/*
        Video latar. `muted` bukan pilihan gaya — browser menolak autoplay yang
        bersuara, jadi tanpa itu videonya tidak pernah mulai. `playsInline`
        mencegah iOS membajaknya jadi pemutar layar penuh.

        `aria-hidden` karena isinya hiasan: tidak ada informasi di dalamnya yang
        tidak sudah tertulis sebagai teks di atasnya.
      */}
      <video
        className="hero-video"
        autoPlay
        loop
        muted
        playsInline
        preload="metadata"
        aria-hidden
      >
        {/* Urutannya penting: browser memakai `source` PERTAMA yang media
            query-nya cocok, jadi yang paling sempit harus di atas. Pemilihannya
            terjadi sekali saat muat dan tidak dievaluasi ulang saat jendela
            diubah ukurannya — itu batas dari elemen `video`, bukan kekeliruan
            di sini, dan tidak berpengaruh pada perangkat sungguhan. */}
        <source src={VIDEO_POTRET} media="(max-width: 640px)" type="video/mp4" />
        <source src={VIDEO} type="video/mp4" />
      </video>
      {/* Tirai gelap di atas video. Video bergerak punya bagian terang dan
          gelap yang berganti terus; tanpa tirai, kontras teks berubah-ubah
          sepanjang pemutaran dan ada detik-detik yang tidak terbaca. */}
      <div className="hero-tirai" aria-hidden />

      <div className="hero-isi">
        <div className="hero-atas">
          <p>
            Unggah rekaman panjang sekali, pilih konsep, dan agent di PC-mu yang
            memotong, membingkai, memberi subtitle, lalu merender sisanya.
          </p>
        </div>

        <div className="hero-tengah">
          <p className="hero-mata">
            {tamu ? "Mode tamu — hanya bisa melihat" : "Agent siap menerima antrean"}
          </p>

          <h1 className="hero-judul">
            <span className="hero-judul-putih">Rekaman panjang</span>
            <ShinyText speed={3} spread={100}>
              jadi short.
            </ShinyText>
          </h1>

          <a href={tamu ? "/login?mulai=1" : "/project/new"} className="hero-cta">
            <span>{tamu ? "Get Started" : "Buat short baru"}</span>
            <Panah />
          </a>
        </div>
      </div>
    </section>
  );
}
