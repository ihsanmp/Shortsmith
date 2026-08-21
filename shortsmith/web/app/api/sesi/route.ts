import { cookies } from "next/headers";
import { count, eq } from "drizzle-orm";

import { db } from "@/db";
import { conceptProfiles, projects, users } from "@/db/schema";
import { COOKIE_NAME, bacaIsiSesi } from "@/lib/session";
import { sentuhSesi } from "@/lib/akun";
import { presignDownload } from "@/lib/storage";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 30;

/**
 * Isi menu profil.
 *
 * ## Kenapa ini perlu rute server sama sekali
 *
 * Cookie sesinya `HttpOnly` — itu memang tujuannya, supaya skrip di halaman
 * tidak bisa membacanya kalau ada XSS. Konsekuensinya kapan sesi berakhir hanya
 * bisa diketahui dari server, meski angkanya sendiri tidak rahasia.
 *
 * ## Kenapa tanda tangannya tidak diperiksa lagi di sini
 *
 * Middleware sudah menolak permintaan tanpa cookie yang sah sebelum sampai ke
 * rute ini. Yang dilakukan di sini hanya membaca bagian kedaluwarsa dari token
 * yang sudah terbukti sah — memverifikasi ulang tidak menambah keamanan, hanya
 * menduplikasi satu-satunya tempat aturan itu seharusnya hidup.
 */
export async function GET() {
  const isi = bacaIsiSesi((await cookies()).get(COOKIE_NAME)?.value);

  const [{ n: jumlahProject }] = await db
    .select({ n: count() })
    .from(projects);
  const [{ n: jumlahKonsep }] = await db
    .select({ n: count() })
    .from(conceptProfiles);

  // Email hanya ada untuk sesi berbasis akun. Sesi kata sandi bersama dan sesi
  // tamu tidak punya, dan itu ditampilkan apa adanya — bukan diisi tebakan.
  let email: string | null = null;
  let username: string | null = null;
  let avatarUrl: string | null = null;
  if (isi?.userId) {
    const [akun] = await db
      .select({
        email: users.email,
        username: users.username,
        avatarKey: users.avatarKey,
      })
      .from(users)
      .where(eq(users.id, isi.userId))
      .limit(1);
    email = akun?.email ?? null;
    username = akun?.username ?? null;

    // Foto disimpan di bucket privat, jadi tiap tampilan butuh URL bertanda
    // tangan yang baru. Kegagalan menandatanganinya tidak boleh menjatuhkan
    // rute ini — yang hilang cuma fotonya, dan avatar bawaan menggantikannya.
    if (akun?.avatarKey) {
      try {
        avatarUrl = await presignDownload(akun.avatarKey);
      } catch {}
    }
  }

  // "Terakhir aktif" diperbarui DI SINI, bukan saat halaman dirender. Rute ini
  // dipanggil ketika menu profil dibuka — jarang, dan sudah menyentuh database
  // untuk hitungan di bawah. Menaruhnya di render halaman berarti setiap
  // kunjungan menanggung satu tulisan yang tidak dibutuhkan halaman itu.
  if (isi?.sesiId) await sentuhSesi(isi.sesiId);

  return Response.json({
    // null kalau cookie-nya berbentuk lain dari yang kita terbitkan, supaya
    // klien menampilkan "—" alih-alih "Invalid Date".
    berakhir: isi?.kedaluwarsa ?? null,
    peran: isi?.peran ?? "pemilik",
    email,
    username,
    avatarUrl,
    jumlahProject,
    jumlahKonsep,
  });
}
