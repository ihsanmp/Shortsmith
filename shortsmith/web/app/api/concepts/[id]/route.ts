import { eq } from "drizzle-orm";
import { z } from "zod";

import { db } from "@/db";
import { hapusObjek } from "@/lib/storage";
import { assets, conceptProfiles, projects } from "@/db/schema";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

/**
 * Penyesuaian kecil tanpa video contoh baru.
 *
 * "Sama seperti Vlog cepat tapi 30 detik" diselesaikan dengan duplikat konsep dan
 * ubah satu angka. Itulah kenapa profile_json diedit sebagai data, bukan kode.
 */
const PatchBody = z.object({
  nama: z.string().min(1).max(120).optional(),
  isDefault: z.boolean().optional(),
  profileJson: z.record(z.unknown()).optional(),
});

export async function GET(_request: Request, { params }: Params) {
  const { id } = await params;
  const [row] = await db
    .select()
    .from(conceptProfiles)
    .where(eq(conceptProfiles.id, id))
    .limit(1);

  if (!row) return Response.json({ error: "Konsep tidak ditemukan" }, { status: 404 });
  return Response.json({ concept: row });
}

export async function PATCH(request: Request, { params }: Params) {
  const { id } = await params;

  let body;
  try {
    body = PatchBody.parse(await request.json());
  } catch (err) {
    return Response.json(
      { error: "Body tidak valid", detail: (err as Error).message },
      { status: 400 },
    );
  }

  if (body.isDefault) {
    await db.update(conceptProfiles).set({ isDefault: false });
  }

  const [row] = await db
    .update(conceptProfiles)
    .set({
      ...(body.nama !== undefined ? { nama: body.nama } : {}),
      ...(body.isDefault !== undefined ? { isDefault: body.isDefault } : {}),
      ...(body.profileJson !== undefined ? { profileJson: body.profileJson } : {}),
    })
    .where(eq(conceptProfiles.id, id))
    .returning();

  if (!row) return Response.json({ error: "Konsep tidak ditemukan" }, { status: 404 });
  return Response.json({ concept: row });
}

/** Duplikat konsep — jalur termurah untuk varian kecil. */
export async function POST(_request: Request, { params }: Params) {
  const { id } = await params;
  const [src] = await db
    .select()
    .from(conceptProfiles)
    .where(eq(conceptProfiles.id, id))
    .limit(1);

  if (!src) return Response.json({ error: "Konsep tidak ditemukan" }, { status: 404 });

  const [copy] = await db
    .insert(conceptProfiles)
    .values({
      nama: `${src.nama} (salinan)`,
      profileJson: src.profileJson,
      sampleVideoUrls: src.sampleVideoUrls,
      siap: src.siap,
      isDefault: false,
    })
    .returning();

  return Response.json({ concept: copy }, { status: 201 });
}

/**
 * Hapus konsep beserta video contohnya di storage.
 *
 * ## Kenapa project pemakai memblokir, bukan ikut terhapus
 *
 * `projects.concept_id` memakai `onDelete: "restrict"` — itu keputusan yang
 * disengaja. Konsep dipakai berulang, dan menghapusnya secara berantai akan
 * melenyapkan project beserta hasil rendernya hanya karena pengguna merapikan
 * daftar konsep. Kehilangan yang tidak diminta dan tidak bisa dibatalkan.
 *
 * Tanpa pemeriksaan di sini, database tetap menolak — tapi yang sampai ke
 * pengguna adalah kegagalan constraint yang tidak bisa ditindaklanjuti. Jadi
 * diperiksa lebih dulu, dan jumlah project pemakainya disebutkan.
 */
export async function DELETE(_request: Request, { params }: Params) {
  const { id } = await params;

  const [konsep] = await db
    .select({ nama: conceptProfiles.nama })
    .from(conceptProfiles)
    .where(eq(conceptProfiles.id, id));
  if (!konsep) {
    return Response.json({ error: "Konsep tidak ditemukan" }, { status: 404 });
  }

  const pemakai = await db
    .select({ id: projects.id, judul: projects.judul })
    .from(projects)
    .where(eq(projects.conceptId, id));
  if (pemakai.length > 0) {
    return Response.json(
      {
        error: `Konsep ini masih dipakai ${pemakai.length} project.`,
        detail:
          "Hapus project-nya lebih dulu, atau biarkan konsepnya — konsep yang " +
          "tidak dipilih tidak mengganggu apa pun.",
        projects: pemakai.slice(0, 5).map((p) => p.judul),
      },
      { status: 409 },
    );
  }

  // Video contoh dibersihkan LEBIH DULU. Kalau urutannya dibalik dan storage
  // gagal, key-nya sudah hilang dari database dan berkasnya jadi yatim:
  // menempati ruang selamanya tanpa ada cara menemukannya lagi.
  const contoh = await db
    .select({ storageKey: assets.storageKey, lokal: assets.lokal })
    .from(assets)
    .where(eq(assets.conceptId, id));

  let terhapus = 0;
  try {
    terhapus = await hapusObjek(contoh.filter((c) => !c.lokal).map((c) => c.storageKey));
  } catch (err) {
    return Response.json(
      { error: "Gagal menghapus video contoh di storage", detail: (err as Error).message },
      { status: 502 },
    );
  }

  // assets dan jobs milik konsep ini ikut terhapus lewat cascade di skema.
  await db.delete(conceptProfiles).where(eq(conceptProfiles.id, id));

  return Response.json({ ok: true, nama: konsep.nama, versiDihapus: terhapus });
}
