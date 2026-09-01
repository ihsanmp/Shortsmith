/**
 * Lihat bentuk jawaban /api/jobs/next apa adanya.
 *
 *     npx tsx scripts/cek-next.ts
 *
 * AMAN dijalankan hanya saat antrean kosong: memanggilnya MENGAMBIL job dari
 * antrean, dan job yang terambil skrip ini tidak akan pernah dikerjakan agent.
 * Periksa dengan cek-antrean.ts lebih dulu.
 */
import { config } from "dotenv";

config({ path: [".env.local", ".env.vercel.local"] });
const kunci = process.env.AGENT_KEY?.trim();
const dasar = (process.env.SHORTSMITH_API_URL || "https://shortsmith-ten.vercel.app").replace(/\/$/, "");
if (!kunci) { console.error("[X] AGENT_KEY tidak ada di env lokal"); process.exit(1); }

async function main() {
  const res = await fetch(`${dasar}/api/jobs/next`, {
    headers: { "X-Agent-Key": kunci! },
    cache: "no-store",
  });
  console.log(`HTTP ${res.status}`);
  const teks = await res.text();
  try {
    const d = JSON.parse(teks);
    console.log("kunci teratas:", Object.keys(d));
    console.log("job:", d.job === null ? "null" : JSON.stringify(d.job).slice(0, 400));
    console.log("tugas:", d.tugas === null ? "null" : JSON.stringify(d.tugas).slice(0, 200));
  } catch {
    console.log("BUKAN JSON:", teks.slice(0, 400));
  }
}

main();
