import { and, eq, ne } from "drizzle-orm";
import { z } from "zod";

import { db } from "@/db";
import { users } from "@/db/schema";
import { akunSekarang, sesiSekarang } from "@/lib/akun";
import { hashSandi, sandiCocok } from "@/lib/sandi";
import { hapusObjek } from "@/lib/storage";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Ubah profil akun sendiri.
 *
 * ## Kenapa semua perubahan lewat satu rute
 *
 * Username, email, foto, dan password semuanya menyunting satu baris yang sama,
 * dan semuanya butuh pemeriksaan kepemilikan yang sama persis. Memecahnya jadi
 * empat rute berarti menyalin pemeriksaan itu empat kali — dan pemeriksaan izin
 * yang disalin adalah tempat lubang keamanan tumbuh.
 *
 * ## Kenapa ganti password minta password lama
 *
 * Cookie sesi berumur dua minggu. Kalau perangkat yang sudah masuk bisa
 * mengganti password tanpa membuktikan tahu yang lama, siapa pun yang sempat
 * memakai komputer yang tidak terkunci bisa mengambil alih akunnya permanen —
 * dan pemiliknya terkunci di luar. Password lama membuat penguasaan sementara
 * atas perangkat tidak otomatis jadi penguasaan permanen atas akun.
 *
 * Email juga diperlakukan begitu, dengan alasan yang sama: email adalah
 * identitas yang dipakai untuk masuk.
 */

const Body = z.object({
  username: z.string().trim().min(1).max(40).optional(),
  email: z.string().email().max(254).optional(),
  avatarKey: z.string().max(500).nullable().optional(),
  passwordLama: z.string().max(200).optional(),
  passwordBaru: z.string().min(10).max(200).optional(),
});

export async function PATCH(request: Request) {
  const sesi = await sesiSekarang();
  const akun = await akunSekarang(sesi);

  if (!akun) {
    return Response.json(
      {
        error:
          sesi?.peran === "tamu"
            ? "Mode tamu tidak punya akun untuk diubah."
            : "Sesi ini tidak terhubung ke akun.",
      },
      { status: 403 },
    );
  }

  let body;
  try {
    body = Body.parse(await request.json());
  } catch {
    return Response.json(
      { error: "Isian tidak valid. Password baru minimal 10 karakter." },
      { status: 400 },
    );
  }

  const perubahan: Partial<typeof users.$inferInsert> = {};

  if (body.username !== undefined) perubahan.username = body.username;

  if (body.avatarKey !== undefined) perubahan.avatarKey = body.avatarKey;

  const gantiSensitif = body.email !== undefined || body.passwordBaru !== undefined;
  if (gantiSensitif) {
    // Hash diambil di sini, bukan lewat `akunSekarang`. Tipe `Akun` dipakai
    // halaman-halaman yang merendernya; menaruh hash password di dalamnya
    // berarti ia ikut terbawa ke tempat yang tidak pernah membutuhkannya.
    const [rahasia] = await db
      .select({ passwordHash: users.passwordHash })
      .from(users)
      .where(eq(users.id, akun.id))
      .limit(1);

    if (
      !body.passwordLama ||
      !rahasia ||
      !(await sandiCocok(body.passwordLama, rahasia.passwordHash))
    ) {
      await new Promise((r) => setTimeout(r, 400));
      return Response.json({ error: "Password sekarang salah" }, { status: 401 });
    }
  }

  if (body.email !== undefined) {
    const email = body.email.trim().toLowerCase();
    if (email !== akun.email) {
      const [bentrok] = await db
        .select({ id: users.id })
        .from(users)
        .where(and(eq(users.email, email), ne(users.id, akun.id)))
        .limit(1);
      if (bentrok) {
        return Response.json({ error: "Email itu sudah dipakai akun lain." }, { status: 409 });
      }
      perubahan.email = email;
    }
  }

  if (body.passwordBaru !== undefined) {
    perubahan.passwordHash = await hashSandi(body.passwordBaru);
  }

  if (Object.keys(perubahan).length === 0) {
    return Response.json({ ok: true, tidakAdaPerubahan: true });
  }

  await db.update(users).set(perubahan).where(eq(users.id, akun.id));

  // Foto lama dibuang SETELAH baris barunya tersimpan. Urutan sebaliknya bisa
  // menghapus berkas lalu gagal menyimpan, dan menyisakan baris yang menunjuk
  // ke sesuatu yang tidak ada lagi.
  if (body.avatarKey !== undefined && akun.avatarKey && akun.avatarKey !== body.avatarKey) {
    try {
      await hapusObjek([akun.avatarKey]);
    } catch {}
  }

  return Response.json({ ok: true });
}
