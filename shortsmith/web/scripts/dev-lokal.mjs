/**
 * `next dev` untuk memeriksa tampilan, dengan nilai boneka untuk variabel yang
 * hanya ada di Vercel.
 *
 * SESSION_SECRET dan kunci storage tidak pernah dibawa ke mesin ini — dan tidak
 * perlu, karena yang diperiksa lewat sini adalah tampilan, bukan integrasinya.
 * Yang diisi di sini cuma nilai boneka supaya server mau menyala; berkas .env
 * tidak disentuh sama sekali.
 *
 *     node scripts/dev-lokal.mjs
 */
import { spawn } from "node:child_process";
import { pathToFileURL } from "node:url";

/** Diekspor supaya `cookie-lokal.ts` menandatangani dengan rahasia yang sama. */
export const RAHASIA_BONEKA = "boneka-lokal-untuk-periksa-tampilan-32b";

const BONEKA = {
  SESSION_SECRET: RAHASIA_BONEKA,
  AGENT_KEY: "boneka-lokal",
  S3_REGION: "us-east-005",
  S3_BUCKET: "boneka-lokal",
  S3_ENDPOINT: "https://contoh.invalid",
  S3_ACCESS_KEY_ID: "boneka-lokal",
  S3_SECRET_ACCESS_KEY: "boneka-lokal",
};

for (const [k, v] of Object.entries(BONEKA)) {
  if (!process.env[k]) process.env[k] = v;
}

// Hanya menyalakan server kalau berkas ini YANG dijalankan. `cookie-lokal.ts`
// mengimpor rahasia bonekanya dari sini, dan impor yang ikut menyalakan server
// berarti mencetak satu cookie menyisakan proses yang menahan port 3000.
if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  spawn("npx", ["next", "dev", "--port", "3000"], {
    stdio: "inherit",
    shell: true,
    env: process.env,
  });
}
