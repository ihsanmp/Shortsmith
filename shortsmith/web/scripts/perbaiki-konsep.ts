/**
 * Perbaiki nilai konsep yang tersimpan dengan gaya lama.
 *
 * Perbaikan di kode hanya berlaku untuk konsep yang dibuat SESUDAHNYA — ia
 * tidak menyentuh baris yang sudah ada di database. Konsep `wake-up-call`
 * terlanjur menyimpan dua nilai yang salah:
 *
 *   - rasio 16:9, karena dua video contohnya beda rasio dan aturan pemenang
 *     seri baru dipasang setelah konsep ini dibuat
 *   - caption "frasa @ tengah-bawah", karena jalur pembuatan lewat halaman
 *     Konsep masih menuliskannya hardcoded saat itu
 *
 * Skrip ini hanya menyentuh dua field itu. Metrik hasil pengukuran —
 * penggal_suara, porsi_pembicara, durasi, ritme shot — tidak diubah sama sekali.
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.vercel.local", ".env.local"] });

const url = process.env.DATABASE_URL?.trim();
if (!url) {
  console.error("[X] DATABASE_URL tidak ada");
  process.exit(1);
}

const NAMA = process.argv[2] ?? "wake-up-call";
const sql = postgres(url, { max: 1, prepare: false, connect_timeout: 15 });

async function main() {
  const [row] = await sql<{ id: string; profile_json: Record<string, any> }[]>`
    SELECT id, profile_json FROM concept_profiles WHERE nama = ${NAMA} LIMIT 1
  `;
  if (!row) {
    console.error(`[X] konsep "${NAMA}" tidak ditemukan`);
    process.exitCode = 1;
    return;
  }

  const lama = row.profile_json ?? {};
  console.log(`konsep : ${NAMA}`);
  console.log(`sebelum: rasio=${lama.aspect_ratio}, caption=${lama.caption?.gaya} @ ${lama.caption?.posisi}`);

  const baru = {
    ...lama,
    aspect_ratio: "9:16",
    caption: {
      ...(lama.caption ?? {}),
      ada: true,
      posisi: "tengah",
      gaya: "kata-per-kata",
      huruf_besar: true,
    },
  };

  await sql`
    UPDATE concept_profiles SET profile_json = ${sql.json(baru)} WHERE id = ${row.id}
  `;

  // Dibaca ulang dari server. Menganggap UPDATE berhasil tanpa memeriksa adalah
  // cara kesalahan yang sama muncul lagi di render berikutnya.
  const [cek] = await sql<{ profile_json: Record<string, any> }[]>`
    SELECT profile_json FROM concept_profiles WHERE id = ${row.id}
  `;
  const p = cek.profile_json;
  console.log(`sesudah: rasio=${p.aspect_ratio}, caption=${p.caption?.gaya} @ ${p.caption?.posisi}`);
  console.log(`metrik utuh: penggal_suara=${p.metrik?.penggal_suara?.mean}, porsi_pembicara=${p.porsi_pembicara}`);
}

main()
  .catch((e) => {
    console.error("[X] gagal:", (e as Error).message);
    process.exitCode = 1;
  })
  .finally(() => sql.end());
