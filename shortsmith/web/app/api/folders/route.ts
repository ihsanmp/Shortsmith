import { eq } from "drizzle-orm";

import { db } from "@/db";
import { agentInfo } from "@/db/schema";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 30;

const KUNCI = "folder_bahan";

/**
 * Daftar folder bahan, untuk dropdown di form.
 *
 * Sengaja TERPISAH dari /api/agent/folders yang dipakai agent untuk melapor.
 * Rute agent harus melewati middleware sesi (ia memakai X-Agent-Key), dan kalau
 * GET ikut di sana, daftar folder di PC pengguna jadi bisa dibaca siapa saja
 * tanpa login. Memisahkannya membuat tiap arah dijaga oleh yang benar.
 */
export async function GET() {
  const [row] = await db
    .select()
    .from(agentInfo)
    .where(eq(agentInfo.kunci, KUNCI))
    .limit(1);

  if (!row) {
    return Response.json({ root: null, folders: [], updatedAt: null });
  }

  // Bentuknya divalidasi saat DITULIS di /api/agent/folders, jadi di sini cukup
  // dibaca apa adanya — menduplikasi skemanya hanya menciptakan dua definisi
  // yang bisa berbeda diam-diam.
  const data = row.data as {
    root: string;
    folders: {
      path: string;
      jumlahVideo: number;
      berkas: { nama: string; ukuranBytes: number }[];
    }[];
  };
  return Response.json({ ...data, updatedAt: row.updatedAt });
}
