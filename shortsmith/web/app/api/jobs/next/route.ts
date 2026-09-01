import { and, asc, eq } from "drizzle-orm";

import { db } from "@/db";
import { assets, conceptProfiles, projects } from "@/db/schema";
import { isAgentAuthorized, unauthorized } from "@/lib/auth";
import { claimNextJob, reapStaleJobs } from "@/lib/jobs";
import { buildKey, presignDownload, presignUpload } from "@/lib/storage";
import { ambilTugas } from "@/lib/tugas";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Batas 30 detik, jauh di bawah bawaan Vercel (300 detik).
//
// Rute ini hanya membaca beberapa baris dan menandatangani URL — kerjanya
// hitungan milidetik. Kalau ia belum selesai dalam 30 detik, artinya ia
// menggantung, dan menggantung selama 5 menit sambil menahan koneksi database
// adalah cara satu permintaan lambat berubah jadi seluruh API mati.
export const maxDuration = 30;

/**
 * Ambil satu job pending dan tandai processing.
 *
 * Responsnya sengaja lengkap: agent mendapat semua URL bertanda tangan yang ia
 * butuhkan dalam satu panggilan — unduh input, unggah output. Konsekuensinya
 * agent TIDAK PERNAH memegang kredensial object storage. Kalau kunci agent bocor,
 * yang bocor hanyalah kemampuan mengambil job, bukan akses penuh ke bucket.
 */
export async function GET(request: Request) {
  if (!isAgentAuthorized(request)) return unauthorized();

  await reapStaleJobs();

  const job = await claimNextJob();
  if (!job) {
    // Tidak ada job — sekalian tawarkan tugas, supaya daemon cukup SATU
    // permintaan per putaran. Lihat lib/tugas.ts untuk angkanya: dua endpoint
    // yang ditanya bergantian membuat 84% lalu lintas API hanyalah daemon
    // menanyakan hal yang sama dua kali, dan itu menjenuhkan pooler koneksi
    // sampai permintaan pengguna sendiri berakhir 504.
    return Response.json({ job: null, tugas: await ambilTugas() }, { status: 200 });
  }

  // Dicocokkan PERSIS, bukan lewat "yang bukan render berarti konsep".
  //
  // Percabangan lama memilih jalur konsep untuk nilai apa pun yang bukan
  // "render" — termasuk undefined. Satu baris job yang bermasalah karena itu
  // dikirim ke pembangun muatan yang salah, dan hasilnya muatan tanpa `id`
  // yang sempat mematikan agent. Sekarang tipe yang tidak dikenal ditolak
  // dengan menyebut nilainya.
  if (job.tipe === "render") {
    return Response.json({ job: await buildRenderPayload(job) });
  }
  if (job.tipe === "profile_extraction") {
    return Response.json({ job: await buildProfilePayload(job) });
  }

  console.error(`[jobs/next] tipe job tidak dikenal: ${JSON.stringify(job.tipe)}`);
  return Response.json({ job: null, tugas: await ambilTugas() }, { status: 200 });
}

async function buildRenderPayload(job: {
  id: string;
  tipe: string;
  project_id: string | null;
  concept_id: string | null;
  retry_count: number;
}) {
  const [project] = job.project_id
    ? await db.select().from(projects).where(eq(projects.id, job.project_id)).limit(1)
    : [];

  const [concept] = job.concept_id
    ? await db
        .select()
        .from(conceptProfiles)
        .where(eq(conceptProfiles.id, job.concept_id))
        .limit(1)
    : [];

  const raws = job.project_id
    ? await db
        .select()
        .from(assets)
        .where(and(eq(assets.projectId, job.project_id), eq(assets.jenis, "raw")))
        // Urutan HARUS stabil DAN sesuai pilihan pengguna: nomor VIDEO yang
        // dipakai agent adalah indeks di array ini. VIDEO 0 adalah sumber suara.
        // created_at tidak cukup — satu batch insert memberi timestamp yang sama
        // ke semua baris, dan tiebreak-nya UUID acak.
        .orderBy(asc(assets.urutan), asc(assets.createdAt), asc(assets.id))
        .limit(10)
    : [];

  // Berkas lokal tidak ditandatangani: tidak ada objek di storage untuk ditunjuk.
  // Agent mencarinya sendiri di SHORTSMITH_BAHAN_DIR memakai namaFile.
  const inputs = await Promise.all(
    raws.map(async (a) => ({
      namaFile: a.namaFile,
      ukuranBytes: a.ukuranBytes,
      lokal: a.lokal,
      bahanFolder: a.bahanFolder,
      storageKey: a.lokal ? "" : a.storageKey,
      downloadUrl: a.lokal ? null : await presignDownload(a.storageKey),
    })),
  );

  // Lagu diambil terpisah dari daftar `raw`, dengan aturan penandatanganan yang
  // sama: berkas lokal tidak punya objek di storage untuk ditunjuk.
  const [lagu] = job.project_id
    ? await db
        .select()
        .from(assets)
        .where(and(eq(assets.projectId, job.project_id), eq(assets.jenis, "music")))
        .limit(1)
    : [];

  const musik = lagu
    ? {
        namaFile: lagu.namaFile,
        ukuranBytes: lagu.ukuranBytes,
        lokal: lagu.lokal,
        bahanFolder: lagu.bahanFolder,
        storageKey: lagu.lokal ? "" : lagu.storageKey,
        downloadUrl: lagu.lokal ? null : await presignDownload(lagu.storageKey),
      }
    : null;

  const outputKey = buildKey("output", `${job.id}.mp4`);

  return {
    id: job.id,
    tipe: job.tipe,
    retryCount: job.retry_count,
    projectId: job.project_id,
    conceptId: job.concept_id,
    brief: project?.brief ?? "",
    judul: project?.judul ?? "",
    profileJson: concept?.profileJson ?? null,
    jenis: project?.jenis ?? "short",
    rasio: project?.rasio ?? "auto",
    inputs,
    musik,
    output: { key: outputKey, uploadUrl: await presignUpload(outputKey, "video/mp4") },
  };
}

async function buildProfilePayload(job: {
  id: string;
  tipe: string;
  concept_id: string | null;
  retry_count: number;
}) {
  const [concept] = job.concept_id
    ? await db
        .select()
        .from(conceptProfiles)
        .where(eq(conceptProfiles.id, job.concept_id))
        .limit(1)
    : [];

  const samples = job.concept_id
    ? await db
        .select()
        .from(assets)
        .where(and(eq(assets.conceptId, job.concept_id), eq(assets.jenis, "sample")))
        .orderBy(asc(assets.urutan), asc(assets.createdAt), asc(assets.id))
        .limit(8)
    : [];

  const inputs = await Promise.all(
    samples.map(async (a) => ({
      namaFile: a.namaFile,
      storageKey: a.storageKey,
      downloadUrl: await presignDownload(a.storageKey),
    })),
  );

  return {
    id: job.id,
    tipe: job.tipe,
    retryCount: job.retry_count,
    conceptId: job.concept_id,
    nama: concept?.nama ?? "",
    profileJson: concept?.profileJson ?? null,
    inputs,
    output: null,
  };
}
