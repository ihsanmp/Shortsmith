import { desc, eq } from "drizzle-orm";
import { z } from "zod";

import { db } from "@/db";
import { assets, conceptProfiles, jobs } from "@/db/schema";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MIN_SAMPEL = 2;

const CreateBody = z.object({
  nama: z.string().min(1).max(120),
  /**
   * Minimal dua video contoh. Satu video adalah sampel n=1: kalau ritmenya
   * kebetulan tidak mewakili gaya asli, seluruh konsep jadi miring dan sulit
   * dilacak penyebabnya. Dengan beberapa video kita bisa menghitung rata-rata
   * DAN standar deviasi — dan deviasi itu sendiri informatif.
   */
  sampleKeys: z.array(z.string().min(1)).min(MIN_SAMPEL).max(4),
  aspectRatio: z.enum(["auto", "9:16", "4:5", "3:4", "1:1", "16:9"]).default("auto"),

});

export async function GET(request: Request) {
  // `?semua=1` untuk halaman pengelolaan konsep, yang harus tetap melihat yang
  // diarsipkan supaya bisa mengembalikannya. Tanpa itu, mengarsipkan berarti
  // kehilangan cara membatalkannya.
  const semua = new URL(request.url).searchParams.get("semua") === "1";

  const rows = await db
    .select({
      id: conceptProfiles.id,
      nama: conceptProfiles.nama,
      siap: conceptProfiles.siap,
      isDefault: conceptProfiles.isDefault,
      arsip: conceptProfiles.arsip,
      profileJson: conceptProfiles.profileJson,
      createdAt: conceptProfiles.createdAt,
    })
    .from(conceptProfiles)
    .orderBy(desc(conceptProfiles.createdAt));

  return Response.json({ concepts: semua ? rows : rows.filter((r) => !r.arsip) });
}

export async function POST(request: Request) {
  let body;
  try {
    body = CreateBody.parse(await request.json());
  } catch (err) {
    return Response.json(
      { error: "Body tidak valid", detail: (err as Error).message },
      { status: 400 },
    );
  }

  // Profil awal kosong — akan diisi agent lewat job profile_extraction.
  const [concept] = await db
    .insert(conceptProfiles)
    .values({
      nama: body.nama,
      siap: false,
      sampleVideoUrls: body.sampleKeys,
      // `caption` dan `struktur` sengaja TIDAK ditulis di sini.
      //
      // Menuliskannya membuat agent mengira pengguna sudah memilih gaya caption
      // secara eksplisit, sehingga tahap "baca gaya dari video contoh" dilewati
      // sepenuhnya — dan konsep selalu lahir dengan frasa 4 kata di bawah, tidak
      // peduli seperti apa contohnya. Jalur pembuatan lewat halaman Project
      // sudah diperbaiki lebih dulu; jalur ini sempat tertinggal dan menghasilkan
      // gejala yang sama persis.
      profileJson: {
        nama: body.nama,
        versi: 1,
        metrik: {},
        aspect_ratio: body.aspectRatio,
        manual: { fokus: "" },
      },
    })
    .returning();

  await db.insert(assets).values(
    body.sampleKeys.map((key) => ({
      conceptId: concept.id,
      jenis: "sample" as const,
      storageKey: key,
      namaFile: key.split("/").pop() ?? key,
    })),
  );

  const [job] = await db
    .insert(jobs)
    .values({ conceptId: concept.id, tipe: "profile_extraction" })
    .returning({ id: jobs.id });

  return Response.json({ concept, jobId: job.id }, { status: 201 });
}

export async function DELETE(request: Request) {
  const id = new URL(request.url).searchParams.get("id");
  if (!id) return Response.json({ error: "Parameter id wajib" }, { status: 400 });

  await db.delete(conceptProfiles).where(eq(conceptProfiles.id, id));
  return Response.json({ ok: true });
}
