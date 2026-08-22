import { and, eq } from "drizzle-orm";
import { z } from "zod";

import { db } from "@/db";
import { assets, conceptProfiles, jobs } from "@/db/schema";
import { isAgentAuthorized, unauthorized } from "@/lib/auth";
import { finishJob } from "@/lib/jobs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Batas 30 detik, jauh di bawah bawaan Vercel (300 detik).
//
// Rute ini hanya membaca beberapa baris dan menandatangani URL — kerjanya
// hitungan milidetik. Kalau ia belum selesai dalam 30 detik, artinya ia
// menggantung, dan menggantung selama 5 menit sambil menahan koneksi database
// adalah cara satu permintaan lambat berubah jadi seluruh API mati.
export const maxDuration = 30;

type Params = { params: Promise<{ id: string }> };

const Body = z.object({
  status: z.enum(["done", "failed"]),
  errorMessage: z.string().max(4000).optional(),
  /** Job render: key hasil yang sudah diunggah agent lewat presigned URL. */
  outputKey: z.string().min(1).optional(),
  namaFile: z.string().max(255).optional(),
  ukuranBytes: z.number().int().positive().optional(),
  durasi: z.number().positive().optional(),
  /**
   * Klip TAMBAHAN, kalau job ini menghasilkan lebih dari satu.
   *
   * Terpisah dari `outputKey`, bukan menggantikannya: agent versi lama hanya
   * mengirim `outputKey`, dan server yang menuntut bentuk baru akan menolak
   * seluruh laporannya -- job yang rendernya sudah selesai jadi gagal karena
   * bentuk pesan, bukan karena pekerjaannya.
   */
  klipTambahan: z
    .array(
      z.object({
        outputKey: z.string().min(1),
        namaFile: z.string().max(255).optional(),
        ukuranBytes: z.number().int().positive().optional(),
        durasi: z.number().positive().optional(),
      }),
    )
    .max(8)
    .optional(),
  /** Job profile_extraction: profil hasil analisis video contoh. */
  profileJson: z.record(z.unknown()).optional(),
});

export async function POST(request: Request, { params }: Params) {
  if (!isAgentAuthorized(request)) return unauthorized();

  const { id } = await params;

  let body;
  try {
    body = Body.parse(await request.json());
  } catch (err) {
    return Response.json(
      { error: "Body tidak valid", detail: (err as Error).message },
      { status: 400 },
    );
  }

  const [job] = await db.select().from(jobs).where(eq(jobs.id, id)).limit(1);
  if (!job) return Response.json({ error: "Job tidak ditemukan" }, { status: 404 });

  if (body.status === "done") {
    if (job.tipe === "render" && body.outputKey && job.projectId) {
      // Klip utama dan klip tambahan disisipkan sebagai baris yang SAMA
      // bentuknya. `urutan` menjaga nomornya stabil: tanpa itu halaman project
      // mengurutkannya lewat created_at yang identik untuk satu batch insert,
      // dan penentu akhirnya jatuh ke UUID acak -- nomor klip akan berubah tiap
      // kali halaman dimuat.
      const semua = [
        {
          outputKey: body.outputKey,
          namaFile: body.namaFile,
          ukuranBytes: body.ukuranBytes,
          durasi: body.durasi,
        },
        ...(body.klipTambahan ?? []),
      ];
      await db.insert(assets).values(
        semua.map((k, i) => ({
          projectId: job.projectId!,
          jenis: "output" as const,
          urutan: i,
          storageKey: k.outputKey,
          namaFile: k.namaFile || (k.outputKey.split("/").pop() ?? "output.mp4"),
          ukuranBytes: k.ukuranBytes,
          durasi: k.durasi != null ? String(k.durasi) : null,
        })),
      );
    }

    if (job.tipe === "profile_extraction" && body.profileJson && job.conceptId) {
      // Konsep hanya boleh ditulis SEKALI, saat pertama kali diekstrak.
      //
      // Setelah `siap`, isinya beku: job berikutnya tidak akan menyentuhnya,
      // dan hasil render lama tetap bisa ditelusuri ke metrik yang sama persis.
      // Untuk mengubah gaya, kirim video contoh baru — itu melahirkan konsep
      // baru, bukan menimpa yang lama.
      const terkunci = await db
        .update(conceptProfiles)
        .set({ profileJson: body.profileJson, siap: true })
        .where(and(eq(conceptProfiles.id, job.conceptId), eq(conceptProfiles.siap, false)))
        .returning({ id: conceptProfiles.id });

      if (terkunci.length === 0) {
        console.warn(
          `[job ${id}] konsep ${job.conceptId} sudah terkunci — hasil ekstraksi diabaikan`,
        );
      }
    }
  }

  const hasil = await finishJob({
    jobId: id,
    status: body.status,
    errorMessage: body.errorMessage ?? null,
  });

  return Response.json({
    ok: true,
    status: hasil?.status,
    retryCount: hasil?.retryCount,
    // Beri tahu agent apakah job akan dicoba lagi, supaya lognya jujur.
    akanDiulang: hasil?.status === "pending",
  });
}
