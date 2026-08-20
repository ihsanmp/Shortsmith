import { z } from "zod";

import { db } from "@/db";
import { agentInfo } from "@/db/schema";
import { isAgentAuthorized, unauthorized } from "@/lib/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 30;

const KUNCI = "folder_bahan";

/**
 * Daftar folder bahan yang tersedia di PC agent.
 *
 * Hanya POST. Pembacaannya ada di /api/folders, yang dijaga sesi login —
 * lihat komentar di sana.
 *
 * Halaman web tidak bisa melihat disk pengguna, jadi tanpa endpoint ini
 * satu-satunya cara memilih folder adalah mengetik path secara manual — dan
 * salah ketik baru ketahuan sepuluh menit kemudian saat job gagal.
 */
const Body = z.object({
  root: z.string().max(500),
  // Subfolder relatif terhadap root. String kosong berarti root itu sendiri.
  folders: z
    .array(
      z.object({
        path: z.string().max(300),
        jumlahVideo: z.number().int().nonnegative(),
        berkas: z
          .array(
            z.object({
              nama: z.string().max(255),
              ukuranBytes: z.number().int().nonnegative(),
            }),
          )
          .max(100)
          .default([]),
      }),
    )
    .max(200),
});

export async function POST(request: Request) {
  if (!isAgentAuthorized(request)) return unauthorized();

  let body;
  try {
    body = Body.parse(await request.json());
  } catch (err) {
    return Response.json(
      { error: "Body tidak valid", detail: (err as Error).message },
      { status: 400 },
    );
  }

  await db
    .insert(agentInfo)
    .values({ kunci: KUNCI, data: body })
    .onConflictDoUpdate({
      target: agentInfo.kunci,
      set: { data: body, updatedAt: new Date() },
    });

  return Response.json({ ok: true, jumlah: body.folders.length });
}
