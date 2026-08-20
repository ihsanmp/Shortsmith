import { eq } from "drizzle-orm";
import { z } from "zod";

import { db } from "@/db";
import { sessions, users } from "@/db/schema";
import { hashSandi } from "@/lib/sandi";
import { COOKIE_NAME, SESSION_TTL_MS, createSessionToken } from "@/lib/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Pendaftaran akun, terbuka.
 *
 * ## Apa artinya "terbuka" di sini
 *
 * Siapa pun yang mengetahui alamat Shortsmith ini bisa membuat akun dan
 * langsung punya akses penuh: melihat seluruh rekaman yang pernah diunggah,
 * membuat project, dan mengantre job ke agent yang berjalan di PC pemiliknya.
 * Tidak ada persetujuan, daftar izin, maupun verifikasi email di antaranya.
 *
 * Itu keputusan sadar pemiliknya, bukan kelalaian. Dicatat di sini supaya siapa
 * pun yang membaca rute ini nanti tahu bahwa tidak ada gerbang yang hilang —
 * memang tidak pernah ada.
 *
 * Yang paling mungkin dibutuhkan berikutnya kalau alamatnya sampai tersebar:
 * pembatasan laju per-IP, dan daftar email yang diizinkan.
 *
 * ## Kenapa panjang minimal 10, bukan 8
 *
 * Kata sandi di sini menjaga akses ke rekaman pribadi dan agent yang berjalan di
 * PC pengguna. Delapan karakter sudah lama berada dalam jangkauan penebakan
 * offline kalau hash-nya sampai bocor; sepuluh menaikkan biayanya beberapa orde
 * tanpa terasa lebih repot untuk diketik.
 */

const Body = z.object({
  email: z.string().email().max(254),
  password: z.string().min(10).max(200),
});

export async function POST(request: Request) {
  const secret = process.env.SESSION_SECRET?.trim();

  if (!secret) {
    return Response.json(
      { error: "SESSION_SECRET belum diset di server." },
      { status: 500 },
    );
  }

  let body;
  try {
    body = Body.parse(await request.json());
  } catch {
    return Response.json(
      { error: "Email harus valid dan password minimal 10 karakter." },
      { status: 400 },
    );
  }

  const email = body.email.trim().toLowerCase();

  const [sudahAda] = await db.select({ id: users.id }).from(users).where(eq(users.email, email)).limit(1);
  if (sudahAda) {
    // Ini memang memberi tahu bahwa sebuah email terdaftar di sini, dan dengan
    // pendaftaran terbuka siapa pun bisa memakainya untuk memeriksa satu per
    // satu. Alternatifnya — berpura-pura berhasil lalu diam-diam tidak membuat
    // apa-apa — membuat orang yang lupa pernah mendaftar terjebak: ia mengira
    // punya akun baru dengan password baru, padahal tidak.
    return Response.json({ error: "Email ini sudah terdaftar. Masuk saja." }, { status: 409 });
  }

  const [akun] = await db
    .insert(users)
    .values({ email, passwordHash: await hashSandi(body.password), lastLoginAt: new Date() })
    .returning({ id: users.id });

  let sesiId: string | undefined;
  try {
    const [baris] = await db
      .insert(sessions)
      .values({
        userId: akun.id,
        userAgent: (request.headers.get("user-agent") ?? "").slice(0, 400),
      })
      .returning({ id: sessions.id });
    sesiId = baris?.id;
  } catch {}

  const token = await createSessionToken(secret, { userId: akun.id, sesiId });
  const res = Response.json({ ok: true });
  res.headers.append(
    "set-cookie",
    [
      `${COOKIE_NAME}=${token}`,
      "Path=/",
      "HttpOnly",
      "SameSite=Lax",
      `Max-Age=${Math.floor(SESSION_TTL_MS / 1000)}`,
      process.env.NODE_ENV === "production" ? "Secure" : "",
    ]
      .filter(Boolean)
      .join("; "),
  );
  return res;
}
