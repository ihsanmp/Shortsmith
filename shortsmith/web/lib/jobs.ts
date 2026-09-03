import { eq } from "drizzle-orm";

import { db } from "@/db";
import { projects } from "@/db/schema";
import {
  claimNextJobSql,
  finishJobSql,
  queuePositionSql,
  reapStaleJobsSql,
  touchHeartbeatSql,
  HEARTBEAT_TIMEOUT,
  MAX_RETRY,
} from "./queue-sql";

export { HEARTBEAT_TIMEOUT, MAX_RETRY };

export type ClaimedJob = {
  id: string;
  tipe: "render" | "profile_extraction";
  project_id: string | null;
  concept_id: string | null;
  retry_count: number;
};

type ProjectStatus = "pending" | "processing" | "done" | "failed";

export async function claimNextJob(): Promise<ClaimedJob | null> {
  const rows = await db.execute<ClaimedJob>(claimNextJobSql());
  const job = rows[0] ?? null;

  // Baris yang terambil TAPI tidak punya id diperlakukan sebagai tidak ada job.
  //
  // Tanpa penjagaan ini, baris seperti itu diteruskan ke pembangun muatan, yang
  // dengan senang hati menyusun jawaban dari field-field bawaannya saja —
  // `job.id` dan `job.tipe` yang undefined hilang begitu saja saat JSON
  // dirangkai. Agent menerima muatan yang terlihat sah bentuknya:
  //
  //     {"nama": "", "profileJson": null, "inputs": [], "output": null}
  //
  // dan sempat MATI karenanya (KeyError: 'id') sebelum ia diajari bertahan.
  // Cacat yang sebenarnya ada di sini: yang tidak punya id bukan job.
  //
  // `job.tipe` juga dipilih diam-diam oleh percabangan di /api/jobs/next —
  // yang bukan "render" jatuh ke jalur konsep, jadi `undefined` mengirim job
  // render ke pembangun muatan yang salah tanpa satu pun peringatan.
  if (job && (!job.id || !job.tipe)) {
    console.error(
      "[claimNextJob] baris job tanpa id/tipe, diabaikan:",
      JSON.stringify(job).slice(0, 300),
    );
    return null;
  }

  if (job?.project_id) {
    await db
      .update(projects)
      .set({ status: "processing" })
      .where(eq(projects.id, job.project_id));
  }
  return job;
}

export async function touchHeartbeat(
  jobId: string,
  patch?: { progress?: number; tahap?: string },
): Promise<boolean> {
  const rows = await db.execute<{ id: string }>(touchHeartbeatSql(jobId, patch));
  return rows.length > 0;
}

/**
 * Dipanggil lazily setiap kali antrean disentuh — tidak perlu cron terpisah,
 * dan biaya satu UPDATE beracuan indeks itu murah.
 */
export async function reapStaleJobs(): Promise<number> {
  const rows = await db.execute<{ id: string }>(reapStaleJobsSql());
  return rows.length;
}

export async function finishJob({
  jobId,
  status,
  errorMessage,
}: {
  jobId: string;
  status: "done" | "failed";
  errorMessage?: string | null;
}): Promise<{ status: string; retryCount: number } | null> {
  const rows = await db.execute<{
    status: string;
    retry_count: number;
    project_id: string | null;
  }>(finishJobSql(jobId, status, errorMessage ?? null));

  const row = rows[0];
  if (!row) return null;

  // Status project sudah ikut disamakan DI DALAM pernyataan yang sama — lihat
  // finishJobSql. Dulu di sini ada UPDATE kedua, dan jendela di antara keduanya
  // yang meninggalkan satu project berstatus "processing" selama sebulan lebih
  // padahal job-nya sudah `done` dan klipnya sudah ada.
  return { status: row.status, retryCount: row.retry_count };
}

/** Berapa job pending yang antre di depan job ini — untuk ditampilkan di UI. */
export async function queuePosition(jobId: string): Promise<number> {
  const rows = await db.execute<{ posisi: number }>(queuePositionSql(jobId));
  return rows[0]?.posisi ?? 0;
}
