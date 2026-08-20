import { count } from "drizzle-orm";

import { db } from "@/db";
import { projects } from "@/db/schema";
import { akunSekarang, sesiSekarang } from "@/lib/akun";
import { TombolKembali } from "@/components/ui/tombol-kembali";

import { TombolKeluar } from "./keluar";

export const dynamic = "force-dynamic";

/**
 * Halaman profil akun.
 *
 * ## Kenapa password ditampilkan sebagai titik-titik
 *
 * Nilainya tidak pernah bisa ditampilkan — yang tersimpan hanya hash-nya, dan
 * itu memang tujuannya. Barisnya tetap ada karena ia menjawab pertanyaan yang
 * berbeda dari "apa passwordku": ia menyatakan bahwa akun ini memang dijaga
 * password, dan memberi tempat yang wajar untuk tombol menggantinya.
 *
 * Jumlah titiknya tetap, tidak mengikuti panjang password sebenarnya. Panjang
 * yang jujur di layar adalah petunjuk gratis bagi siapa pun yang kebetulan
 * melihat.
 *
 * ## Kenapa sesi tanpa akun tetap boleh membuka halaman ini
 *
 * Tamu dan sesi kata sandi bersama tidak punya baris di tabel `users`. Halaman
 * ini menampilkan apa adanya untuk mereka, alih-alih mengalihkan pergi —
 * dialihan tanpa penjelasan terbaca seperti kerusakan.
 */

const SENSOR = "••••••••••";

function Baris({ label, nilai }: { label: string; nilai: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{nilai}</dd>
    </>
  );
}

export default async function Profil() {
  const sesi = await sesiSekarang();
  const akun = await akunSekarang(sesi);

  const [{ n: jumlahProject }] = await db.select({ n: count() }).from(projects);

  const tamu = sesi?.peran === "tamu";

  return (
    <section className="profil-halaman">
      <TombolKembali href="/projects" label="Kembali ke project" className="profil-halaman-kembali-bulat" />

      <h1 className="profil-halaman-judul">
        <span>PROFIL </span>
        <strong>AKUN</strong>
      </h1>

      {/* Foto tautan ke halaman edit. Menekan foto profil untuk menggantinya
          adalah kebiasaan yang sudah terbentuk di mana-mana; membiarkannya mati
          membuat orang mengira fotonya memang tidak bisa diganti. */}
      {akun ? (
        <a
          href="/profile/edit"
          className="profil-halaman-avatar profil-halaman-avatar-tautan"
          aria-label="Ganti foto profil"
        >
          <Foto url={akun.avatarUrl} />
          <span className="profil-halaman-avatar-tirai">
            <svg
              viewBox="0 0 24 24"
              width="20"
              height="20"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M4 8a2 2 0 0 1 2-2h1.5l1-1.6h7L19 6h-1a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" />
              <circle cx="12" cy="12.5" r="3.4" />
            </svg>
          </span>
        </a>
      ) : (
        <div className="profil-halaman-avatar">
          <Foto url={null} />
        </div>
      )}

      <dl className="profil-halaman-kartu">
        <Baris label="Username" nilai={akun?.username ?? (tamu ? "Tamu" : "Pemilik")} />
        <Baris
          label="Email"
          nilai={akun?.email ?? (tamu ? "—" : "Tanpa akun (kata sandi bersama)")}
        />
        <Baris label="Password" nilai={akun ? SENSOR : "—"} />
        <Baris label="Project dibuat" nilai={String(jumlahProject)} />
      </dl>

      <div className="profil-halaman-aksi">
        {akun ? (
          <>
            <a href="/profile/edit" className="profil-halaman-tombol">
              Edit profile
            </a>
            <a href="/profile/akun" className="profil-halaman-tombol">
              Kelola akun
            </a>
          </>
        ) : (
          <>
            <a href="/projects" className="profil-halaman-tombol">
              Semua project
            </a>
            <a href="/login?mulai=1" className="profil-halaman-tombol">
              Masuk dengan akun
            </a>
          </>
        )}
        <TombolKeluar />
      </div>
    </section>
  );
}

/**
 * Avatar bawaan digambar sebagai SVG, bukan berkas.
 *
 * Ia muncul untuk setiap akun yang belum mengunggah foto — yaitu semuanya, di
 * awal. Menjadikannya berkas berarti satu permintaan jaringan tambahan untuk
 * gambar yang isinya tiga bentuk geometri.
 */
function Foto({ url }: { url: string | null }) {
  if (url) {
    // eslint-disable-next-line @next/next/no-img-element -- URL bertanda tangan
    // dari storage, berumur pendek; next/image tidak bisa mengoptimalkannya.
    return <img src={url} alt="" className="profil-halaman-foto" />;
  }
  return (
    <svg viewBox="0 0 128 128" width="100%" height="100%" aria-hidden>
      <rect width="128" height="128" fill="#cbd5e1" />
      <circle cx="64" cy="48" r="24" fill="#f8fafc" />
      <path d="M18 126c4-28 24-46 46-46s42 18 46 46" fill="#f8fafc" />
    </svg>
  );
}
