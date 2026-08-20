import { eq } from "drizzle-orm";
import { z } from "zod";

import { db } from "@/db";
import { sessions, users } from "@/db/schema";
import { sandiCocok } from "@/lib/sandi";
import {
  COOKIE_NAME,
  SESSION_TTL_MS,
  createSessionToken,
  passwordCocok,
  type Peran,
} from "@/lib/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Tiga jalan masuk, satu rute.
 *
 *   1. `{ email, password }`  — akun terdaftar
 *   2. `{ password }`         — kata sandi bersama yang lama, tetap berlaku
 *   3. `{ tamu: true }`       — melihat-lihat, tanpa izin mengubah apa pun
 *
 * ## Kenapa kata sandi bersama tidak dimatikan
 *
 * Ia jaring pengaman. Kalau sistem akun barunya bermasalah — hash tidak cocok,
 * database tidak terjangkau saat login — masih ada jalan masuk yang tidak
 * bergantung pada tabel mana pun.
 *
 * ## Kenapa pesan gagalnya sama untuk email salah dan sandi salah
 *
 * Pesan yang berbeda mengubah form login jadi alat pemeriksa: siapa pun bisa
 * mencoba deretan email dan mengetahui mana yang terdaftar hanya dari kalimat
 * yang muncul. Satu kalimat untuk keduanya menutup itu.
 */

const Body = z.object({
  email: z.string().email().max(254).optional(),
  password: z.string().min(1).max(200).optional(),
  tamu: z.boolean().optional(),
});

const GAGAL = "Email atau password salah";

/** Jeda tetap untuk setiap kegagalan, memperlambat penebakan beruntun. */
async function jeda() {
  await new Promise((r) => setTimeout(r, 400));
}

function balasan(token: string) {
  const res = Response.json({ ok: true });
  res.headers.append(
    "set-cookie",
    [
      `${COOKIE_NAME}=${token}`,
      "Path=/",
      "HttpOnly",
      "SameSite=Lax",
      `Max-Age=${Math.floor(SESSION_TTL_MS / 1000)}`,
      // Vercel selalu HTTPS; di localhost Secure akan membuat cookie ditolak.
      process.env.NODE_ENV === "production" ? "Secure" : "",
    ]
      .filter(Boolean)
      .join("; "),
  );
  return res;
}

export async function POST(request: Request) {
  const sandiBersama = process.env.APP_PASSWORD?.trim();
  const secret = process.env.SESSION_SECRET?.trim();

  if (!sandiBersama || !secret) {
    return Response.json(
      { error: "APP_PASSWORD atau SESSION_SECRET belum diset di server." },
      { status: 500 },
    );
  }

  let body;
  try {
    body = Body.parse(await request.json());
  } catch {
    return Response.json({ error: "Permintaan tidak lengkap" }, { status: 400 });
  }

  // --- 3. Tamu ---
  if (body.tamu) {
    const peran: Peran = "tamu";
    return balasan(await createSessionToken(secret, { peran }));
  }

  if (!body.password) {
    return Response.json({ error: "Password wajib diisi" }, { status: 400 });
  }

  // --- 1. Akun terdaftar ---
  if (body.email) {
    const email = body.email.trim().toLowerCase();
    const [akun] = await db.select().from(users).where(eq(users.email, email)).limit(1);

    // Hash diverifikasi hanya kalau akunnya ada. Kalau tidak ada, jeda tetap
    // dijalankan supaya waktu balasannya tidak membedakan email terdaftar dari
    // yang tidak.
    if (!akun || !(await sandiCocok(body.password, akun.passwordHash))) {
      await jeda();
      return Response.json({ error: GAGAL }, { status: 401 });
    }

    // Kegagalan mencatat tidak boleh menggagalkan login itu sendiri — keduanya
    // catatan, bukan syarat. Sesi yang tidak tercatat hanya berarti perangkatnya
    // tidak muncul di daftar "Kelola akun"; ia tetap bisa dipakai.
    let sesiId: string | undefined;
    try {
      await db.update(users).set({ lastLoginAt: new Date() }).where(eq(users.id, akun.id));
      const [baris] = await db
        .insert(sessions)
        .values({
          userId: akun.id,
          userAgent: (request.headers.get("user-agent") ?? "").slice(0, 400),
        })
        .returning({ id: sessions.id });
      sesiId = baris?.id;
    } catch {}

    return balasan(await createSessionToken(secret, { userId: akun.id, sesiId }));
  }

  // --- 2. Kata sandi bersama ---
  if (!passwordCocok(body.password, sandiBersama)) {
    await jeda();
    return Response.json({ error: GAGAL }, { status: 401 });
  }

  return balasan(await createSessionToken(secret));
}

/** Logout: kosongkan cookie. */
export async function DELETE() {
  const res = Response.json({ ok: true });
  res.headers.append(
    "set-cookie",
    `${COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`,
  );
  return res;
}
