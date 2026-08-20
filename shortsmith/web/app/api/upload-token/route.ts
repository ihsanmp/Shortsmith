import { z } from "zod";

import { buildKey, presignUpload } from "@/lib/storage";

export const runtime = "nodejs";

const Body = z.object({
  filename: z.string().min(1).max(255),
  contentType: z.string().min(1).max(200),
  prefix: z.enum(["raw", "sample", "music", "avatar"]).default("raw"),
  ukuranBytes: z.number().int().positive().max(8 * 1024 * 1024 * 1024).optional(),
});

/**
 * Terbitkan presigned URL untuk upload langsung dari browser ke object storage.
 *
 * Video besar tidak boleh melewati serverless function: batas body Vercel ~4.5 MB,
 * dan durasi eksekusinya terbatas. Route ini hanya menandatangani URL dan mencatat
 * niat upload — byte-nya mengalir langsung browser -> storage.
 */
export async function POST(request: Request) {
  let parsed;
  try {
    parsed = Body.parse(await request.json());
  } catch (err) {
    return Response.json(
      { error: "Body tidak valid", detail: (err as Error).message },
      { status: 400 },
    );
  }

  const key = buildKey(parsed.prefix, parsed.filename);
  const uploadUrl = await presignUpload(key, parsed.contentType);

  return Response.json({ key, uploadUrl, expiresIn: 1800 });
}
