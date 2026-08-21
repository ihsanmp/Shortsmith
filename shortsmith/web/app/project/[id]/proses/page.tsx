"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { PemuatAI } from "@/components/ui/pemuat-ai";
import { ProgressBar } from "@/components/ui/progress-bar";
import { TombolKembali } from "@/components/ui/tombol-kembali";

/**
 * Halaman khusus selama render berjalan.
 *
 * ## Kenapa halamannya sendiri
 *
 * Render makan menit, bukan detik. Menampilkannya sebagai satu kotak kecil di
 * antara tombol Unduh dan Hapus membuat halaman project terlihat setengah jadi
 * selama itu — ada tempat untuk hasil yang belum ada, dan tindakan yang belum
 * boleh dilakukan. Halaman terpisah hanya berisi satu hal, dan hal itu memang
 * satu-satunya yang sedang terjadi.
 *
 * ## Kenapa ia mengalihkan sendiri saat selesai
 *
 * Yang menunggu di sini menunggu hasilnya, bukan menunggu izin untuk pindah.
 * Begitu status meninggalkan `processing`, halaman project sudah punya sesuatu
 * untuk ditampilkan — pemutar videonya, atau pesan gagalnya.
 */

type Status = "pending" | "processing" | "done" | "failed";

type Data = {
  project: { judul: string; status: Status };
  job: { status: Status; progress: number; tahap: string } | null;
};

export default function HalamanProses({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [data, setData] = useState<Data | null>(null);
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

        // `replace`, bukan `push`: halaman ini tidak boleh masuk riwayat.
        // Kalau masuk, menekan Back dari halaman project akan mengembalikan
        // pengguna ke layar tunggu untuk proses yang sudah selesai.
        if (d.job?.status !== "processing" && d.project.status !== "processing") {
          router.replace(`/project/${id}`);
          return;
        }
        timer = setTimeout(poll, 4000);
      } catch (err) {
        if (alive) setError((err as Error).message);
      }
    }

    poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [id, router]);

  const tahap = data?.job?.tahap?.trim() || "Memproses";
  const progres = data?.job?.progress ?? 0;

  return (
    <section className="proses-halaman">
      <TombolKembali
        href={`/project/${id}`}
        label="Kembali ke project"
        className="proses-kembali"
      />

      {/* Satu kata tetap di dalam bolanya, bukan nama tahap yang berganti-ganti.
          
          Tahap sebenarnya tetap ditampilkan — di label bilah progres tepat di
          bawah ini. Yang di dalam bola menjawab pertanyaan yang berbeda: bukan
          "sedang di langkah mana", melainkan "ini sedang dikerjakan". Nama
          tahap di situ juga membuat lebar katanya berubah-ubah setiap beberapa
          menit, dan bolanya ikut terlihat berdenyut ukuran. */}
      <PemuatAI kata="editing" ukuran={260} />

      <div>
        <h1 className="proses-judul">{data?.project.judul ?? "Menyiapkan"}</h1>
        <p className="proses-tahap">Agent sedang mengerjakan short ini di PC-mu.</p>
      </div>

      <div className="proses-bilah">
        <ProgressBar
          value={progres > 0 ? progres : null}
          label={tahap}
          pendingLabel="Menyiapkan"
          completeLabel="Render selesai"
        />
      </div>

      {error ? (
        <div className="notice err" role="alert">
          {error}
        </div>
      ) : (
        <p className="proses-catatan">
          Perkiraan total 10&ndash;15 menit. Halaman ini memperbarui sendiri dan
          akan pindah ke hasilnya begitu selesai — tidak perlu ditunggu di sini.
        </p>
      )}
    </section>
  );
}
