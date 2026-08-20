import { desc, eq } from "drizzle-orm";
import { redirect } from "next/navigation";

import { db } from "@/db";
import { sessions } from "@/db/schema";
import { akunSekarang, bacaPerangkat, sesiSekarang } from "@/lib/akun";
import { TombolKembali } from "@/components/ui/tombol-kembali";

export const dynamic = "force-dynamic";

/**
 * Kelola akun: perangkat mana saja yang sedang masuk ke akun ini.
 *
 * ## Apa yang halaman ini BISA dan TIDAK BISA
 *
 * Ia mendaftar perangkat, bukan mengendalikannya. Cookie sesi Shortsmith
 * membuktikan dirinya sendiri lewat tanda tangan — memverifikasinya tidak
 * menyentuh database, dan itu yang membuat penjagaannya bisa berjalan di Edge
 * untuk setiap permintaan tanpa ongkos kueri.
 *
 * Harganya dibayar di sini: menghapus baris dari daftar ini tidak akan
 * menendang perangkatnya keluar, karena cookie-nya tetap sah sampai
 * kedaluwarsa sendiri. Membuat "keluarkan perangkat" benar-benar bekerja
 * menuntut setiap permintaan memeriksa database — perubahan yang jauh lebih
 * besar daripada halaman ini.
 *
 * Karena itu tombol "keluarkan" TIDAK disediakan. Tombol yang tidak melakukan
 * apa yang dijanjikan namanya lebih buruk daripada tombol yang tidak ada: ia
 * membuat orang mengira dirinya sudah aman.
 */

function waktu(d: Date) {
  return new Intl.DateTimeFormat("id-ID", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

export default async function KelolaAkun() {
  const sesi = await sesiSekarang();
  const akun = await akunSekarang(sesi);
  if (!akun) redirect("/profile");

  const daftar = await db
    .select({
      id: sessions.id,
      userAgent: sessions.userAgent,
      createdAt: sessions.createdAt,
      lastSeenAt: sessions.lastSeenAt,
    })
    .from(sessions)
    .where(eq(sessions.userId, akun.id))
    .orderBy(desc(sessions.createdAt))
    .limit(50);

  return (
    <section className="profil-halaman profil-halaman-sempit">
      <TombolKembali href="/profile" label="Kembali ke profil" className="profil-halaman-kembali-bulat" />

      <h1 className="profil-halaman-judul">
        <span>KELOLA </span>
        <strong>AKUN</strong>
      </h1>

      <p className="profil-halaman-sub">
        {akun.email} — {daftar.length} perangkat pernah masuk
      </p>

      {daftar.length === 0 ? (
        <div className="empty">Belum ada perangkat tercatat.</div>
      ) : (
        <ul className="perangkat-daftar">
          {daftar.map((d) => {
            const { browser, sistem } = bacaPerangkat(d.userAgent);
            const ini = d.id === sesi?.sesiId;
            return (
              <li key={d.id} className={`perangkat${ini ? " perangkat-ini" : ""}`}>
                <div className="perangkat-ikon" aria-hidden>
                  <svg
                    viewBox="0 0 24 24"
                    width="18"
                    height="18"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <rect x="3" y="4" width="18" height="12" rx="2" />
                    <path d="M8 20h8" />
                  </svg>
                </div>
                <div className="perangkat-teks">
                  <p className="perangkat-nama">
                    {browser} di {sistem}
                    {ini && <span className="perangkat-lencana">perangkat ini</span>}
                  </p>
                  <p className="perangkat-waktu">
                    Masuk {waktu(d.createdAt)} · terakhir aktif {waktu(d.lastSeenAt)}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* Batas halaman ini dinyatakan terbuka. Daftar perangkat tanpa keterangan
          ini mudah dibaca sebagai jaminan kendali yang tidak benar-benar ada. */}
      <p className="profil-halaman-catatan">
        Daftar ini catatan, bukan kendali. Menutup sesi di perangkat lain hanya
        bisa dilakukan dari perangkat itu sendiri lewat tombol Keluar — sesi
        Shortsmith tidak disimpan di server, jadi tidak ada yang bisa dicabut
        dari jarak jauh. Kalau sebuah perangkat hilang, ganti password: sesi
        lama tetap hidup sampai kedaluwarsa, tapi tidak ada yang bisa membuat
        sesi baru.
      </p>
    </section>
  );
}
