/**
 * Lepaskan project dari konsepnya: project menyimpan SALINAN profilnya sendiri.
 *
 *     npx tsx scripts/migrasi-pisah-konsep.ts
 *
 * ## Kenapa
 *
 * `projects.concept_id` NOT NULL dengan onDelete: "restrict" berarti konsep
 * yang pernah dipakai tidak bisa dihapus selamanya — dan satu-satunya jalan
 * keluar yang ditawarkan adalah menghapus project beserta hasil rendernya.
 * Ongkos yang jauh lebih besar daripada yang diminta.
 *
 * Yang sebenarnya dibutuhkan project dari konsep cuma satu: profilnya, yaitu
 * angka-angka gaya yang dipakai saat merender. Kalau angka itu disalin ke
 * project, tautannya tidak lagi menahan apa pun.
 *
 * ## Yang ikut membaik
 *
 * Mengubah konsep tidak lagi diam-diam mengubah arti project lama. Sebelum ini,
 * konsep yang diedit membuat project lama ikut berubah gayanya kalau dirender
 * ulang — padahal project itu dibuat dengan angka yang berbeda.
 *
 * Salinan mengunci itu: tiap project mengingat gaya yang benar-benar dipakainya.
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.local", ".env.vercel.local"] });
const url = process.env.DATABASE_URL?.trim();
if (!url) { console.error("[X] DATABASE_URL tidak ditemukan"); process.exit(1); }
const sql = postgres(url, { max: 1, prepare: false });

async function main() {
  try {
    await sql`ALTER TABLE projects ADD COLUMN IF NOT EXISTS profil_json jsonb`;
    await sql`ALTER TABLE projects ADD COLUMN IF NOT EXISTS konsep_nama text`;

    // Diisi dari konsep yang dipakai SEKARANG, sebelum tautannya dilonggarkan.
    // Urutannya penting: setelah concept_id boleh NULL, sumber salinannya bisa
    // hilang dan project lama tidak punya profil sama sekali.
    const isi = await sql`
      UPDATE projects p
         SET profil_json  = c.profile_json,
             konsep_nama  = c.nama
        FROM concept_profiles c
       WHERE c.id = p.concept_id AND p.profil_json IS NULL
      RETURNING p.id
    `;
    console.log(`[ok] ${isi.length} project diisi salinan profilnya`);

    await sql`ALTER TABLE projects ALTER COLUMN concept_id DROP NOT NULL`;

    // Nama constraint-nya dibaca, bukan ditebak: penamaan bawaan Postgres
    // berbeda-beda tergantung bagaimana tabelnya dibuat.
    const [fk] = await sql<{ conname: string }[]>`
      SELECT conname
        FROM pg_constraint
       WHERE conrelid = 'projects'::regclass
         AND contype = 'f'
         AND confrelid = 'concept_profiles'::regclass
    `;
    if (fk) {
      await sql.unsafe(`ALTER TABLE projects DROP CONSTRAINT "${fk.conname}"`);
      await sql.unsafe(
        `ALTER TABLE projects ADD CONSTRAINT "${fk.conname}" ` +
          `FOREIGN KEY (concept_id) REFERENCES concept_profiles(id) ON DELETE SET NULL`,
      );
      console.log(`[ok] ${fk.conname}: restrict -> set null`);
    } else {
      console.log("[!] constraint FK ke concept_profiles tidak ditemukan");
    }

    // Dibaca ULANG dari server.
    const cek = await sql<{ column_name: string; is_nullable: string }[]>`
      SELECT column_name, is_nullable
        FROM information_schema.columns
       WHERE table_name = 'projects'
         AND column_name IN ('concept_id', 'profil_json', 'konsep_nama')
       ORDER BY column_name
    `;
    for (const c of cek) console.log(`[ok] projects.${c.column_name} (nullable ${c.is_nullable})`);

    const [sisa] = await sql<{ n: number }[]>`
      SELECT count(*)::int AS n FROM projects WHERE profil_json IS NULL
    `;
    if (sisa.n) console.log(`[!] ${sisa.n} project masih tanpa salinan profil`);
    else console.log("[ok] semua project punya salinan profilnya");
  } finally {
    await sql.end();
  }
}

main();
