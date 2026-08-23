import { z } from "zod";

import { db } from "@/db";
import { tugas } from "@/db/schema";
import { sesiSekarang } from "@/lib/akun";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Membuat permintaan singkat ke agent: menulis prompt, atau memeriksa klip.
 *
 * ## Kenapa lewat antrean, bukan dikerjakan di sini
 *
 * Yang mengerjakan adalah Claude di PC pengguna lewat `claude -p`. Itu satu
 * satunya jalur yang tidak menagih apa pun — ia ikut langganan Claude yang
 * sudah dibayar. Server ini tidak punya, dan sengaja tidak diberi, kunci API
 * Anthropic.
 *
 * Ongkosnya kelihatan di kecepatan: daemon menyahut tiap 10 detik dan
 * `claude -p` sendiri makan puluhan detik. Form yang memanggil ini HARUS
 * menunjukkan bahwa ia sedang menunggu, bukan diam seolah tidak terjadi apa-apa.
 */

const BATAS_PROMPT = 5;

const Buat = z.discriminatedUnion("tipe", [
  z.object({
    tipe: z.literal("prompt"),
    jenis: z.enum(["short", "cinematic", "podcast"]),
    tema: z.string().max(500).default(""),
    /**
     * Berapa prompt yang diminta. Dibatasi lima karena itulah jumlah kartu di
     * form; meminta lebih banyak menghasilkan prompt yang tidak punya tempat
     * untuk ditampilkan.
     */
    jumlah: z.number().int().min(1).max(BATAS_PROMPT),
    durasi: z.number().min(1).max(60).default(8),
    /** Nama bahan yang sudah dipilih, supaya Claude tidak mengulang yang ada. */
    sudahAda: z.array(z.string().max(255)).max(40).default([]),
  }),
  z.object({
    tipe: z.literal("review"),
    jenis: z.enum(["short", "cinematic", "podcast"]),
    /** Klip hasil generate yang sudah diunggah, beserta prompt asalnya. */
    klip: z
      .array(
        z.object({
          key: z.string().min(1).max(400),
          nama: z.string().min(1).max(255),
          prompt: z.string().max(2000).default(""),
        }),
      )
      .min(1)
      .max(BATAS_PROMPT),
    /**
     * Bahan pembanding. Boleh KOSONG — di mode folder lokal, bahannya tidak
     * pernah menyentuh server sama sekali. Pemeriksaan eksposurnya dilewati
     * dan yang tersisa penilaian isi; itu lebih jujur daripada membandingkan
     * dengan angka yang dikarang.
     */
    bahan: z
      .array(
        z.object({
          key: z.string().default(""),
          nama: z.string().max(255),
          /**
           * Subfolder di dalam `bahan/` untuk berkas mode lokal. Bahan sekarang
           * tersimpan per jenis (Short, Cinematic, Podcast, B-roll), jadi
           * nama saja tidak cukup untuk menemukannya.
           */
          folder: z.string().max(120).default(""),
        }),
      )
      .max(10)
      .default([]),
  }),
]);

export async function POST(request: Request) {
  const sesi = await sesiSekarang();
  // Tamu tidak boleh memakai ini. Bukan sekadar soal hak baca: tiap permintaan
  // menjalankan `claude -p` di PC pemilik agent, jadi membiarkannya terbuka
  // berarti siapa pun bisa memakai langganan Claude orang lain.
  if (!sesi || sesi.peran === "tamu" || !sesi.userId) {
    return Response.json({ error: "Perlu masuk dengan akun" }, { status: 403 });
  }

  const parsed = Buat.safeParse(await request.json().catch(() => null));
  if (!parsed.success) {
    return Response.json(
      { error: parsed.error.issues[0]?.message ?? "Permintaan tidak sah" },
      { status: 400 },
    );
  }

  const { tipe, ...permintaan } = parsed.data;
  const [baris] = await db
    .insert(tugas)
    .values({ tipe, permintaan, userId: sesi.userId })
    .returning({ id: tugas.id });

  return Response.json({ id: baris.id, status: "pending" }, { status: 201 });
}
