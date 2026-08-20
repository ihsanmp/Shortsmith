/**
 * Cari host pooler Supabase yang benar untuk kredensial yang ada.
 *
 * Error "Tenant or user not found" muncul saat project berada di server pooler
 * yang BERBEDA dari yang tertulis di connection string — Supabase bisa
 * memindahkannya, dan hostname lama lalu menjawab "tenant tidak ada" dengan
 * benar: project-nya memang bukan di sana.
 *
 * Skrip ini mencoba beberapa varian host memakai kredensial yang sama, lalu
 * melaporkan mana yang menjawab. Kata sandinya tidak pernah dicetak.
 */
import { config } from "dotenv";
import postgres from "postgres";

config({ path: [".env.vercel.local", ".env.local"] });

const url = process.env.DATABASE_URL?.trim();
if (!url) {
  console.error("[X] DATABASE_URL tidak ada");
  process.exit(1);
}

const asli = new URL(url);
const host = asli.hostname;
console.log(`host sekarang : ${host}:${asli.port}`);

// Varian yang masuk akal: nomor server pooler berubah, atau memakai koneksi
// langsung (port 5432) yang tidak melewati pooler sama sekali.
const kandidat = new Set<string>();
for (let i = 0; i <= 3; i++) {
  kandidat.add(host.replace(/^aws-\d+-/, `aws-${i}-`));
}

async function coba(h: string, port: string): Promise<string> {
  const u = new URL(url!);
  u.hostname = h;
  u.port = port;
  const sql = postgres(u.toString(), {
    max: 1,
    prepare: false,
    connect_timeout: 8,
    idle_timeout: 2,
  });
  try {
    await sql`SELECT 1`;
    return "OK";
  } catch (e) {
    return (e as Error).message.slice(0, 70);
  } finally {
    await sql.end({ timeout: 2 }).catch(() => {});
  }
}

async function main() {
  console.log("\nmencoba varian host pooler (port 6543):");
  for (const h of [...kandidat].sort()) {
    const hasil = await coba(h, "6543");
    const tanda = hasil === "OK" ? "[ok] " : "  -  ";
    console.log(`${tanda}${h.padEnd(42)} ${hasil}`);
  }
}

main().catch((e) => {
  console.error("[X]", (e as Error).message);
  process.exitCode = 1;
});
