import { count } from "drizzle-orm";

import { db } from "@/db";
import { conceptProfiles, projects } from "@/db/schema";
import { TombolKembali } from "@/components/ui/tombol-kembali";

// Tetap dinamis, dan itu keputusan setelah mencoba sebaliknya.
//
// `revalidate` sempat dipasang di sini supaya halamannya disajikan CDN. Ia
// membuat Next menyiapkan halaman ini SAAT BUILD -- dan build lalu gagal total
// dengan ECONNREFUSED ketika databasenya tidak bisa dihubungi.
//
// Artinya deploy jadi bergantung pada database sedang hidup, demi dua angka
// hitungan yang cuma dipajang. Itu menukar ketahanan deploy dengan 250 ms di
// satu halaman yang jarang dibuka; tidak sepadan.
export const dynamic = "force-dynamic";

/**
 * Halaman About.
 *
 * ## Kenapa bentuknya begini
 *
 * Susunannya mengikuti halaman Manifest PlaceRadar: judul berpil bergaris,
 * satu pernyataan besar, pernyataan kedua yang rata kanan, lalu bagian-bagian
 * di bawahnya. Yang TIDAK diikuti adalah isinya — PlaceRadar punya bagian tim,
 * foto anggota, dan ucapan terima kasih. Shortsmith tidak punya tim, jadi
 * tempat itu diisi hal yang memang ada padanya: cara kerjanya, dan batas-batas
 * yang jujur.
 *
 * ## Kenapa angkanya dari database
 *
 * "Sudah dipakai untuk N project" hanya berarti kalau N-nya benar. Angka yang
 * diketik tangan di halaman About adalah angka yang basi sejak hari kedua.
 */

const LANGKAH = [
  {
    n: "01",
    judul: "Unggah rekaman panjang",
    isi: "Satu rekaman suara utuh, plus klip B-roll kalau ada. Bisa juga dibaca langsung dari folder di PC — bahannya tidak perlu menyentuh internet sama sekali.",
  },
  {
    n: "02",
    judul: "Pilih konsep",
    isi: "Konsep adalah gaya editing yang diukur sekali dari beberapa video contoh: panjang target, ritme potongan, cara membuka. Sekali dibuat, dipakai berulang tanpa mengubah kode.",
  },
  {
    n: "03",
    judul: "Agent bekerja di PC-mu",
    isi: "Transkrip, cari batas kalimat di jeda hening, pilih potongan, kunci bingkai ke wajah yang sedang bicara, tempel subtitle, render. Semuanya di mesin sendiri.",
  },
  {
    n: "04",
    judul: "Short-nya siap",
    isi: "Rasio 9:16, tanpa bilah hitam, subtitle sudah menempel. Tinggal unduh.",
  },
];

const JUJUR = [
  {
    judul: "Agent harus hidup di PC-mu",
    isi: "Website ini cuma papan kendali. Yang memotong dan merender adalah program yang berjalan di komputermu sendiri — kalau ia mati, antrean berhenti sampai ia dinyalakan lagi.",
  },
  {
    judul: "Editornya menebak, bukan tahu",
    isi: "Pemilihan potongan dan pembingkaian wajah berdasarkan ukuran dan aturan, bukan pemahaman. Hasilnya konsisten, tapi bukan pengganti mata yang menonton ulang sebelum diunggah.",
  },
  {
    judul: "Satu akun, banyak perangkat",
    isi: "Sesi berlaku dua minggu di tiap perangkat yang dipakai masuk. Halaman Kelola akun mendaftar perangkatnya, tapi tidak bisa mengusir yang lain dari jarak jauh.",
  },
];

export default async function About() {
  const [{ n: jumlahProject }] = await db.select({ n: count() }).from(projects);
  const [{ n: jumlahKonsep }] = await db.select({ n: count() }).from(conceptProfiles);

  return (
    <section className="tentang">
      <TombolKembali href="/" label="Kembali ke dashboard" className="kembali-atas" />

      <header className="tentang-kepala">
        <div className="tentang-pil-baris">
          <span className="tentang-pil">Apa</span>
          <span className="tentang-amp">&amp;</span>
          <span className="tentang-pil">Kenapa</span>
        </div>
        <h1 className="tentang-judul">SHORTSMITH?</h1>
      </header>

      <div className="tentang-blok">
        <p className="tentang-pernyataan">
          Shortsmith mengubah <em>rekaman panjang</em> jadi short, dikerjakan
          oleh agent yang berjalan di komputermu sendiri.
        </p>
        <p className="tentang-dukungan">
          Bukan layanan yang mengunggah rekamanmu ke server orang lain untuk
          diproses. Bahan mentahnya boleh tidak pernah meninggalkan disk — yang
          naik ke internet cuma hasil akhirnya, dan hanya kalau kamu memintanya.
        </p>
      </div>

      <div className="tentang-blok tentang-blok-kanan">
        <p className="tentang-pernyataan">
          Gaya editing diukur sekali,
          <br />
          lalu dipakai berulang.
        </p>
        <p className="tentang-dukungan">
          Itulah yang disebut konsep di sini. Ia diekstrak dari video contoh yang
          kamu anggap bagus — target durasi, ritme potongan, cara membuka — lalu
          setiap short berikutnya mengikuti ukuran yang sama. Ganti gayanya
          berarti membuat konsep baru, bukan menyunting kode.
        </p>
      </div>

      <div className="tentang-angka">
        <div>
          <strong>{jumlahProject}</strong>
          <span>project dibuat</span>
        </div>
        <div>
          <strong>{jumlahKonsep}</strong>
          <span>konsep tersimpan</span>
        </div>
        <div>
          <strong>9:16</strong>
          <span>rasio keluaran</span>
        </div>
      </div>

      <h2 className="tentang-sub">Cara kerjanya</h2>
      <ol className="tentang-langkah">
        {LANGKAH.map((l) => (
          <li key={l.n}>
            <span className="tentang-nomor">{l.n}</span>
            <div>
              <h3>{l.judul}</h3>
              <p>{l.isi}</p>
            </div>
          </li>
        ))}
      </ol>

      {/* Bagian ini sengaja ada. Halaman About yang isinya hanya kelebihan
          membuat batas-batasnya baru ketahuan saat seseorang tertabrak olehnya —
          dan saat itu ia terasa seperti kerusakan, bukan rancangan. */}
      <h2 className="tentang-sub">Yang perlu diketahui</h2>
      <ul className="tentang-jujur">
        {JUJUR.map((j) => (
          <li key={j.judul}>
            <h3>{j.judul}</h3>
            <p>{j.isi}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
