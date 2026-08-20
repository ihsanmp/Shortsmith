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

  if (row.project_id) {
    await db
      .update(projects)
      .set({ status: row.status as ProjectStatus })
      .where(eq(projects.id, row.project_id));
  }
  return { status: row.status, retryCount: row.retry_count };
}

/** Berapa job pending yang antre di depan job ini — untuk ditampilkan di UI. */
export async function queuePosition(jobId: string): Promise<number> {
  const rows = await db.execute<{ posisi: number }>(queuePositionSql(jobId));
  return rows[0]?.posisi ?? 0;
}
