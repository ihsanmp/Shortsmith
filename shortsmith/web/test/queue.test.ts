/**
 * Uji SQL antrean terhadap Postgres sungguhan (PGlite = Postgres dikompilasi ke WASM).
 *
 * Yang dieksekusi di sini adalah query yang SAMA PERSIS dengan yang dikirim ke
 * produksi â€” diimpor dari lib/queue-sql.ts, bukan disalin ulang.
 *
 *   npx tsx test/queue.test.ts
 */
import { PGlite } from "@electric-sql/pglite";
import { sql, type SQL } from "drizzle-orm";
import { drizzle } from "drizzle-orm/pglite";

import {
  claimNextJobSql,
  finishJobSql,
  queuePositionSql,
  reapStaleJobsSql,
  touchHeartbeatSql,
} from "../lib/queue-sql";

let lulus = 0;
let gagal = 0;

function cek(nama: string, kondisi: boolean, detail = "") {
  if (kondisi) {
    lulus++;
    console.log(`  ok    ${nama}`);
  } else {
    gagal++;
    console.log(`  GAGAL ${nama}  ${detail}`);
  }
}

const DDL = `
CREATE TYPE job_status AS ENUM ('pending','processing','done','failed');
CREATE TYPE job_type   AS ENUM ('render','profile_extraction');

CREATE TABLE concept_profiles (
  id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  nama  text NOT NULL DEFAULT '',
  siap  boolean NOT NULL DEFAULT false
);

CREATE TABLE jobs (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id    uuid,
  concept_id    uuid,
  tipe          job_type   NOT NULL,
  status        job_status NOT NULL DEFAULT 'pending',
  progress      integer    NOT NULL DEFAULT 0,
  tahap         text       NOT NULL DEFAULT '',
  error_message text,
  retry_count   integer    NOT NULL DEFAULT 0,
  heartbeat_at  timestamptz,
  started_at    timestamptz,
  finished_at   timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);
`;

async function main() {
  const client = new PGlite();
  const db = drizzle(client);
  await client.exec(DDL);

  /**
   * Driver postgres-js (produksi) mengembalikan array baris langsung; driver
   * pglite membungkusnya dalam { rows }. SQL-nya identik â€” hanya cara membaca
   * hasilnya yang berbeda, jadi normalisasi cukup di sisi test.
   */
  async function q<T>(statement: SQL): Promise<T[]> {
    const hasil = (await db.execute(statement)) as unknown;
    if (Array.isArray(hasil)) return hasil as T[];
    return ((hasil as { rows?: T[] }).rows ?? []) as T[];
  }

  async function buat(
    opts: { umur?: string; status?: string; retry?: number } = {},
  ): Promise<string> {
    const rows = await q<{ id: string }>(sql`
      INSERT INTO jobs (tipe, status, retry_count, created_at)
      VALUES ('render',
              ${opts.status ?? "pending"}::job_status,
              ${opts.retry ?? 0},
              now() - ${opts.umur ?? "0 seconds"}::interval)
      RETURNING id
    `);
    return rows[0].id;
  }

  // ---- 1. FIFO + transisi status ----
  console.log("\n1. claim mengambil job tertua dan menandainya processing");
  const lama = await buat({ umur: "60 seconds" });
  const baru = await buat({ umur: "10 seconds" });

  const c1 = await q<{ id: string }>(claimNextJobSql());
  cek("mengambil job tertua lebih dulu", c1[0]?.id === lama, `dapat ${c1[0]?.id}`);

  const s1 = await q<{ status: string; tahap: string }>(
    sql`SELECT status, tahap FROM jobs WHERE id = ${lama}`,
  );
  cek("status jadi processing", s1[0].status === "processing", s1[0].status);
  cek("tahap terisi", s1[0].tahap === "diambil agent", s1[0].tahap);

  // ---- 2. tidak diambil dua kali ----
  console.log("\n2. job yang sedang processing tidak diambil dua kali");
  const c2 = await q<{ id: string }>(claimNextJobSql());
  cek("claim kedua dapat job BERBEDA", c2[0]?.id === baru, `dapat ${c2[0]?.id}`);

  const c3 = await q<{ id: string }>(claimNextJobSql());
  cek("claim ketiga kosong (antrean habis)", c3.length === 0, `${c3.length} baris`);

  // ---- 3. heartbeat ----
  console.log("\n3. heartbeat");
  const hb = await q(touchHeartbeatSql(lama, { progress: 42, tahap: "render" }));
  cek("heartbeat job processing diterima", hb.length === 1);

  const s3 = await q<{ progress: number; tahap: string }>(
    sql`SELECT progress, tahap FROM jobs WHERE id = ${lama}`,
  );
  cek("progress tersimpan", Number(s3[0].progress) === 42, String(s3[0].progress));

  const pending = await buat({ status: "pending" });
  const hb2 = await q(touchHeartbeatSql(pending, { progress: 10 }));
  cek("heartbeat job non-processing DITOLAK", hb2.length === 0, `${hb2.length} baris`);

  // ---- 4. reaper ----
  console.log("\n4. reaper mengembalikan job terlantar (heartbeat > 5 menit)");
  const terlantar = await buat({ status: "processing" });
  await q(sql`UPDATE jobs SET heartbeat_at = now() - interval '9 minutes'
              WHERE id = ${terlantar}`);

  const r1 = await q<{ id: string; status: string }>(reapStaleJobsSql());
  const dipungut = r1.find((r) => r.id === terlantar);
  cek("job terlantar dipungut", Boolean(dipungut), JSON.stringify(r1));
  cek("dikembalikan ke pending, bukan failed", dipungut?.status === "pending",
      String(dipungut?.status));

  const s4 = await q<{ retry_count: number; heartbeat_at: string | null }>(
    sql`SELECT retry_count, heartbeat_at FROM jobs WHERE id = ${terlantar}`,
  );
  cek("retry_count naik jadi 1", Number(s4[0].retry_count) === 1, String(s4[0].retry_count));
  cek("heartbeat dibersihkan", s4[0].heartbeat_at === null);

  const segar = await buat({ status: "processing" });
  await q(sql`UPDATE jobs SET heartbeat_at = now() WHERE id = ${segar}`);
  const r2 = await q<{ id: string }>(reapStaleJobsSql());
  cek("job dengan heartbeat segar TIDAK dipungut", !r2.some((r) => r.id === segar));

  // ---- 5. reaper menyerah setelah batas retry ----
  console.log("\n5. reaper menandai gagal permanen setelah batas percobaan");
  const habis = await buat({ status: "processing", retry: 2 });
  await q(sql`UPDATE jobs SET heartbeat_at = now() - interval '9 minutes'
              WHERE id = ${habis}`);

  const r3 = await q<{ id: string; status: string }>(reapStaleJobsSql());
  const mati = r3.find((r) => r.id === habis);
  cek("retry habis -> failed", mati?.status === "failed", String(mati?.status));

  const s5 = await q<{ error_message: string | null; finished_at: string | null }>(
    sql`SELECT error_message, finished_at FROM jobs WHERE id = ${habis}`,
  );
  cek("pesan error diisi", (s5[0].error_message ?? "").includes("berhenti merespons"),
      String(s5[0].error_message));
  cek("finished_at diisi", s5[0].finished_at !== null);

  // ---- 6. finishJob ----
  console.log("\n6. finishJob");
  const sukses = await buat({ status: "processing" });
  const f1 = await q<{ status: string }>(finishJobSql(sukses, "done", null));
  cek("done -> done", f1[0].status === "done", f1[0].status);

  const s6 = await q<{ progress: number }>(
    sql`SELECT progress FROM jobs WHERE id = ${sukses}`,
  );
  cek("progress diset 100", Number(s6[0].progress) === 100, String(s6[0].progress));

  const g1 = await buat({ status: "processing", retry: 0 });
  const f2 = await q<{ status: string; retry_count: number }>(
    finishJobSql(g1, "failed", "ffmpeg meledak"),
  );
  cek("gagal pertama -> kembali ke pending", f2[0].status === "pending", f2[0].status);
  cek("retry_count naik", Number(f2[0].retry_count) === 1, String(f2[0].retry_count));

  const g3 = await buat({ status: "processing", retry: 2 });
  const f3 = await q<{ status: string }>(finishJobSql(g3, "failed", "menyerah"));
  cek("gagal setelah batas -> failed permanen", f3[0].status === "failed", f3[0].status);

  // ---- 7. render menunggu konsepnya siap ----
  console.log("\n7. job render tidak diambil sebelum konsepnya siap");
  await q(sql`DELETE FROM jobs`);

  const belum = (await q<{ id: string }>(sql`
    INSERT INTO concept_profiles (nama, siap) VALUES ('belum', false) RETURNING id`))[0].id;

  const jobProfil = (await q<{ id: string }>(sql`
    INSERT INTO jobs (tipe, concept_id, created_at)
    VALUES ('profile_extraction', ${belum}, now() - interval '10 seconds') RETURNING id`))[0].id;
  const jobRender = (await q<{ id: string }>(sql`
    INSERT INTO jobs (tipe, concept_id, created_at)
    VALUES ('render', ${belum}, now() - interval '5 seconds') RETURNING id`))[0].id;

  const a1 = await q<{ id: string; tipe: string }>(claimNextJobSql());
  cek("yang diambil pertama adalah profile_extraction", a1[0]?.id === jobProfil,
      `dapat ${a1[0]?.tipe}`);

  const a2 = await q<{ id: string }>(claimNextJobSql());
  cek("render DILEWATI selama konsep belum siap", a2.length === 0,
      `malah dapat ${a2.length} job`);

  await q(sql`UPDATE concept_profiles SET siap = true WHERE id = ${belum}`);
  const a3 = await q<{ id: string }>(claimNextJobSql());
  cek("setelah konsep siap, render baru diambil", a3[0]?.id === jobRender,
      `dapat ${a3[0]?.id}`);

  // job render tanpa konsep sama sekali tetap boleh jalan
  await q(sql`DELETE FROM jobs`);
  const lepas = (await q<{ id: string }>(sql`
    INSERT INTO jobs (tipe, concept_id) VALUES ('render', NULL) RETURNING id`))[0].id;
  const a4 = await q<{ id: string }>(claimNextJobSql());
  cek("render tanpa concept_id tetap bisa diambil", a4[0]?.id === lepas);

  // ---- 8. posisi antrean ----
  console.log("\n8. posisi antrean");
  await q(sql`DELETE FROM jobs`);
  await buat({ umur: "30 seconds" });
  await buat({ umur: "20 seconds" });
  const q3 = await buat({ umur: "10 seconds" });
  const pos = await q<{ posisi: number }>(queuePositionSql(q3));
  cek("job ketiga punya 2 job di depannya", Number(pos[0].posisi) === 2,
      `posisi=${pos[0].posisi}`);

  // Job yang SEDANG dikerjakan harus ikut dihitung. Sebelumnya tidak, sehingga
  // job yang menunggu di belakang satu job berjalan terbaca berposisi nol --
  // dan halaman project menuduh agent-nya mati padahal ia sedang sibuk.
  await q(sql`DELETE FROM jobs`);
  await buat({ umur: "30 seconds" });
  await q<{ id: string }>(claimNextJobSql());
  const q5 = await buat({ umur: "10 seconds" });
  const pos2 = await q<{ posisi: number }>(queuePositionSql(q5));
  cek("job di belakang job yang sedang jalan berposisi 1",
      Number(pos2[0].posisi) === 1, `posisi=${pos2[0].posisi}`);

  await client.close();

  console.log(`\n${lulus} lolos, ${gagal} gagal`);
  process.exit(gagal === 0 ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
