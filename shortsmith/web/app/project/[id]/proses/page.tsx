"use client";

import { use } from "react";
import { useRouter } from "next/navigation";

import { PemuatAI } from "@/components/ui/pemuat-ai";
import { PilihTopik } from "@/components/pilih-topik";
import { ProgressBar } from "@/components/ui/progress-bar";
import { TombolKembali } from "@/components/ui/tombol-kembali";
import { useJajakProject } from "@/lib/jajak";

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
  job: {
    id: string;
    status: Status;
    progress: number;
    tahap: string;
    topikUsul: string[] | null;
    topikPilih: string[] | null;
  } | null;
};

export default function HalamanProses({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { data, error, setData } = useJajakProject<Data>(id, (d) => {
    if (d.job?.status === "processing" || d.project.status === "processing") return false;
    // `replace`, bukan `push`: halaman ini tidak boleh masuk riwayat. Kalau
    // masuk, menekan Back dari halaman project akan mengembalikan pengguna ke
    // layar tunggu untuk proses yang sudah selesai.
    router.replace(`/project/${id}`);
    return true;
  });

  const tahap = data?.job?.tahap?.trim() || "Memproses";
  const progres = data?.job?.progress ?? 0;
  const job = data?.job ?? null;

  // Ditanyakan HANYA kalau agent sudah menaruh usulan DAN pengguna belum
  // menjawab. `topikPilih` yang berupa array kosong adalah jawaban yang sah
  // ("tidak satu pun"), jadi yang diperiksa null-nya, bukan panjangnya.
  const tanya = Boolean(
    job && job.topikUsul && job.topikUsul.length > 0 && job.topikPilih === null,
  );

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

      {/* Pertanyaannya menggantikan bilah progres, bukan menempel di bawahnya.
          Selama menunggu jawaban tidak ada yang bergerak, dan bilah yang diam
          di sebelah pertanyaan terbaca seperti proses yang macet. */}
      {tanya ? (
        <PilihTopik
          jobId={job!.id}
          topik={job!.topikUsul!}
          onKirim={(dipilih) =>
            setData((d) =>
              d?.job ? { ...d, job: { ...d.job, topikPilih: dipilih } } : d,
            )
          }
        />
      ) : (
      <div className="proses-bilah">
        <ProgressBar
          value={progres > 0 ? progres : null}
          label={tahap}
          pendingLabel="Menyiapkan"
          completeLabel="Render selesai"
        />
      </div>
      )}

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
