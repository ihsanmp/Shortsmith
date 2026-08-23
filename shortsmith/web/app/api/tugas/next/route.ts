import { isAgentAuthorized, unauthorized } from "@/lib/auth";
import { ambilTugas } from "@/lib/tugas";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Agent mengambil satu tugas dari antrean.
 *
 * Sejak `/api/jobs/next` ikut mengembalikan tugas, route ini TIDAK lagi dipakai
 * daemon versi baru — ia dipertahankan supaya agent versi lama, yang menanyakan
 * keduanya terpisah, tetap berjalan setelah server diperbarui.
 *
 * Isinya sengaja tipis: seluruh logikanya ada di lib/tugas.ts supaya kedua
 * jalur tidak bisa diam-diam berbeda aturannya.
 */
export async function GET(request: Request) {
  if (!isAgentAuthorized(request)) return unauthorized();
  return Response.json({ tugas: await ambilTugas() });
}
