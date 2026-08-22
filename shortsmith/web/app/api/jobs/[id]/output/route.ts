import { eq } from "drizzle-orm";

import { db } from "@/db";
import { jobs } from "@/db/schema";
import { isAgentAuthorized, unauthorized } from "@/lib/auth";
import { buildKey, presignUpload } from "@/lib/storage";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Slot unggah tambahan untuk job yang menghasilkan LEBIH DARI SATU klip.
 *
 * ## Kenapa diminta satu per satu, bukan dikirim di muka
 *
 * `/api/jobs/next` menyertakan satu URL unggah karena saat job dibagikan,
 * belum ada yang tahu berapa klip yang akan lahir darinya. Jumlah itu baru
 * ditentukan setelah transkrip ada -- ia bergantung pada panjang rekaman dan
 * pada berapa topik berbeda yang benar-benar ditemukan di dalamnya.
 *
 * Menebak di muka berarti menerbitkan lima izin tulis untuk job yang mungkin
 * hanya menghasilkan satu, dan izin yang tidak terpakai tetap berlaku sampai
 * kedaluwarsa.
 *
 * ## Kenapa agent tidak membuat key-nya sendiri
 *
 * Aturan yang sama dengan seluruh jalur lain: agent tidak pernah memegang
 * kredensial storage. Ia meminta, server yang menandatangani. Membiarkan agent
 * menyusun key sendiri berarti memberinya kemampuan menulis ke mana pun di
 * dalam bucket, dan itu tidak dibutuhkan untuk pekerjaan ini.
 */
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!isAgentAuthorized(request)) return unauthorized();

  const { id } = await params;
  const [job] = await db.select().from(jobs).where(eq(jobs.id, id)).limit(1);
  if (!job) return Response.json({ error: "Job tidak ditemukan" }, { status: 404 });

  // Hanya job yang MASIH dikerjakan. Job yang sudah selesai atau gagal tidak
  // punya alasan menulis berkas baru, dan membiarkannya berarti sebuah key
  // agent yang bocor bisa dipakai menulis kapan saja setelahnya.
  if (job.status !== "processing") {
    return Response.json(
      { error: `Job berstatus ${job.status}, bukan processing` },
      { status: 409 },
    );
  }
  if (job.tipe !== "render" || !job.projectId) {
    return Response.json({ error: "Job ini bukan render" }, { status: 400 });
  }

  const key = buildKey("output", `${job.projectId}-${crypto.randomUUID()}.mp4`);
  return Response.json({ key, uploadUrl: await presignUpload(key, "video/mp4") });
}
