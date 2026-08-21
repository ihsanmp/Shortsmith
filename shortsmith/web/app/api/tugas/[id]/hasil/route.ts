import { and, eq } from "drizzle-orm";
import { z } from "zod";

import { db } from "@/db";
import { tugas } from "@/db/schema";
import { isAgentAuthorized, unauthorized } from "@/lib/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Agent melaporkan hasil satu tugas — berhasil maupun gagal.
 *
 * Gagal ikut dilaporkan lewat jalur yang sama, bukan dibiarkan basi. Tugas yang
 * gagal diam-diam akan menunggu sampai penjaga tugas-basi membebaskannya, lalu
 * diambil lagi, gagal lagi, berputar tanpa pengguna pernah tahu apa yang salah.
 */
// Satu objek dengan dua field opsional, bukan union.
//
// Union tampak lebih tepat tapi tidak bisa dipersempit TypeScript di sini:
// `z.unknown()` membuat `hasil` opsional, sehingga `{ hasil?: unknown }` juga
// cocok dengan objek yang cuma berisi `error` — dan `"error" in data` berhenti
// menjadi pembeda yang dimengerti kompilator.
const Lapor = z
  .object({
    hasil: z.unknown().optional(),
    error: z.string().min(1).max(2000).optional(),
  })
  .refine((d) => d.error !== undefined || d.hasil !== undefined, {
    message: "Laporan harus memuat `hasil` atau `error`",
  });

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  if (!isAgentAuthorized(request)) return unauthorized();

  const { id } = await params;
  const parsed = Lapor.safeParse(await request.json().catch(() => null));
  if (!parsed.success) {
    return Response.json({ error: "Laporan tidak sah" }, { status: 400 });
  }

  const { hasil, error } = parsed.data;
  const gagal = typeof error === "string";
  const rows = await db
    .update(tugas)
    .set({
      status: gagal ? "failed" : "done",
      hasil: gagal ? null : (hasil ?? null),
      errorMessage: gagal ? error : null,
      finishedAt: new Date(),
    })
    // Hanya baris yang memang sedang dikerjakan. Tanpa penjaga status ini,
    // laporan yang terlambat datang dari daemon yang sudah dianggap mati akan
    // menimpa hasil yang sementara itu sudah dikerjakan daemon lain.
    .where(and(eq(tugas.id, id), eq(tugas.status, "processing")))
    .returning({ id: tugas.id });

  if (!rows.length) {
    return Response.json({ error: "Tugas tidak sedang dikerjakan" }, { status: 409 });
  }
  return Response.json({ ok: true });
}
