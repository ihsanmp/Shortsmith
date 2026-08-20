import { and, desc, eq } from "drizzle-orm";

import { db } from "@/db";
import { assets, conceptProfiles, jobs, projects } from "@/db/schema";
import { queuePosition, reapStaleJobs } from "@/lib/jobs";
import { hapusObjek, presignDownload } from "@/lib/storage";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

/** Endpoint yang di-polling halaman status. */
export async function GET(_request: Request, { params }: Params) {
  const { id } = await params;

  // Pungut job terlantar setiap kali antrean disentuh — tidak perlu cron terpisah.
  await reapStaleJobs();

  const [project] = await db
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
    .limit(1);

  if (!project) {
    return Response.json({ error: "Project tidak ditemukan" }, { status: 404 });
  }

  const [job] = await db
    .select()
    .from(jobs)
    .where(eq(jobs.projectId, id))
    .orderBy(desc(jobs.createdAt))
    .limit(1);

  const [output] = await db
    .select()
    .from(assets)
    .where(and(eq(assets.projectId, id), eq(assets.jenis, "output")))
    .orderBy(desc(assets.createdAt))
    .limit(1);

  const outputUrl = output ? await presignDownload(output.storageKey) : null;

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
        }
      : null,
    output: outputUrl
      ? { url: outputUrl, namaFile: output.namaFile, ukuranBytes: output.ukuranBytes }
      : null,
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

