import { config } from "dotenv";
import type { Config } from "drizzle-kit";

/**
 * drizzle-kit dijalankan sebagai proses terpisah, di luar Next.js, jadi ia tidak
 * ikut memuat `.env.local` seperti yang dilakukan `next dev`/`next build`.
 * Tanpa baris di bawah, `db:push` gagal dengan "url: ''" meski variabelnya ada.
 *
 * `.env.local` diisi oleh `vercel env pull`, sehingga migrasi berjalan terhadap
 * database yang sama persis dengan yang dipakai deployment produksi.
 */
config({ path: ".env.local" });
config({ path: ".env" });

const url = process.env.DATABASE_URL;
if (!url) {
  throw new Error(
    "DATABASE_URL belum ada. Jalankan dulu: vercel env pull .env.local --environment=production",
  );
}

export default {
  schema: "./db/schema.ts",
  out: "./drizzle",
  dialect: "postgresql",
  dbCredentials: { url },
} satisfies Config;
