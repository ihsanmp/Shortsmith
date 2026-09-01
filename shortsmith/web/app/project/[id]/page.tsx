"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Keterangan } from "@/components/ui/keterangan";
import { Konfirmasi } from "@/components/ui/konfirmasi";
import { ProgressBar } from "@/components/ui/progress-bar";
import { TombolKembali } from "@/components/ui/tombol-kembali";
import { galatDari } from "@/lib/galat";

type Status = "pending" | "processing" | "done" | "failed";

type Data = {
  project: { judul: string; brief: string; status: Status; conceptNama: string | null };
  job: {
    id: string;
    status: Status;
    progress: number;
    tahap: string;
    errorMessage: string | null;
    retryCount: number;
    posisiAntrean: number;
    estimasiMenit: number;
  } | null;
  output: { url: string; namaFile: string; ukuranBytes: number | null } | null;
  /**
   * Semua hasil project ini. Saat topik dikosongkan, satu rekaman panjang
   * dipecah jadi beberapa klip dari bagian yang berbeda.
   *
   * Opsional supaya halaman ini tetap jalan terhadap respons lama yang belum
   * memuatnya -- yang terjadi kalau halaman dimuat dari cache sementara server
   * sudah diperbarui, atau sebaliknya.
   */
  semuaOutput?: {
    url: string;
    namaFile: string;
    ukuranBytes: number | null;
    durasi: number | null;
    keterangan: string | null;
  }[];
};

export default function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [data, setData] = useState<Data | null>(null);
  const [hapusBusy, setHapusBusy] = useState(false);
  const [tanyaHapus, setTanyaHapus] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      try {
        const res = await fetch(`/api/projects/${id}`, { cache: "no-store" });
        if (!res.ok) throw new Error(await galatDari(res, "Gagal memuat"));
        const d: Data = await res.json();
        if (!alive) return;
        setData(d);

        // Berhenti polling begitu job mencapai keadaan akhir.
        const selesai = d.project.status === "done" || d.project.status === "failed";
        if (!selesai) timer = setTimeout(poll, 4000);
      } catch (err) {
        if (alive) setError((err as Error).message);
      }
    }

    poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [id]);

  // Selama render berjalan, tempatnya bukan di sini.
  //
  // `replace`, bukan `push`: halaman ini dan halaman proses tidak boleh saling
  // menumpuk di riwayat, kalau tidak menekan Back akan memantul di antara
  // keduanya selama render belum selesai.
  useEffect(() => {
    if (data?.job?.status === "processing") {
      router.replace(`/project/${id}/proses`);
    }
  }, [data?.job?.status, id, router]);

  if (error) return <div className="notice err">{error}</div>;
  if (!data) return <div className="empty">Memuat...</div>;

  const { project, job, output } = data;
  // Jatuh kembali ke `output` tunggal kalau daftar belum ada.
  //
  // Tipenya dinyatakan eksplisit, bukan disimpulkan dari gabungan dua bentuk:
  // `output` tidak punya `durasi`, dan gabungan keduanya membuat kompilator
  // menganggap field itu tidak ada di salah satu cabang.
  type Klip = {
    url: string;
    namaFile: string;
    ukuranBytes: number | null;
    durasi?: number | null;
    keterangan?: string | null;
  };
  const klip: Klip[] = data.semuaOutput?.length
    ? data.semuaOutput
    : output
      ? [output]
      : [];

  async function hapus() {
    setHapusBusy(true);
    try {
      const res = await fetch(`/api/projects/${id}`, { method: "DELETE" });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail ?? d.error ?? "Gagal menghapus");
      window.location.href = "/";
    } catch (err) {
      setTanyaHapus(false);
      setHapusBusy(false);
      setError((err as Error).message);
    }
  }

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 24 }}>
        <div>
          <div className="badge">Project</div>
          <h1 className="title" style={{ fontSize: "2rem" }}>
            {project.judul}
          </h1>
          <span className="hint">Konsep: {project.conceptNama ?? "-"}</span>
        </div>
      </div>

      {job && job.status === "pending" && (
        <div className="notice info" style={{ marginBottom: 20 }}>
          {job.posisiAntrean === 0 ? (
            <>Menunggu agent mengambil job ini. Pastikan agent sedang berjalan di PC lokal.</>
          ) : (
            <>
              Ada <strong>{job.posisiAntrean}</strong> job di depan job ini — satu PC
              hanya bisa memproses satu job pada satu waktu, jadi yang ini menunggu
              giliran. <strong>Agent-nya tidak bermasalah.</strong>
              {/* Rentang, bukan satu angka.
                  
                  Sebelumnya di sini tertulis perkiraan menit yang dihitung dari
                  satu angka tetap per job. Sejak topik yang dikosongkan
                  menghasilkan beberapa klip, lama satu job berkisar dari
                  sepuluh menit sampai dua puluh lima — jadi angka tunggal
                  berapa pun akan meleset untuk separuh kasusnya. Menyebut
                  rentang yang benar lebih berguna daripada satu angka yang
                  terlihat pasti tapi salah. */}
              <br />
              Satu job biasanya 10&ndash;25 menit, tergantung panjang rekaman dan
              berapa klip yang dihasilkan.
            </>
          )}
          {job.retryCount > 0 && (
            <>
              <br />
              Percobaan ke-{job.retryCount + 1} dari 3.
            </>
          )}
        </div>
      )}


      {job && job.status === "failed" && (
        <div className="notice err" style={{ marginBottom: 20 }}>
          <strong>Job gagal permanen setelah {job.retryCount} percobaan.</strong>
          <br />
          {job.errorMessage ?? "Tidak ada pesan error."}
        </div>
      )}

      {klip.length > 0 && (
        <div className="panel stack" style={{ marginBottom: 20 }}>
          <h2 className="section">
            {klip.length > 1 ? `${klip.length} klip` : "Hasil"}
          </h2>
          {klip.length > 1 && (
            <p className="hint">
              Topiknya dikosongkan, jadi rekaman ini dipecah jadi beberapa klip
              dari bagian yang berbeda.
            </p>
          )}
          {klip.map((k, i) => (
            <div key={k.url} className="stack">
              {/* Nomor hanya muncul kalau memang ada lebih dari satu. Menomori
                  satu-satunya klip menyiratkan ada klip lain yang hilang. */}
              {klip.length > 1 && (
                <p className="hint mono" style={{ marginBottom: 0 }}>
                  Klip {i + 1}
                  {k.durasi ? ` — ${Math.round(k.durasi)} detik` : ""}
                </p>
              )}
              <video src={k.url} controls playsInline />
              <div className="row">
                <a className="pill pill-aksi" href={k.url} download={k.namaFile}>
                  Unduh
                </a>
                {k.ukuranBytes && (
                  <span className="hint">{(k.ukuranBytes / 1e6).toFixed(1)} MB</span>
                )}
              </div>
              {/* Keterangan unggahan ditaruh DI BAWAH videonya, bukan di panel
                  terpisah: keduanya dipakai bersamaan saat mengunggah, dan
                  memisahkannya berarti menyalin sambil menggulir bolak-balik.
                  Klip yang keteranganya gagal ditulis tidak menampilkan apa
                  pun — tidak ada yang perlu dijelaskan tentang ketiadaannya. */}
              {k.keterangan && <Keterangan teks={k.keterangan} />}
            </div>
          ))}
        </div>
      )}

      {project.brief && (
        <div className="panel">
          <h2 className="section">Brief</h2>
          <p style={{ fontSize: "0.9rem", color: "var(--ink-3)", marginTop: 8 }}>
            {project.brief}
          </p>
        </div>
      )}

      <div className="row" style={{ marginTop: 28, justifyContent: "space-between" }}>
        {/* Tujuannya `/projects`, bukan `/` — daftar project sudah pindah ke
            halaman sendiri, dan tautan lama ini mendarat di dashboard. */}
        <TombolKembali href="/projects" label="Kembali ke project" />
        {/* Ditaruh jauh dari tombol Unduh dan diberi warna peringatan.
            Penghapusannya permanen, jadi jaraknya dari tombol yang sering
            diklik adalah bagian dari rancangannya. */}
        <button
          className="btn ghost"
          type="button"
          disabled={hapusBusy}
          style={{ borderColor: "var(--err)", color: "var(--err)" }}
          onClick={() => setTanyaHapus(true)}
        >
          Hapus project
        </button>
      </div>

      <Konfirmasi
        terbuka={tanyaHapus}
        judul="Hapus project ini?"
        pesan="Video hasil dan video mentahnya akan dihapus dari storage berikut seluruh versinya. Tindakan ini tidak bisa dibatalkan."
        labelYa="Hapus"
        busy={hapusBusy}
        onYa={hapus}
        onBatal={() => setTanyaHapus(false)}
      />
    </>
  );
}
