import { TombolKembali } from "@/components/ui/tombol-kembali";

export const dynamic = "force-dynamic";

/**
 * Pemilih jenis video, sebelum formnya.
 *
 * ## Kenapa dipisah dari formnya
 *
 * Jenis menentukan hal-hal yang muncul di form itu sendiri — rasio, apakah
 * subtitle ditawarkan, apakah lagu wajib. Menaruhnya sebagai satu dropdown di
 * dalam form berarti form itu berubah bentuk di depan mata saat pilihannya
 * diganti, dan pengguna kehilangan apa yang sudah ia isi.
 *
 * ## Apa yang JENISNYA benar-benar tentukan
 *
 * Tiga hal yang memang sudah bisa dikendalikan pipeline: rasio keluaran, durasi
 * target, dan apakah subtitle dibakar. Gaya potongannya sendiri tetap datang
 * dari konsep — jenis tidak mengubah cara agent memilih potongan.
 */

const JENIS = [
  {
    id: "short",
    nama: "Short",
    ringkas: "Tegak 9:16, subtitle menempel",
    isi: "Untuk TikTok, Reels, dan YouTube Shorts. Potongan rapat mengikuti kalimat, subtitle dibakar di gambar, target sekitar satu menit.",
    detail: ["9:16 · 1080×1920", "Subtitle otomatis", "Musik opsional, pelan"],
  },
  {
    id: "cinematic",
    nama: "Cinematic",
    ringkas: "Lanskap 16:9, tanpa subtitle",
    isi: "Untuk potongan bergaya film: rasio lebar, potongan lebih panjang dan bernapas, tanpa teks di gambar supaya bingkainya bersih.",
    detail: ["16:9 · 1920×1080", "Tanpa subtitle", "Musik opsional"],
  },
  {
    id: "amv",
    nama: "AMV anime",
    ringkas: "Potongan cepat mengikuti lagu",
    isi: "Rangkaian klip yang mengikuti lagu, bukan ucapan. Lagunya jadi jalur utama — bukan latar — jadi ia wajib diisi.",
    detail: ["Rasio dari konsep", "Tanpa subtitle", "Lagu WAJIB, keras"],
  },
] as const;

export default function PilihJenis() {
  return (
    <section className="jenis-halaman">
      <TombolKembali href="/" label="Kembali ke dashboard" className="kembali-atas" />

      <div className="badge">Video baru</div>
      <h1 className="title" style={{ fontSize: "2rem" }}>
        Mau bikin apa?
      </h1>
      <p className="hint" style={{ marginBottom: 28 }}>
        Pilihan ini menentukan rasio, panjang, dan apakah subtitle dibakar.
      </p>

      <div className="jenis-grid">
        {JENIS.map((j) => (
          <a key={j.id} href={`/project/new?jenis=${j.id}`} className="jenis-kartu">
            <h2 className="jenis-nama">{j.nama}</h2>
            <p className="jenis-ringkas">{j.ringkas}</p>
            <p className="jenis-isi">{j.isi}</p>
            <ul className="jenis-detail">
              {j.detail.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          </a>
        ))}
      </div>

      {/* Batasnya dinyatakan di tempat orang memilih, bukan setelah hasilnya
          mengecewakan. Jenis mengubah bingkai dan panjang; ia tidak mengubah
          cara agent memutuskan potongan mana yang dipakai. */}
      <p className="jenis-catatan">
        Ketiganya memakai mesin editing yang sama. Yang membedakan adalah rasio,
        subtitle, dan kekerasan lagu — sedangkan <strong>ritme potongannya
        datang dari konsep</strong>, yang diukur dari video contoh. Untuk AMV
        itu berarti: buat konsep dari beberapa AMV yang kamu suka, dan panjang
        shot-nya akan terukur dari sana.
      </p>
    </section>
  );
}
