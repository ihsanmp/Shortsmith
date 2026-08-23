import { sql } from "drizzle-orm";

import { db } from "@/db";
import { presignDownload } from "@/lib/storage";

/**
 * Pengambilan satu tugas dari antrean, dipakai bersama oleh dua route.
 *
 * ## Kenapa dipisah ke sini
 *
 * `/api/jobs/next` ikut mengembalikan tugas kalau tidak ada job, supaya daemon
 * cukup satu permintaan per putaran alih-alih dua. Terukur di log produksi:
 * dari 100 permintaan, 42 ke `/api/jobs/next` dan 42 ke `/api/tugas/next` --
 * 84% seluruh lalu lintas hanyalah daemon bertanya "ada kerjaan?" dua kali
 * untuk pertanyaan yang sama.
 *
 * Beban itu menjenuhkan pooler koneksi Postgres, dan delapan permintaan
 * berakhir 504 FUNCTION_INVOCATION_TIMEOUT -- termasuk halaman project yang
 * dibuka pengguna.
 *
 * `/api/tugas/next` tetap ada supaya agent versi lama masih jalan.
 */

const BASI_DETIK = 120;

type Diambil = {
  id: string;
  tipe: "prompt" | "review";
  permintaan: Record<string, unknown>;
};

export async function ambilTugas() {
  // Tugas yang tertinggal `processing` karena daemon mati dibebaskan lebih
  // dulu. Ambangnya jauh lebih pendek daripada job: tugas ini hitungan detik,
  // jadi yang sudah lewat dua menit pasti mati.
  await db.execute(sql`
    UPDATE tugas
       SET status = 'pending', heartbeat_at = NULL
     WHERE status = 'processing'
       AND heartbeat_at IS NOT NULL
       AND heartbeat_at < now() - (${BASI_DETIK} * interval '1 second')
  `);

  // SKIP LOCKED supaya dua daemon yang berjalan bersamaan tidak mengambil
  // baris yang sama, mengerjakannya dua kali, dan menagih dua kali.
  const rows = await db.execute<Diambil>(sql`
    UPDATE tugas t
       SET status = 'processing', heartbeat_at = now()
     WHERE t.id = (
       SELECT q.id FROM tugas q
        WHERE q.status = 'pending'
        ORDER BY q.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
     )
    RETURNING t.id, t.tipe, t.permintaan
  `);

  const t = rows[0];
  if (!t) return null;

  const permintaan = { ...t.permintaan } as Record<string, unknown>;

  // Berkas hanya bisa dibaca agent lewat URL bertanda tangan. Agent TIDAK
  // pernah memegang kredensial storage — aturan yang sama dengan seluruh jalur
  // lain, dan tidak dilonggarkan di sini.
  if (t.tipe === "review") {
    const klip = (permintaan.klip ?? []) as { key: string; nama: string; prompt: string }[];
    permintaan.klip = await Promise.all(
      klip.map(async (k) => ({ ...k, url: await presignDownload(k.key) })),
    );

    const bahan = (permintaan.bahan ?? []) as {
      key: string;
      nama: string;
      folder: string;
    }[];
    permintaan.bahan = await Promise.all(
      bahan.map(async (b) => ({
        ...b,
        // Bahan mode folder lokal tidak punya key. Ia dikenali agent lewat
        // namanya di dalam folder bahan, persis seperti di jalur render.
        url: b.key ? await presignDownload(b.key) : null,
      })),
    );
  }

  return { id: t.id, tipe: t.tipe, permintaan };
}
