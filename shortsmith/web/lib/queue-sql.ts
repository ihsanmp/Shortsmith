import { sql, type SQL } from "drizzle-orm";

/**
 * SQL antrean, dipisah dari lapisan yang memanggilnya supaya bisa dieksekusi
 * apa adanya di test terhadap Postgres sungguhan. Yang diuji adalah query yang
 * sama persis dengan yang dikirim ke produksi — bukan salinannya.
 */

export const MAX_RETRY = 2;
export const HEARTBEAT_TIMEOUT = "5 minutes";

/**
 * Ambil satu job pending dan tandai processing, secara atomik.
 *
 * `FOR UPDATE SKIP LOCKED` adalah bagian yang tidak boleh dihilangkan. Tanpa itu,
 * dua agent yang polling bersamaan (atau satu agent yang di-restart saat request
 * sebelumnya masih terbang) bisa mengambil job yang sama dan merender dua kali.
 * Satu statement UPDATE...RETURNING sudah berjalan dalam transaksi implisit.
 */
export function claimNextJobSql(): SQL {
  return sql`
    UPDATE jobs j
       SET status       = 'processing',
           started_at   = now(),
           heartbeat_at = now(),
           progress     = 0,
           tahap        = 'diambil agent'
     WHERE j.id = (
       SELECT q.id
         FROM jobs q
        WHERE q.status = 'pending'
          -- Job render tidak boleh diambil sebelum konsepnya selesai diekstrak.
          -- Kalau user mengunggah video contoh bersamaan dengan video mentah,
          -- dua job lahir sekaligus: profile_extraction lalu render. Tanpa
          -- penjaga ini, render bisa terambil duluan dan mengerjakan konsep
          -- yang metriknya masih kosong.
          AND (
            q.tipe <> 'render'
            OR q.concept_id IS NULL
            OR EXISTS (
              SELECT 1 FROM concept_profiles c
               WHERE c.id = q.concept_id AND c.siap
            )
          )
        ORDER BY q.created_at
        LIMIT 1
        FOR UPDATE SKIP LOCKED
     )
    RETURNING j.id, j.tipe, j.project_id, j.concept_id, j.retry_count
  `;
}

export function touchHeartbeatSql(
  jobId: string,
  patch?: { progress?: number; tahap?: string },
): SQL {
  return sql`
    UPDATE jobs
       SET heartbeat_at = now(),
           progress     = COALESCE(${patch?.progress ?? null}::int, progress),
           tahap        = COALESCE(${patch?.tahap ?? null}::text, tahap)
     WHERE id = ${jobId} AND status = 'processing'
    RETURNING id
  `;
}

/**
 * Kembalikan job yang agent-nya berhenti merespons ke antrean.
 * Menangani PC mati mendadak, listrik padam, atau agent crash.
 */
export function reapStaleJobsSql(): SQL {
  return sql`
    UPDATE jobs
       SET status = CASE WHEN retry_count >= ${MAX_RETRY} THEN 'failed'::job_status
                         ELSE 'pending'::job_status END,
           retry_count = retry_count + 1,
           heartbeat_at = NULL,
           error_message = CASE
             WHEN retry_count >= ${MAX_RETRY}
             THEN 'Agent berhenti merespons dan batas percobaan ulang habis.'
             ELSE error_message END,
           finished_at = CASE WHEN retry_count >= ${MAX_RETRY} THEN now() ELSE NULL END
     WHERE status = 'processing'
       AND heartbeat_at IS NOT NULL
       AND heartbeat_at < now() - ${HEARTBEAT_TIMEOUT}::interval
    RETURNING id, status
  `;
}

/**
 * Tutup satu job. Kegagalan yang masih punya jatah percobaan dikembalikan ke
 * `pending`, bukan langsung `failed`.
 */
export function finishJobSql(
  jobId: string,
  status: "done" | "failed",
  errorMessage: string | null,
): SQL {
  return sql`
    UPDATE jobs
       SET status = CASE
             WHEN ${status} = 'done' THEN 'done'::job_status
             WHEN retry_count >= ${MAX_RETRY} THEN 'failed'::job_status
             ELSE 'pending'::job_status END,
           retry_count = CASE WHEN ${status} = 'failed'
                              THEN retry_count + 1 ELSE retry_count END,
           progress = CASE WHEN ${status} = 'done' THEN 100 ELSE progress END,
           tahap = CASE WHEN ${status} = 'done' THEN 'selesai' ELSE tahap END,
           error_message = ${errorMessage},
           heartbeat_at = NULL,
           finished_at = CASE WHEN ${status} = 'done' OR retry_count >= ${MAX_RETRY}
                              THEN now() ELSE NULL END
     WHERE id = ${jobId}
    RETURNING status, retry_count, project_id
  `;
}

export function queuePositionSql(jobId: string): SQL {
  return sql`
    SELECT COUNT(*)::int AS posisi
      FROM jobs
     WHERE
       -- Job yang SEDANG dikerjakan ikut dihitung, dan ini yang sebelumnya
       -- hilang. Agent mengerjakan satu job pada satu waktu, jadi job yang
       -- sedang berjalan berada di depan antrean seperti halnya job pending
       -- yang lebih tua.
       --
       -- Tanpa ini, job yang menunggu di belakang satu job berjalan terbaca
       -- berposisi NOL, dan halaman project menyimpulkan tidak ada apa-apa di
       -- depannya -- lalu menampilkan "Pastikan agent sedang berjalan di PC
       -- lokal" untuk agent yang sebenarnya sibuk mengerjakan job sebelumnya.
       status = 'processing'
       OR (
         status = 'pending'
         AND created_at < (SELECT created_at FROM jobs WHERE id = ${jobId})
       )
  `;
}
