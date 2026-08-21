import { desc, eq } from "drizzle-orm";
import { z } from "zod";

import { db } from "@/db";
import { assets, conceptProfiles, jobs, projects } from "@/db/schema";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAKS_CONTOH = 4;
const MAKS_MENTAH = 10;

/**
 * Dua cara menentukan konsep, saling eksklusif:
 *
 *   conceptId   — pakai konsep yang sudah ada di pustaka, apa adanya
 *   konsepBaru  — unggah video contoh di sini, konsep BARU dibuat dari situ
 *
 * Yang kedua tidak pernah menimpa konsep lama. Tiap kali kamu mengirim video
 * contoh, lahir konsep baru; yang lama tetap utuh dan tetap bisa dipilih.
 */
const CreateBody = z
  .object({
    judul: z.string().max(200).default("Tanpa judul"),
    brief: z.string().max(4000).default(""),
    // Jenis video yang dituju. Menentukan rasio, durasi target, dan subtitle.
    jenis: z.enum(["short", "cinematic", "amv", "podcast"]).default("short"),
    // Rasio keluaran pilihan pengguna. "auto" = serahkan pada jenis dan konsep.
    rasio: z
      .enum(["auto", "9:16", "16:9", "1:1", "4:5", "3:4"])
      .default("auto"),
    // Lagu latar, opsional — kecuali untuk AMV, yang diperiksa di bawah.
    musik: z
      .object({
        key: z.string().default(""),
        namaFile: z.string().max(255),
        ukuranBytes: z.number().int().positive().optional(),
        lokal: z.boolean().default(false),
        bahanFolder: z.string().max(300).default(""),
      })
      .nullish(),
    // Beberapa video mentah per project. Agent menganalisis tiap file terpisah
    // dan boleh mencampur potongan dari mana pun di antaranya.
    rawKeys: z
      .array(
        z
          .object({
            // Kosong untuk berkas lokal — ia tidak pernah diunggah, jadi tidak
            // punya key di object storage.
            key: z.string().default(""),
            // Wajib: di mode lokal, inilah SATU-SATUNYA penunjuk berkas.
            namaFile: z.string().min(1).max(255),
            ukuranBytes: z.number().int().positive().optional(),
            lokal: z.boolean().default(false),
            // Subfolder di dalam folder bahan agent. Divalidasi lagi di sisi
            // agent — nilai ini datang dari jaringan dan menunjuk ke disk.
            bahanFolder: z
              .string()
              .max(300)
              .default("")
              .refine((v) => !v.includes("..") && !v.startsWith("/") && !v.includes(":"), {
                message: "Folder bahan tidak boleh absolut atau memuat '..'",
              }),
          })
          .refine((r) => r.lokal || r.key.length > 0, {
            message: "key wajib untuk berkas yang diunggah",
          }),
      )
      .min(1)
      .max(MAKS_MENTAH),
    conceptId: z.string().uuid().optional(),
    konsepBaru: z
      .object({
        nama: z.string().min(1).max(120),
        sampleKeys: z.array(z.string().min(1)).min(1).max(MAKS_CONTOH),
        // "auto" = ikuti rasio video contoh; selain itu, pilihan user menang.
        aspectRatio: z.enum(["auto", "9:16", "4:5", "3:4", "1:1", "16:9"]).default("auto"),
      })
      .optional(),
  })
  .refine((b) => Boolean(b.conceptId) !== Boolean(b.konsepBaru), {
    message: "Isi salah satu saja: conceptId atau konsepBaru",
  });

export async function GET() {
  const rows = await db
    .select({
      id: projects.id,
      judul: projects.judul,
      status: projects.status,
      brief: projects.brief,
      createdAt: projects.createdAt,
      conceptNama: conceptProfiles.nama,
    })
    .from(projects)
    .leftJoin(conceptProfiles, eq(projects.conceptId, conceptProfiles.id))
    .orderBy(desc(projects.createdAt))
    .limit(100);

  return Response.json({ projects: rows });
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

  let conceptId: string;
  let jobEkstraksi: string | null = null;

  if (body.konsepBaru) {
    // --- Jalur B: video contoh diunggah bersamaan dengan video mentah ---
    const [concept] = await db
      .insert(conceptProfiles)
      .values({
        nama: body.konsepBaru.nama,
        siap: false,
        sampleVideoUrls: body.konsepBaru.sampleKeys,
        // Hanya yang benar-benar DIPILIH pengguna yang ditulis di sini. Sisanya
        // sengaja dikosongkan supaya agent yang mengisinya dari video contoh
        // dan dari nilai bawaannya sendiri.
        //
        // Sebelumnya `caption` dan `struktur` ditulis hardcoded di baris ini,
        // dan itu menang atas apa pun yang agent tentukan — termasuk gaya
        // caption yang diukur dari video contoh. Akibatnya konsep tampak "tidak
        // terpakai": rasio dan ritme ikut contoh, tapi captionnya tetap frasa
        // 4 kata di bawah, karena angka itu datang dari sini, bukan dari
        // videonya.
        profileJson: {
          nama: body.konsepBaru.nama,
          versi: 1,
          metrik: {},
          aspect_ratio: body.konsepBaru.aspectRatio,
          gaya_bahasa: "",
          manual: { fokus: "" },
        },
      })
      .returning();

    await db.insert(assets).values(
      body.konsepBaru.sampleKeys.map((key, i) => ({
        conceptId: concept.id,
        jenis: "sample" as const,
        urutan: i,
        storageKey: key,
        namaFile: key.split("/").pop() ?? key,
      })),
    );

    const [job] = await db
      .insert(jobs)
      .values({ conceptId: concept.id, tipe: "profile_extraction" })
      .returning({ id: jobs.id });

    conceptId = concept.id;
    jobEkstraksi = job.id;
  } else {
    // --- Jalur A: konsep yang sudah ada, dipakai apa adanya ---
    const [concept] = await db
      .select({ id: conceptProfiles.id, siap: conceptProfiles.siap })
      .from(conceptProfiles)
      .where(eq(conceptProfiles.id, body.conceptId!))
      .limit(1);

    if (!concept) {
      return Response.json({ error: "Konsep tidak ditemukan" }, { status: 400 });
    }
    if (!concept.siap) {
      return Response.json(
        { error: "Konsep ini masih dianalisis. Tunggu sampai statusnya siap." },
        { status: 409 },
      );
    }
    conceptId = concept.id;
  }

  // AMV tanpa lagu tidak masuk akal: lagunya yang jadi jalur utama, bukan
  // latar. Diperiksa di sini, bukan hanya di form — form bisa dilewati, rute
  // ini tidak.
  if (body.jenis === "amv" && !body.musik) {
    return Response.json(
      { error: "AMV membutuhkan lagu. Pilih berkas audionya lebih dulu." },
      { status: 400 },
    );
  }

  const [project] = await db
    .insert(projects)
    .values({
      judul: body.judul,
      conceptId,
      brief: body.brief,
      jenis: body.jenis,
      rasio: body.rasio,
    })
    .returning();

  // Indeks array ditulis eksplisit ke kolom `urutan`. Jangan pernah bersandar
  // pada urutan insert atau created_at: batch insert memberi timestamp yang
  // sama ke semua baris, dan penentu berikutnya adalah UUID acak.
  await db.insert(assets).values(
    body.rawKeys.map((r, i) => ({
      projectId: project.id,
      jenis: "raw" as const,
      urutan: i,
      lokal: r.lokal,
      bahanFolder: r.bahanFolder,
      storageKey: r.key,
      namaFile: r.namaFile,
      ukuranBytes: r.ukuranBytes,
    })),
  );

  // Lagu disimpan sebagai aset terpisah berjenis `music`, bukan dititipkan ke
  // daftar `raw`. Kalau ikut di sana, agent akan memperlakukannya sebagai video
  // mentah — menganalisisnya, memecahnya jadi adegan, dan mencoba mengambil
  // gambar dari berkas yang tidak punya gambar.
  if (body.musik) {
    await db.insert(assets).values({
      projectId: project.id,
      jenis: "music" as const,
      urutan: 0,
      lokal: body.musik.lokal,
      bahanFolder: body.musik.bahanFolder,
      storageKey: body.musik.key,
      namaFile: body.musik.namaFile,
      ukuranBytes: body.musik.ukuranBytes,
    });
  }

  // Job render dibuat sekarang juga, tapi antrean tidak akan mengambilnya
  // sebelum konsepnya `siap` — penjaganya ada di claimNextJobSql().
  const [job] = await db
    .insert(jobs)
    .values({ projectId: project.id, conceptId, tipe: "render" })
    .returning({ id: jobs.id });

  return Response.json(
    { project, jobId: job.id, jobEkstraksi, conceptId },
    { status: 201 },
  );
}
