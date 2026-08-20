import { cookies } from "next/headers";
import { and, eq, lt, sql } from "drizzle-orm";

import { db } from "@/db";
import { sessions, users } from "@/db/schema";
import { presignDownload } from "@/lib/storage";
import { COOKIE_NAME, bacaIsiSesi, type IsiSesi } from "@/lib/session";

/**
 * Pembacaan akun yang dipakai bersama oleh halaman profil dan rute API-nya.
 *
 * Dikumpulkan di satu tempat karena tiga halaman membutuhkan bentuk data yang
 * sama persis. Menyalinnya ke tiap halaman berarti tiga tempat yang harus ikut
 * berubah setiap kali ada kolom baru — dan yang ketiga selalu yang terlupakan.
 */

export type Akun = {
  id: string;
  email: string;
  username: string;
  avatarKey: string | null;
  /** URL bertanda tangan untuk foto profil; null kalau belum ada fotonya. */
  avatarUrl: string | null;
  createdAt: Date;
};

export async function sesiSekarang(): Promise<IsiSesi | null> {
  return bacaIsiSesi((await cookies()).get(COOKIE_NAME)?.value);
}

/**
 * Akun yang sedang masuk, atau `null` untuk sesi tamu maupun sesi kata sandi
 * bersama — keduanya memang tidak terikat ke akun mana pun.
 */
export async function akunSekarang(isi?: IsiSesi | null): Promise<Akun | null> {
  const sesi = isi === undefined ? await sesiSekarang() : isi;
  if (!sesi?.userId) return null;

  const [baris] = await db
    .select({
      id: users.id,
      email: users.email,
      username: users.username,
      avatarKey: users.avatarKey,
      createdAt: users.createdAt,
    })
    .from(users)
    .where(eq(users.id, sesi.userId))
    .limit(1);

  if (!baris) return null;

  // Foto disimpan di bucket privat, jadi tiap tampilan butuh URL bertanda
  // tangan yang baru. Kegagalan menandatanganinya tidak boleh menjatuhkan
  // halaman — yang hilang cuma fotonya, dan avatar bawaan menggantikannya.
  let avatarUrl: string | null = null;
  if (baris.avatarKey) {
    try {
      avatarUrl = await presignDownload(baris.avatarKey);
    } catch {}
  }

  return { ...baris, avatarUrl };
}

/**
 * Nama browser dan sistem operasi dari User-Agent.
 *
 * Sengaja kasar. Yang dibutuhkan halaman "Kelola akun" hanya cukup untuk
 * pengguna mengenali perangkatnya sendiri di antara beberapa baris — bukan
 * ketepatan versi. Menambah pustaka parser User-Agent untuk itu adalah ongkos
 * yang tidak sebanding.
 */
export function bacaPerangkat(ua: string): { browser: string; sistem: string } {
  const browser = /Edg\//.test(ua)
    ? "Edge"
    : /OPR\/|Opera/.test(ua)
      ? "Opera"
      : /Firefox\//.test(ua)
        ? "Firefox"
        : /Chrome\//.test(ua)
          ? "Chrome"
          : /Safari\//.test(ua)
            ? "Safari"
            : "Browser lain";

  const sistem = /Windows NT/.test(ua)
    ? "Windows"
    : /Android/.test(ua)
      ? "Android"
      : /iPhone|iPad|iPod/.test(ua)
        ? "iOS"
        : /Mac OS X/.test(ua)
          ? "macOS"
          : /Linux/.test(ua)
            ? "Linux"
            : "Sistem lain";

  return { browser, sistem };
}

/**
 * Perbarui "terakhir aktif" untuk sesi ini, paling sering sekali per jam.
 *
 * ## Kenapa ada ambang satu jam
 *
 * Tanpa itu, setiap perpindahan halaman menulis satu baris ke database untuk
 * mengubah stempel waktu beberapa detik — beban tulis yang terus-menerus demi
 * ketelitian yang tidak ada gunanya bagi siapa pun. Syaratnya diletakkan di
 * dalam WHERE, jadi Postgres yang memutuskan: kalau belum satu jam, perintahnya
 * tidak menyentuh baris mana pun sama sekali.
 *
 * ## Kenapa kegagalannya ditelan, DAN dibatasi waktunya
 *
 * Ini catatan, bukan syarat. Tapi menelan kegagalan saja tidak cukup: kueri
 * yang menggantung tidak pernah gagal, ia hanya tidak selesai. Fungsi ini
 * sempat dipanggil dengan `await` dari root layout, jadi satu tulisan yang
 * lambat menahan render SELURUH halaman — dan itu tampil sebagai tab yang
 * memuat tanpa henti, hanya bagi pengguna yang masuk pakai akun.
 *
 * Sekarang ia dipanggil dari rute API, bukan dari render halaman, dan tetap
 * diberi batas waktu. Dua lapis, karena satu lapis saja pernah terbukti kurang.
 */
const BATAS_SENTUH_MS = 2000;

export async function sentuhSesi(sesiId: string): Promise<void> {
  if (!sesiId) return;
  try {
    await Promise.race([
      db
        .update(sessions)
        .set({ lastSeenAt: new Date() })
        .where(
          and(
            eq(sessions.id, sesiId),
            lt(sessions.lastSeenAt, sql`now() - interval '1 hour'`),
          ),
        ),
      new Promise((r) => setTimeout(r, BATAS_SENTUH_MS)),
    ]);
  } catch {}
}
