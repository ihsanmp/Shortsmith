import { z } from "zod";

import { isAgentAuthorized, unauthorized } from "@/lib/auth";
import { touchHeartbeat } from "@/lib/jobs";

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

const Body = z
  .object({
    progress: z.number().int().min(0).max(100).optional(),
    tahap: z.string().max(120).optional(),
  })
  .default({});

/**
 * Tanda agent masih hidup. Dikirim tiap 30 detik selama memproses.
 *
 * Respons `{ ok: false }` berarti job ini sudah tidak lagi milik agent — biasanya
 * karena ia sempat dianggap terlantar dan dikembalikan ke antrean. Agent harus
 * berhenti mengerjakannya supaya tidak ada dua proses merender job yang sama.
 */
export async function POST(request: Request, { params }: Params) {
  if (!isAgentAuthorized(request)) return unauthorized();

  const { id } = await params;

  let body: z.infer<typeof Body> = {};
  try {
    const text = await request.text();
    body = text ? Body.parse(JSON.parse(text)) : {};
  } catch {
    body = {};
  }

  const ok = await touchHeartbeat(id, body);
  return Response.json({ ok }, { status: ok ? 200 : 409 });
}
