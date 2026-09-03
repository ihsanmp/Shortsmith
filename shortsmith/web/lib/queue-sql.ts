import { sql, type SQL } from "drizzle-orm";

/**
 * SQL antrean, dipisah dari lapisan yang memanggilnya supaya bisa dieksekusi
 * apa adanya di test terhadap Postgres sungguhan. Yang diuji adalah query yang
 * sama persis dengan yang dikirim ke produksi — bukan salinannya.
 */

export const MAX_RETRY = 2;

/**
 * Berapa kali job boleh direbut kembali karena agent-nya hilang.
 *
 * TERPISAH dari MAX_RETRY, dan sengaja jauh lebih longgar. Keduanya menjawab
 * pertanyaan yang berbeda:
 *
 *   retry_count  "apakah job ini rusak?"      — bukti: agent melaporkan gagal
 *   lepas_count  "apakah agent ini sehat?"    — bukti: denyutnya berhenti
 *
 * Agent yang hilang bukan bukti apa pun tentang job-nya. PC-nya tidur, listrik
 * padam, atau daemonnya di-restart untuk memasang versi baru — dan restart
 * adalah hal yang sering terjadi justru saat sedang memperbaiki sesuatu.
 *
 * Terjadi sungguhan: satu job podcast sedang menunggu pengguna mencentang
 * topik, keadaan yang paling lama dan paling rentan karena ia duduk di
 * `processing` tanpa menghitung apa pun. Daemon di-restart untuk memasang
 * perbaikan, server membacanya sebagai percobaan gagal ketiga, dan job itu
 * ditandai gagal permanen padahal tidak ada yang salah dengannya.
 *
 * Tetap dibatasi: job yang benar-benar membuat agent-nya mati tiap kali harus
 * berhenti sendiri, bukan mengulang analisis satu jam berkali-kali selamanya.
 * Sepuluh cukup longgar untuk tidak pernah tersentuh pemakaian normal.
 */
export const MAX_LEPAS = 10;
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
       SET status = CASE WHEN lepas_count >= ${MAX_LEPAS} THEN 'failed'::job_status
                         ELSE 'pending'::job_status END,
           -- lepas_count, BUKAN retry_count. Lihat MAX_LEPAS untuk kenapa
           -- keduanya menjawab pertanyaan yang berbeda.
           lepas_count = lepas_count + 1,
           heartbeat_at = NULL,
           error_message = CASE
             WHEN lepas_count >= ${MAX_LEPAS}
             THEN 'Agent berkali-kali berhenti merespons di tengah job ini.'
             ELSE error_message END,
           finished_at = CASE WHEN lepas_count >= ${MAX_LEPAS} THEN now() ELSE NULL END
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
/**
 * Menyelesaikan job DAN menyamakan status project-nya dalam satu pernyataan.
 *
 * ## Kenapa satu pernyataan, bukan dua
 *
 * Sebelumnya `finishJob` menulis dua kali: satu UPDATE ke jobs, lalu satu
 * UPDATE ke projects memakai project_id yang dikembalikan. Di antara keduanya
 * ada jendela, dan kalau yang kedua gagal — jaringan tersendat, fungsi
 * serverless kehabisan waktu — job selesai sementara project-nya tetap
 * "processing" selamanya.
 *
 * Bukan kemungkinan teoretis: satu project dari 30 Juli tercatat berstatus
 * processing padahal job render-nya `done` dan klipnya sudah ada. Selama
 * sebulan lebih ia tampil sebagai "sedang diproses" di daftar project, dan
 * halaman prosesnya akan menjajak tanpa akhir karena syarat berhentinya
 * menuntut KEDUA status keluar dari processing.
 *
 * Sebagai satu pernyataan, keduanya berhasil bersama atau gagal bersama.
 */
export function finishJobSql(
  jobId: string,
  status: "done" | "failed",
  errorMessage: string | null,
): SQL {
  return sql`
    WITH selesai AS (
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
    ),
    -- Project mengikuti status akhir job-nya. Job yang dikembalikan ke antrean
    -- (pending) membuat project-nya kembali pending juga, persis seperti
    -- perilaku dua-pernyataan yang digantikannya.
    --
    -- Tanpa cast: kedua kolom memakai enum yang sama, job_status.
    ikut AS (
      UPDATE projects p
         SET status = s.status
        FROM selesai s
       WHERE p.id = s.project_id
    )
    SELECT status, retry_count, project_id FROM selesai
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
