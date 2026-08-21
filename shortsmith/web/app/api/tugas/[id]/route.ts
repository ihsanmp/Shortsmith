import { and, eq } from "drizzle-orm";

import { db } from "@/db";
import { tugas } from "@/db/schema";
import { sesiSekarang } from "@/lib/akun";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Dibaca berulang oleh form selama menunggu agent menyahut.
 *
 * Dijepit ke pemiliknya lewat `userId` di klausa WHERE, bukan diperiksa setelah
 * barisnya terbaca. Bedanya nyata: dengan filter di query, id milik orang lain
 * mengembalikan 404 yang sama persis dengan id yang memang tidak ada — tidak
 * ada cara membedakan "bukan punyamu" dari "tidak pernah ada".
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const sesi = await sesiSekarang();
  if (!sesi || sesi.peran === "tamu" || !sesi.userId) {
    return Response.json({ error: "Perlu masuk dengan akun" }, { status: 403 });
  }

  const [baris] = await db
    .select({
      id: tugas.id,
      tipe: tugas.tipe,
      status: tugas.status,
      hasil: tugas.hasil,
      error: tugas.errorMessage,
    })
    .from(tugas)
    .where(and(eq(tugas.id, id), eq(tugas.userId, sesi.userId)))
    .limit(1);

  if (!baris) return Response.json({ error: "Tidak ditemukan" }, { status: 404 });
  return Response.json(baris);
}
