import { and, desc, eq } from "drizzle-orm";

import { db } from "@/db";
import { assets, conceptProfiles, jobs, projects } from "@/db/schema";
import { queuePosition } from "@/lib/jobs";
import { hapusObjek, presignDownload } from "@/lib/storage";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

/** Endpoint yang di-polling halaman status. */
export async function GET(_request: Request, { params }: Params) {
  const { id } = await params;

  // Tiga pembacaan yang saling BEBAS, dijalankan bersamaan.
  //
  // Sebelumnya berurutan, dan halaman project mem-poll route ini tiap empat
  // detik selama render berjalan — yang bisa berlangsung dua puluh lima menit.
  // Tiap round-trip ke Postgres dari Vercel berbiaya puluhan milidetik, jadi
  // menunggu satu selesai sebelum memulai berikutnya membayar ongkos itu tiga
  // kali untuk pertanyaan yang tidak saling bergantung.
  //
  // `reapStaleJobs()` DIBUANG dari sini, bukan sekadar dipindah. Ia query
  // UPDATE, dan ini jalur BACA: tiap halaman project yang terbuka menulis ke
  // database tiap empat detik tanpa ada yang memintanya. Pemungutannya sudah
  // dilakukan /api/jobs/next, yang memang disentuh daemon tiap sepuluh detik --
  // jadi tidak ada yang hilang, yang hilang cuma tulisannya.
  const [[project], [job], keluaranMentah] = await Promise.all([
    db
      .select({
        id: projects.id,
        judul: projects.judul,
        brief: projects.brief,
        status: projects.status,
        createdAt: projects.createdAt,
        conceptId: projects.conceptId,
        conceptNama: conceptProfiles.nama,
      })
      .from(projects)
      .leftJoin(conceptProfiles, eq(projects.conceptId, conceptProfiles.id))
      .where(eq(projects.id, id))
      .limit(1),
    db
      .select()
      .from(jobs)
      .where(eq(jobs.projectId, id))
      .orderBy(desc(jobs.createdAt))
      .limit(1),
    db
      .select()
      .from(assets)
      .where(and(eq(assets.projectId, id), eq(assets.jenis, "output")))
      .orderBy(assets.urutan, desc(assets.createdAt)),
  ]);

  if (!project) {
    return Response.json({ error: "Project tidak ditemukan" }, { status: 404 });
  }

  // Satu project bisa punya beberapa hasil.
  //
  // Saat topiknya dikosongkan, satu rekaman panjang dipecah jadi beberapa klip
  // dari bagian yang berbeda. Diurutkan menurut `urutan`, bukan `created_at`:
  // semuanya disisipkan dalam satu batch sehingga waktunya identik, dan
  // penentu akhirnya jatuh ke UUID acak -- nomor klip akan berubah tiap kali
  // halaman dimuat.
  const keluaran = keluaranMentah;

  const semuaOutput = await Promise.all(
    keluaran.map(async (o) => ({
      url: await presignDownload(o.storageKey),
      namaFile: o.namaFile,
      ukuranBytes: o.ukuranBytes,
      durasi: o.durasi != null ? Number(o.durasi) : null,
      keterangan: o.keterangan,
    })),
  );
  const output = keluaran[0];
  const outputUrl = semuaOutput[0]?.url ?? null;

  // Estimasi kasar: satu PC hanya bisa memproses satu job pada satu waktu.
  const posisi = job && job.status === "pending" ? await queuePosition(job.id) : 0;

  return Response.json({
    project,
    job: job
      ? {
          id: job.id,
          status: job.status,
          progress: job.progress,
          tahap: job.tahap,
          errorMessage: job.errorMessage,
          retryCount: job.retryCount,
          heartbeatAt: job.heartbeatAt,
          posisiAntrean: posisi,
          estimasiMenit: posisi * 12,
          // Topik yang ditawarkan agent, dan yang sudah dicentang pengguna.
          // `topikPilih` null berarti pertanyaannya masih terbuka — itulah
          // satu-satunya penanda yang dipakai halaman proses untuk memunculkan
          // daftar centangnya.
          topikUsul: job.topikUsul ?? null,
          topikPilih: job.topikPilih ?? null,
        }
      : null,
    // `output` dipertahankan apa adanya supaya klien lama tetap jalan; yang
    // baru membaca `semuaOutput`.
    output: outputUrl
      ? { url: outputUrl, namaFile: output.namaFile, ukuranBytes: output.ukuranBytes }
      : null,
    semuaOutput,
  });
}

/**
 * Hapus project: berkasnya di storage DAN barisnya di database.
 *
 * Versi sebelumnya hanya menghapus baris database dan MENINGGALKAN berkasnya di
 * Backblaze selamanya — ratusan MB per project yang terus ditagih tanpa ada cara
 * menemukannya lagi lewat aplikasi ini.
 *
 * Sempat ada dua cakupan di sini, "hasil saja" dan "semua". Yang pertama dibuang:
 * alasannya adalah supaya project bisa dirender ulang tanpa mengunggah lagi,
 * padahal aplikasi ini tidak punya tombol render ulang. Menyimpan video mentah
 * untuk kemampuan yang tidak ada hanya menyisakan biaya penyimpanan.
 */
export async function DELETE(_request: Request, { params }: Params) {
  const { id } = await params;

  const baris = await db
    .select({ storageKey: assets.storageKey, lokal: assets.lokal })
    .from(assets)
    .where(eq(assets.projectId, id));

  // Storage dibersihkan LEBIH DULU. Kalau urutannya dibalik dan penghapusan
  // storage gagal, key-nya sudah hilang dari database dan berkasnya jadi yatim:
  // menempati ruang selamanya tanpa ada cara menemukannya lagi.
  let terhapus = 0;
  try {
    // Berkas lokal adalah MILIK PENGGUNA di disknya sendiri, bukan salinan yang
    // kita kelola. Tombol hapus di aplikasi ini tidak boleh menyentuhnya —
    // itu kehilangan data yang tidak bisa dibatalkan dan tidak pernah diminta.
    terhapus = await hapusObjek(baris.filter((b) => !b.lokal).map((b) => b.storageKey));
  } catch (err) {
    return Response.json(
      { error: "Gagal menghapus berkas di storage", detail: (err as Error).message },
      { status: 502 },
    );
  }

  await db.delete(projects).where(eq(projects.id, id));

  return Response.json({ ok: true, berkasDihapus: baris.length, versiDihapus: terhapus });
}

