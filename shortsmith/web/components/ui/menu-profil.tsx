"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

/**
 * Menu profil: avatar + panah di navbar, membuka dropdown berisi daftar menu.
 *
 * ## Kenapa isinya bukan nama, email, dan foto
 *
 * Shortsmith tidak punya model pengguna. Login-nya satu kata sandi bersama, dan
 * cookie sesinya hanya berisi waktu kedaluwarsa plus tanda tangan — tidak ada
 * username, email, atau nama di mana pun di sistem ini. Mengisi baris-baris itu
 * berarti mengarang, dan panel profil berisi karangan lebih buruk daripada
 * tidak ada: ia terlihat persis seperti data sungguhan.
 *
 * Yang ditampilkan karena itu hanya yang memang diketahui sistem: berapa
 * project dan konsep yang ada, dan kapan sesinya berakhir.
 *
 * ## Kenapa datanya diambil saat dibuka, bukan saat halaman dimuat
 *
 * Menu ini jarang dibuka. Mengambilnya saat mount berarti dua kueri hitung ke
 * database di SETIAP kunjungan halaman, untuk angka yang kebanyakan waktu tidak
 * pernah dilihat.
 *
 * ## Kenapa item-itemnya muncul bergiliran
 *
 * Panel yang seluruh isinya muncul serentak terbaca sebagai satu blok yang
 * ditempelkan. Jeda 22ms antar item membuat matanya menyusuri daftar dari atas
 * ke bawah — urutan yang sama dengan cara daftar itu dibaca. Jedanya sengaja
 * pendek: di atas ~40ms per item, menu mulai terasa lambat merespons.
 */

const PANEL = { type: "spring", stiffness: 420, damping: 34, mass: 0.85 } as const;
const JEDA_ITEM = 0.022;

/** Avatar bawaan, digambar sebagai SVG — tidak ada berkas yang perlu dimuat. */
const AVATAR = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(
  `<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
    <rect width="128" height="128" fill="#cbd5e1"/>
    <circle cx="64" cy="48" r="24" fill="#f8fafc"/>
    <path d="M18 126c4-28 24-46 46-46s42 18 46 46" fill="#f8fafc"/>
  </svg>`,
)}`;

type Sesi = {
  berakhir: number | null;
  peran: "pemilik" | "tamu";
  email: string | null;
  username: string | null;
  avatarUrl: string | null;
  jumlahProject: number;
  jumlahKonsep: number;
};

function tanggal(ms: number | null): string {
  if (ms === null) return "—";
  return new Date(ms).toLocaleDateString("id-ID", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

type IkonProps = { d: string };
function Ikon({ d }: IkonProps) {
  return (
    <svg
      className="profil-ikon"
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d={d} />
    </svg>
  );
}

const JALUR = {
  project: "M4 7a2 2 0 0 1 2-2h3.6l1.6 2H18a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z",
  konsep: "M12 3.5l2.2 4.8 5.3.6-3.9 3.6 1 5.2-4.6-2.6-4.6 2.6 1-5.2L4.5 8.9l5.3-.6z",
  keluar: "M15 17l5-5-5-5M20 12H9M13 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h7",
} as const;

type Item = {
  label: string;
  ikon: string;
  href?: string;
  onClick?: () => void;
  bahaya?: boolean;
  /** Pemisah di ATAS item ini, memisahkannya dari kelompok sebelumnya. */
  pisah?: boolean;
};

export function MenuProfil({
  awalUsername = null,
  awalAvatarUrl = null,
}: {
  /** Disiapkan server supaya avatar di navbar benar sejak halaman muncul. */
  awalUsername?: string | null;
  awalAvatarUrl?: string | null;
} = {}) {
  const [terbuka, setTerbuka] = useState(false);
  const [sesi, setSesi] = useState<Sesi | null>(null);
  const [gagal, setGagal] = useState(false);
  const kurangiGerak = useReducedMotion();

  const wadahRef = useRef<HTMLDivElement | null>(null);
  const pemicuRef = useRef<HTMLButtonElement | null>(null);

  const muat = useCallback(async () => {
    try {
      const r = await fetch("/api/sesi");
      if (!r.ok) throw new Error(String(r.status));
      setSesi((await r.json()) as Sesi);
      setGagal(false);
    } catch {
      // Kegagalan di sini tidak menutup menunya. Angkanya hilang, tapi seluruh
      // itemnya tetap bisa ditekan — termasuk Keluar, yang justru paling
      // dibutuhkan saat ada yang tidak beres.
      setGagal(true);
    }
  }, []);

  function alihkan() {
    const baru = !terbuka;
    setTerbuka(baru);
    // Diambil ulang SETIAP kali dibuka, bukan sekali lalu disimpan.
    //
    // Nama dan foto bisa berubah dari halaman edit profil, dan menu ini hidup
    // di layout — ia tidak pernah dilepas saat berpindah halaman, jadi nilai
    // yang disimpan sekali akan bertahan basi sampai seluruh tab dimuat ulang.
    // Satu permintaan kecil saat menu dibuka jauh lebih murah daripada
    // menampilkan nama lama kepada orang yang baru saja menggantinya.
    if (baru) void muat();
  }

  useEffect(() => {
    if (!terbuka) return;

    function diLuar(e: MouseEvent) {
      if (!wadahRef.current?.contains(e.target as Node)) setTerbuka(false);
    }
    function tombol(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      setTerbuka(false);
      // Fokus dikembalikan ke pemicunya. Tanpa ini fokus tertinggal di elemen
      // yang baru saja hilang, dan pengguna keyboard terlempar ke awal halaman.
      pemicuRef.current?.focus();
    }

    document.addEventListener("mousedown", diLuar);
    document.addEventListener("keydown", tombol);
    return () => {
      document.removeEventListener("mousedown", diLuar);
      document.removeEventListener("keydown", tombol);
    };
  }, [terbuka]);

  const tamu = sesi?.peran === "tamu";

  const items: Item[] = [
    // Dashboard dan "Short baru" sengaja TIDAK di sini. Keduanya sudah punya
    // pintunya sendiri yang selalu terlihat — nav pil dan tombol di halaman
    // project — dan menu yang mengulang isi navbar memaksa orang membaca dua
    // daftar untuk menemukan satu hal.
    //
    // Untuk tamu keduanya dilepas: server mengalihkannya pergi dari halaman itu,
    // jadi menawarkannya di sini cuma menghasilkan klik yang membatalkan diri
    // sendiri.
    ...(tamu
      ? []
      : [
          { label: "Project", ikon: JALUR.project, href: "/projects" },
          { label: "Konsep", ikon: JALUR.konsep, href: "/concepts" },
        ]),
    {
      label: "Keluar",
      ikon: JALUR.keluar,
      bahaya: true,
      // Keluar dipisahkan dari navigasi biasa. Ia satu-satunya item yang
      // membuang keadaan, dan menempelkannya langsung di bawah "Short baru"
      // membuatnya mudah tertekan saat tangan meleset satu baris.
      pisah: true,
      onClick: async () => {
        await fetch("/api/login", { method: "DELETE" });
        // Muat ulang penuh, bukan navigasi klien: seluruh cache halaman harus
        // ikut hilang bersama sesinya.
        window.location.href = "/login";
      },
    },
  ];

  // Username di atas, email di bawahnya. Nama yang dipilih sendiri lebih cepat
  // dikenali pemiliknya daripada alamat email — dan emailnya tetap ada persis
  // di bawahnya untuk menjawab "akun yang mana", pertanyaan yang muncul begitu
  // ada lebih dari satu.
  const judul = sesi?.username ?? awalUsername ?? (tamu ? "Tamu" : "Pemilik");

  const angka = sesi
    ? (sesi.email ?? `${sesi.jumlahProject} project · ${sesi.jumlahKonsep} konsep`)
    : gagal
      ? "gagal memuat"
      : "memuat…";

  return (
    <div className="profil" ref={wadahRef}>
      <button
        ref={pemicuRef}
        type="button"
        className={`profil-pemicu${terbuka ? " profil-pemicu-aktif" : ""}`}
        aria-haspopup="menu"
        aria-expanded={terbuka}
        aria-label={terbuka ? "Tutup menu profil" : "Buka menu profil"}
        onClick={alihkan}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- URL bertanda
            tangan berumur pendek, atau data URI; keduanya tidak bisa
            dioptimalkan next/image. */}
        <img
          src={sesi?.avatarUrl || awalAvatarUrl || AVATAR}
          alt=""
          className="profil-avatar"
        />
        <svg
          className={`profil-panah${terbuka ? " profil-panah-naik" : ""}`}
          viewBox="0 0 24 24"
          width="15"
          height="15"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      <AnimatePresence>
        {terbuka && (
          <motion.div
            className="profil-panel"
            role="menu"
            aria-label="Menu profil"
            initial={kurangiGerak ? false : { opacity: 0, y: -8, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={
              kurangiGerak
                ? { opacity: 0 }
                : { opacity: 0, y: -6, scale: 0.97, transition: { duration: 0.12 } }
            }
            transition={PANEL}
            // Titik jangkar di kanan atas: panel tumbuh DARI pemicunya, bukan
            // dari tengah dirinya sendiri.
            style={{ transformOrigin: "top right" }}
          >
            {/* Kepalanya tautan, bukan keterangan pasif: menekan identitas untuk
                membuka halaman akun adalah pola yang sudah dikenal, dan tanpa
                itu satu-satunya jalan ke halaman profil adalah menghafal
                URL-nya. */}
            <div className="profil-kepala">
              <a href="/profile" className="profil-kepala-tautan" role="menuitem">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={sesi?.avatarUrl || awalAvatarUrl || AVATAR}
                  alt=""
                  className="profil-avatar-besar"
                />
                <span className="profil-kepala-teks">
                  <span className="profil-judul">{judul}</span>
                  <span className="profil-sub">{angka}</span>
                </span>
              </a>
            </div>

            <div className="profil-pisah" role="separator" />

            <ul className="profil-daftar">
              {items.map((it, i) => (
                <motion.li
                  key={it.label}
                  className={it.pisah ? "profil-li-pisah" : undefined}
                  initial={kurangiGerak ? false : { opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * JEDA_ITEM, duration: 0.18 }}
                >
                  {it.href ? (
                    <a href={it.href} className="profil-item" role="menuitem">
                      <Ikon d={it.ikon} />
                      <span>{it.label}</span>
                    </a>
                  ) : (
                    <button
                      type="button"
                      role="menuitem"
                      onClick={it.onClick}
                      className={`profil-item${it.bahaya ? " profil-item-bahaya" : ""}`}
                    >
                      <Ikon d={it.ikon} />
                      <span>{it.label}</span>
                    </button>
                  )}
                </motion.li>
              ))}
            </ul>

            <div className="profil-pisah" role="separator" />

            {/* Mode tamu dinyatakan terang-terangan. Tanpa ini, tombol yang
                ditekan lalu gagal dengan 403 terbaca sebagai aplikasi rusak,
                bukan sebagai batas yang memang disengaja. */}
            {sesi?.peran === "tamu" && (
              <p className="profil-kaki profil-kaki-tamu">Mode tamu — hanya bisa melihat</p>
            )}

            <p className="profil-kaki">Sesi berakhir {tanggal(sesi?.berakhir ?? null)}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default MenuProfil;
