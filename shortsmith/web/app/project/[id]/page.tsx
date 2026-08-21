"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Konfirmasi } from "@/components/ui/konfirmasi";
import { ProgressBar } from "@/components/ui/progress-bar";
import { TombolKembali } from "@/components/ui/tombol-kembali";

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
        if (!res.ok) throw new Error((await res.json()).error ?? "Gagal memuat");
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
              Posisi antrean: <strong>{job.posisiAntrean + 1}</strong>. Perkiraan mulai
              diproses sekitar <strong>{job.estimasiMenit} menit</strong> lagi — satu PC
              hanya bisa memproses satu job pada satu waktu.
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

      {output && (
        <div className="panel stack" style={{ marginBottom: 20 }}>
          <h2 className="section">Hasil</h2>
          <video src={output.url} controls playsInline />
          <div className="row">
            <a className="pill pill-aksi" href={output.url} download={output.namaFile}>
              Unduh
            </a>
            {output.ukuranBytes && (
              <span className="hint">{(output.ukuranBytes / 1e6).toFixed(1)} MB</span>
            )}
          </div>
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
