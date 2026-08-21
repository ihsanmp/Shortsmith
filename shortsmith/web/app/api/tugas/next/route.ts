import { sql } from "drizzle-orm";

import { db } from "@/db";
import { isAgentAuthorized, unauthorized } from "@/lib/auth";
import { presignDownload } from "@/lib/storage";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Diambil = {
  id: string;
  tipe: "prompt" | "review";
  permintaan: Record<string, unknown>;
};

/**
 * Agent mengambil satu tugas dari antrean.
 *
 * ## Kenapa tugas basi dibebaskan di sini
 *
 * Kalau daemon mati di tengah tugas, barisnya tertinggal `processing`
 * selamanya dan pengguna menunggu jawaban yang tidak akan datang. `jobs` punya
 * `reapStaleJobs` untuk itu; di sini ambangnya jauh lebih pendek — tugas ini
 * hitungan detik, bukan menit, jadi yang sudah lewat dua menit pasti mati.
 */
const BASI_DETIK = 120;

export async function GET(request: Request) {
  if (!isAgentAuthorized(request)) return unauthorized();

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
  if (!t) return Response.json({ tugas: null });

  const permintaan = { ...t.permintaan } as Record<string, unknown>;

  // Berkas hanya bisa dibaca agent lewat URL bertanda tangan. Agent TIDAK
  // pernah memegang kredensial storage — itu aturan yang sama dengan
  // /api/jobs/next, dan tidak dilonggarkan untuk jalur baru ini.
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

  return Response.json({ tugas: { id: t.id, tipe: t.tipe, permintaan } });
}
