import { eq } from "drizzle-orm";
import { z } from "zod";

import { db } from "@/db";
import { jobs } from "@/db/schema";
import { isAgentAuthorized, unauthorized } from "@/lib/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 30;

/**
 * Pilihan topik untuk job yang kolom topiknya dikosongkan pengguna.
 *
 * Tiga pintu, tiga pemakai yang berbeda:
 *
 *   POST  agent  — menaruh daftar topik yang ia temukan di rekaman
 *   GET   agent  — menanyakan apakah pengguna sudah mencentang
 *   PATCH web    — pengguna mengirim centangannya
 *
 * ## Kenapa agent menanyakan, bukan diberi tahu
 *
 * Agent berjalan di PC pengguna, di belakang router rumahan. Tidak ada alamat
 * yang bisa dihubungi server, dan membuka satu berarti meminta pengguna
 * mengurus port forwarding untuk sesuatu yang cuma dipakai sekali per job.
 * Menanyakan tiap beberapa detik jauh lebih murah daripada itu, dan job ini
 * memang sedang tidak mengerjakan apa pun sambil menunggu.
 *
 * ## Kenapa PATCH tidak memakai token agent
 *
 * Yang mencentang adalah orang di peramban, bukan agent. Ia sudah lolos
 * middleware sesi untuk sampai ke halaman project-nya, dan menuntut token agent
 * di sini berarti menaruh kredensial mesin di dalam JavaScript halaman — satu
 * cara paling mudah membocorkannya.
 */

type Params = { params: Promise<{ id: string }> };

const MAKS_TOPIK = 12;
const Daftar = z.array(z.string().trim().min(1).max(400)).max(MAKS_TOPIK);

/** Agent menaruh topik yang ia temukan. */
export async function POST(request: Request, { params }: Params) {
  if (!isAgentAuthorized(request)) return unauthorized();
  const { id } = await params;

  let usul: string[];
  try {
    usul = Daftar.parse((await request.json())?.topik);
  } catch {
    return Response.json({ error: "Daftar topik tidak valid" }, { status: 400 });
  }

  // `topikPilih` dinolkan bersamaan. Kalau job ini diulang, pilihan lama harus
  // ikut hangus — kalau tidak, agent langsung membaca centangan untuk daftar
  // topik yang sudah tidak ada lagi.
  const [row] = await db
    .update(jobs)
    .set({ topikUsul: usul, topikPilih: null })
    .where(eq(jobs.id, id))
    .returning({ id: jobs.id });

  if (!row) return Response.json({ error: "Job tidak ada" }, { status: 404 });
  return Response.json({ ok: true, jumlah: usul.length });
}

/** Agent menanyakan apakah sudah dicentang. `pilih: null` berarti belum. */
export async function GET(request: Request, { params }: Params) {
  if (!isAgentAuthorized(request)) return unauthorized();
  const { id } = await params;

  const [row] = await db
    .select({ usul: jobs.topikUsul, pilih: jobs.topikPilih, status: jobs.status })
    .from(jobs)
    .where(eq(jobs.id, id));

  if (!row) return Response.json({ error: "Job tidak ada" }, { status: 404 });
  return Response.json({
    usul: row.usul ?? [],
    pilih: row.pilih ?? null,
    status: row.status,
  });
}

/** Pengguna mengirim centangannya. */
export async function PATCH(request: Request, { params }: Params) {
  const { id } = await params;

  let pilih: string[];
  try {
    pilih = Daftar.parse((await request.json())?.topik);
  } catch {
    return Response.json({ error: "Pilihan topik tidak valid" }, { status: 400 });
  }

  const [job] = await db
    .select({ usul: jobs.topikUsul, pilih: jobs.topikPilih })
    .from(jobs)
    .where(eq(jobs.id, id));

  if (!job) return Response.json({ error: "Job tidak ada" }, { status: 404 });
  if (job.pilih) {
    // Bukan galat: dua tab terbuka, atau tombol ditekan dua kali. Yang pertama
    // sudah dipakai agent, dan menimpanya sekarang berarti agent merender topik
    // yang berbeda dari yang ditampilkan sebagai terpilih.
    return Response.json({ ok: true, sudah: true, topik: job.pilih });
  }

  // Hanya topik yang MEMANG diusulkan yang diterima. Tanpa saringan ini, badan
  // permintaan bisa menyuntikkan kalimat apa pun sebagai arahan penyuntingan,
  // dan arahan itu diteruskan mentah-mentah ke model di PC pengguna.
  const sah = new Set(job.usul ?? []);
  const bersih = pilih.filter((t) => sah.has(t));
  if (bersih.length !== pilih.length) {
    return Response.json(
      { error: "Ada topik yang bukan bagian dari usulan job ini" },
      { status: 400 },
    );
  }

  await db.update(jobs).set({ topikPilih: bersih }).where(eq(jobs.id, id));
  return Response.json({ ok: true, topik: bersih });
}
