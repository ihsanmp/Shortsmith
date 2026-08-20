"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { motion, useReducedMotion } from "motion/react";

/**
 * Navigasi berbentuk pil dengan indikator yang meluncur mengikuti kursor.
 *
 * ## Kenapa indikatornya satu elemen yang berpindah, bukan latar per item
 *
 * Kalau tiap item punya latarnya sendiri yang menyala saat di-hover, tidak ada
 * yang bergerak — yang terjadi hanya satu kotak padam dan kotak lain menyala.
 * Satu elemen yang berpindah menyatakan hubungan antar item: mata mengikuti
 * benda yang sama berjalan dari "Dashboard" ke "Konsep", dan perpindahan itu
 * yang membuat navigasinya terbaca sebagai satu deret, bukan tombol-tombol
 * terpisah.
 *
 * ## Kenapa lebar ikut dianimasikan
 *
 * "Dashboard" dan "Konsep" tidak sama panjang. Indikator berlebar tetap akan
 * meleset di salah satunya. Menganimasikan lebar bersamaan dengan posisi juga
 * yang menghasilkan efek meregang khas saat pil melintas jauh — pegas untuk x
 * dan lebar tidak pernah tiba bersamaan, dan selisih itulah yang terlihat
 * seperti benda lentur.
 *
 * ## Kenapa `left`/`width`, bukan transform
 *
 * Aturan umum "animasikan transform, jangan layout" berlaku untuk properti yang
 * memicu reflow di seluruh pohon. Di sini yang dianimasikan adalah elemen
 * `position: absolute` di dalam container ber-`contain` — ia tidak punya
 * saudara yang ikut bergeser. `motion` juga menjalankannya di luar siklus React.
 * Menggunakan `scaleX` justru salah: ia akan ikut meregangkan sudut pilnya
 * menjadi lonjong.
 *
 * ## Kenapa keluar dari hover mengembalikannya ke halaman aktif
 *
 * Indikator ini merangkap dua tugas: menandai posisi kursor dan menandai
 * halaman yang sedang dibuka. Kalau ia tertinggal di tempat terakhir kursor
 * lewat, tugas kedua hilang — pengguna kehilangan penanda "saya sedang di mana".
 */

const PEGAS = { type: "spring", stiffness: 380, damping: 34, mass: 0.9 } as const;
/** Lebar mengejar posisi sedikit lebih lambat; selisihnya yang bikin meregang. */
const PEGAS_LEBAR = { type: "spring", stiffness: 300, damping: 30, mass: 1 } as const;
const SEKETIKA = { duration: 0 } as const;

type Sasaran = { kiri: number; lebar: number };

export type ItemNav = {
  label: string;
  href?: string;
  /** Dipakai untuk item yang menjalankan aksi, bukan berpindah halaman. */
  onClick?: () => void;
  /** Pathname yang membuat item ini dianggap aktif. Default: `href`. */
  cocok?: (pathname: string) => boolean;
};

export type AksiNav = { label: string; href: string };

/**
 * `aksi` adalah ajakan utama yang duduk di dalam wadah yang sama tapi DI LUAR
 * jangkauan indikator.
 *
 * Indikator menandai "kamu sedang di sini"; ajakan utama menandai "mulai dari
 * sini". Membiarkan indikator meluncur ke atasnya mencampur dua pernyataan itu
 * — dan tombolnya, yang seharusnya paling menonjol, justru kehilangan warnanya
 * sendiri setiap kali pil putih menutupinya.
 */
export function NavPil({ items, aksi }: { items: ItemNav[]; aksi?: AksiNav }) {
  const pathname = usePathname();
  const kurangiGerak = useReducedMotion();

  const wadahRef = useRef<HTMLDivElement | null>(null);
  const itemRefs = useRef<(HTMLElement | null)[]>([]);
  const [sasaran, setSasaran] = useState<Sasaran | null>(null);
  const [disorot, setDisorot] = useState<number | null>(null);

  const indeksAktif = items.findIndex((it) =>
    it.cocok ? it.cocok(pathname) : it.href === pathname,
  );

  // Indeks yang sedang ditunjuk indikator: hover menang atas halaman aktif,
  // karena hover adalah niat pengguna sekarang dan halaman aktif adalah fakta
  // yang sudah ia ketahui.
  const indeksTampil = disorot ?? (indeksAktif >= 0 ? indeksAktif : null);

  const ukur = useCallback((i: number | null) => {
    const wadah = wadahRef.current;
    if (!wadah || i === null) return null;
    const el = itemRefs.current[i];
    if (!el) return null;
    const w = wadah.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    return { kiri: r.left - w.left, lebar: r.width };
  }, []);

  // Diukur setelah layout, bukan dihitung dari panjang teks. Lebar sebenarnya
  // bergantung pada font yang termuat, dan font web tiba SETELAH render pertama
  // — indikator yang posisinya dihitung sebelum itu akan meleset dan tetap
  // meleset.
  useEffect(() => {
    const perbarui = () => setSasaran(ukur(indeksTampil));
    perbarui();

    const wadah = wadahRef.current;
    if (!wadah) return;

    // ResizeObserver menangkap dua hal sekaligus: jendela yang diubah ukurannya
    // dan font yang baru selesai dimuat lalu mengubah lebar teks.
    const ro = new ResizeObserver(perbarui);
    ro.observe(wadah);
    for (const el of itemRefs.current) if (el) ro.observe(el);
    return () => ro.disconnect();
  }, [indeksTampil, ukur, items.length]);

  return (
    <div
      ref={wadahRef}
      className="navpil"
      onMouseLeave={() => setDisorot(null)}
    >
      {sasaran && (
        <motion.span
          aria-hidden
          className="navpil-indikator"
          initial={false}
          animate={{ left: sasaran.kiri, width: sasaran.lebar, opacity: 1 }}
          transition={
            kurangiGerak
              ? SEKETIKA
              : { left: PEGAS, width: PEGAS_LEBAR, opacity: { duration: 0.15 } }
          }
        />
      )}

      {items.map((it, i) => {
        const aktif = i === indeksAktif;
        const dibawahPil = i === indeksTampil;
        const kelas = `navpil-item${dibawahPil ? " navpil-item-terang" : ""}`;

        const props = {
          ref: (el: HTMLElement | null) => {
            itemRefs.current[i] = el;
          },
          className: kelas,
          onMouseEnter: () => setDisorot(i),
          // Fokus keyboard menggerakkan indikator juga. Tanpa ini, pengguna yang
          // menyusuri nav dengan Tab tidak mendapat penanda apa pun selain
          // cincin fokus bawaan.
          onFocus: () => setDisorot(i),
          onBlur: () => setDisorot(null),
        };

        return it.href ? (
          <a
            key={it.label}
            href={it.href}
            aria-current={aktif ? "page" : undefined}
            {...(props as React.ComponentProps<"a">)}
          >
            {it.label}
          </a>
        ) : (
          <button
            key={it.label}
            type="button"
            onClick={it.onClick}
            {...(props as React.ComponentProps<"button">)}
          >
            {it.label}
          </button>
        );
      })}

      {aksi && (
        <a
          href={aksi.href}
          className="navpil-aksi"
          // Masuk ke tombol ini berarti keluar dari deret item. Tanpa ini
          // indikator tertinggal di item terakhir yang dilewati kursor, dan
          // penanda "kamu sedang di sini" jadi berbohong.
          onMouseEnter={() => setDisorot(null)}
        >
          {aksi.label}
        </a>
      )}
    </div>
  );
}

export default NavPil;
