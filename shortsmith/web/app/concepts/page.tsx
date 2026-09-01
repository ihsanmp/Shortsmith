import { desc } from "drizzle-orm";

import { db } from "@/db";
import { conceptProfiles } from "@/db/schema";
import { HapusKonsep } from "@/components/ui/hapus-konsep";
import { TombolKembali } from "@/components/ui/tombol-kembali";

export const dynamic = "force-dynamic";

type Metrik = { mean?: number; std?: number };
type Profile = { metrik?: Record<string, Metrik>; gaya_bahasa?: string };

export default async function ConceptsPage() {
  const rows = await db
    .select()
    .from(conceptProfiles)
    .orderBy(desc(conceptProfiles.createdAt));

  return (
    <>
      {/* Tombol kembali di barisnya sendiri, di atas judul. Menaruhnya sebaris
          dengan judul akan mendorong judulnya ke kanan dan memutus rata kirinya
          dengan seluruh isi halaman di bawahnya. */}
      <TombolKembali href="/" label="Kembali ke dashboard" className="kembali-atas" />

      <div className="row" style={{ justifyContent: "space-between", marginBottom: 24 }}>
        <div>
          <div className="badge">Pustaka</div>
          <h1 className="title" style={{ fontSize: "2rem" }}>
            Konsep
          </h1>
          <span className="hint">
            Dibuat sekali dari video contoh, dipakai berulang tanpa ubah kode.
          </span>
        </div>
        <a href="/concepts/new" className="pill pill-aksi">
          Konsep baru
        </a>
      </div>

      {rows.length === 0 ? (
        <div className="empty">
          Belum ada konsep.
          <br />
          Konsep dibuat dari 2&ndash;4 video contoh yang sudah jadi.
        </div>
      ) : (
        <div className="konsep-grid">
          {rows.map((c) => {
            const p = (c.profileJson ?? {}) as Profile;
            const durasi = p.metrik?.durasi_total?.mean;
            const cut = p.metrik?.jumlah_cut?.mean;
            const shot = p.metrik?.avg_shot_length;

            return (
              <article key={c.id} className="konsep-kartu">
                <span className="konsep-ikon" aria-hidden>
                  <svg
                    viewBox="0 0 24 24"
                    width="24"
                    height="24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M12 3.5l2.2 4.8 5.3.6-3.9 3.6 1 5.2-4.6-2.6-4.6 2.6 1-5.2L4.5 8.9l5.3-.6z" />
                  </svg>
                </span>

                <h3 className="konsep-nama">
                  {/* Tautan judulnya merentang menutupi seluruh kartu lewat
                      ::after, jadi seluruh kartu bisa ditekan tanpa membungkus
                      tombol Hapus di dalam sebuah <a> — bersarangnya elemen
                      interaktif membuat keyboard dan pembaca layar bingung mana
                      yang sebenarnya ditekan. */}
                  <a href={`/concepts/${c.id}/edit`} className="konsep-tautan">
                    {c.nama}
                  </a>
                </h3>

                <p className="konsep-desc">
                  {c.siap ? (
                    <>
                      {durasi ? `${durasi.toFixed(0)} detik` : "durasi belum terukur"}
                      {" · "}
                      {cut ? `${cut.toFixed(0)} potongan` : "potongan belum terukur"}
                      {shot?.mean
                        ? ` · rata-rata shot ${shot.mean.toFixed(2)} detik`
                        : ""}
                    </>
                  ) : (
                    <>
                      Menunggu agent menganalisis {c.sampleVideoUrls.length} video
                      contoh.
                    </>
                  )}
                </p>

                <div className="konsep-kaki">
                  <div className="konsep-label">
                    {c.isDefault && <span className="tag done">default</span>}
                    {!c.siap && <span className="tag pending">menganalisis</span>}
                    {c.arsip && <span className="tag pending">diarsipkan</span>}
                  </div>
                  <HapusKonsep
                    id={c.id}
                    nama={c.nama}
                    arsip={c.arsip}
                    className="konsep-hapus"
                  />
                </div>
              </article>
            );
          })}
        </div>
      )}
    </>
  );
}
