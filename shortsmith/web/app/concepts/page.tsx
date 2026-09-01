import { and, desc, eq, inArray } from "drizzle-orm";

import { db } from "@/db";
import { conceptProfiles, jobs } from "@/db/schema";
import { HapusKonsep } from "@/components/ui/hapus-konsep";
import { Progress } from "@/components/ui/progress";
import { TombolKembali } from "@/components/ui/tombol-kembali";

export const dynamic = "force-dynamic";

type Metrik = { mean?: number; std?: number };
type Profile = { metrik?: Record<string, Metrik>; gaya_bahasa?: string };

export default async function ConceptsPage() {
  const rows = await db
    .select()
    .from(conceptProfiles)
    .orderBy(desc(conceptProfiles.createdAt));

  // Kemajuan analisis diambil dari job-nya, bukan ditebak.
  //
  // Agent memang melaporkan angka sebenarnya di sepanjang jalan — 10-60 saat
  // mengunduh contoh, 65 saat membaca gaya, 95 saat mengirim profil. Sebelum
  // ini angka itu tidak pernah sampai ke halaman ini, dan yang terlihat cuma
  // lencana "menganalisis" yang diam selama beberapa menit: tidak ada bedanya
  // antara sedang berjalan dan tersangkut.
  //
  // Ditanyakan HANYA untuk konsep yang belum siap. Konsep yang sudah selesai
  // tidak punya kemajuan untuk ditampilkan, dan menariknya untuk semua baris
  // berarti membaca job untuk seluruh pustaka setiap kali halaman dibuka.
  const belum = rows.filter((r) => !r.siap).map((r) => r.id);
  const kemajuan = new Map<string, { progress: number; tahap: string }>();
  if (belum.length) {
    const jr = await db
      .select({
        conceptId: jobs.conceptId,
        progress: jobs.progress,
        tahap: jobs.tahap,
        createdAt: jobs.createdAt,
      })
      .from(jobs)
      .where(and(eq(jobs.tipe, "profile_extraction"), inArray(jobs.conceptId, belum)))
      .orderBy(desc(jobs.createdAt));
    // Yang TERBARU per konsep yang menang: job yang diulang melahirkan baris
    // baru, dan yang lama berhenti di angka tempat ia gagal.
    for (const j of jr) {
      if (j.conceptId && !kemajuan.has(j.conceptId)) {
        kemajuan.set(j.conceptId, { progress: j.progress, tahap: j.tahap });
      }
    }
  }

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

                {/* Bilah hanya untuk konsep yang MASIH dianalisis. Bilah penuh
                    pada konsep yang sudah selesai tidak mengabarkan apa pun,
                    dan cuma menambah satu garis di tiap kartu. */}
                {!c.siap && (
                  <Progress value={kemajuan.get(c.id)?.progress ?? 0} type="success" />
                )}

                <div className="konsep-kaki">
                  <div className="konsep-label">
                    {c.isDefault && <span className="tag done">default</span>}
                    {!c.siap && (
                      <span className="tag pending">
                        {kemajuan.get(c.id)?.tahap || "menganalisis"}
                      </span>
                    )}
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
