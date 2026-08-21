import { desc, eq, inArray } from "drizzle-orm";

import { db } from "@/db";
import { conceptProfiles, jobs, projects } from "@/db/schema";
import { TombolKembali } from "@/components/ui/tombol-kembali";

export const dynamic = "force-dynamic";

/**
 * Daftar seluruh project.
 *
 * Sebelumnya daftar ini menumpang di beranda, di bawah penjelasan cara kerja.
 * Dipisahkan karena keduanya melayani saat yang berbeda: penjelasan dibaca
 * sekali saat baru mengenal, daftar dibuka tiap hari. Menumpuknya berarti
 * pekerjaan harian selalu berada di bawah bacaan yang sudah selesai dibaca.
 */
const BATAS = 60;

function waktu(d: Date) {
  return new Intl.DateTimeFormat("id-ID", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

export default async function DaftarProject() {
  const daftar = await db
    .select({
      id: projects.id,
      judul: projects.judul,
      status: projects.status,
      createdAt: projects.createdAt,
      conceptNama: conceptProfiles.nama,
    })
    .from(projects)
    .leftJoin(conceptProfiles, eq(projects.conceptId, conceptProfiles.id))
    .orderBy(desc(projects.createdAt))
    .limit(BATAS);

  // Progres diambil TERPISAH, bukan lewat join.
  //
  // Satu project bisa punya lebih dari satu job render — job yang gagal
  // diunggah pernah dijalankan ulang. Dengan join, tiap job tambahan
  // menggandakan barisnya dan project yang sama muncul dua kali di daftar,
  // sementara `limit(20)` diam-diam memotong project lain untuk memberi
  // tempat. Dua query membuat itu tidak mungkin terjadi.
  const progresPer = new Map<string, { progress: number; tahap: string }>();
  if (daftar.length > 0) {
    const barisJob = await db
      .select({
        projectId: jobs.projectId,
        progress: jobs.progress,
        tahap: jobs.tahap,
        createdAt: jobs.createdAt,
      })
      .from(jobs)
      .where(inArray(jobs.projectId, daftar.map((d) => d.id)))
      .orderBy(desc(jobs.createdAt));

    // Diurutkan terbaru lebih dulu, jadi yang pertama masuk adalah job terakhir
    // — dan itulah yang mewakili keadaan project sekarang.
    for (const j of barisJob) {
      if (j.projectId && !progresPer.has(j.projectId)) {
        progresPer.set(j.projectId, { progress: j.progress, tahap: j.tahap });
      }
    }
  }

  const rows = daftar.map((d) => ({
    ...d,
    progress: progresPer.get(d.id)?.progress ?? 0,
    tahap: progresPer.get(d.id)?.tahap ?? "",
  }));

  return (
    <>
      <TombolKembali href="/" label="Kembali ke dashboard" className="kembali-atas" />

      <div className="row" style={{ justifyContent: "space-between", marginBottom: 24 }}>
        <div>
          <div className="badge">Project</div>
          <h1 className="title" style={{ fontSize: "2rem" }}>
            Semua project
          </h1>
          <span className="hint">{rows.length} project</span>
        </div>
        <a href="/video/baru" className="pill pill-aksi">
          Buat short baru
        </a>
      </div>

      {rows.length === 0 ? (
        <div className="empty">
          Belum ada project.
          <br />
          Buat konsep dulu di <a href="/concepts" style={{ textDecoration: "underline" }}>halaman Konsep</a>,
          lalu unggah rekaman pertamamu.
        </div>
      ) : (
        <div className="kartu-grid">
          {rows.map((p, i) => {
            // Status menentukan angka yang jujur untuk bilahnya. Job yang
            // selesai selalu 100 meski heartbeat terakhirnya berhenti di 92;
            // yang gagal ditampilkan apa adanya, karena seberapa jauh ia
            // sempat berjalan justru informasi yang berguna saat menelusuri.
            const persen =
              p.status === "done" ? 100 : Math.max(0, Math.min(100, p.progress ?? 0));

            return (
              <a
                key={p.id}
                href={`/project/${p.id}`}
                className={`kartu kartu-${i % 4}`}
              >
                <div className="kartu-atas">
                  <span className="kartu-tanggal">{waktu(p.createdAt)}</span>
                </div>

                <div className="kartu-tengah">
                  <h3 className="kartu-judul">{p.judul}</h3>
                  <p className="kartu-konsep">{p.conceptNama ?? "konsep terhapus"}</p>
                </div>

                <div className="kartu-progress">
                  <div className="kartu-progress-atas">
                    <span>{p.status === "processing" ? p.tahap || "Memproses" : "Progres"}</span>
                    <span className="kartu-persen">{persen}%</span>
                  </div>
                  <div className="kartu-bar">
                    <div style={{ width: `${persen}%` }} />
                  </div>
                </div>
              </a>
            );
          })}
        </div>
      )}
    </>
  );
}
