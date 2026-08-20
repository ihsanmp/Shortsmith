import { timingSafeEqual } from "node:crypto";

/**
 * Autentikasi agent: satu kunci rahasia di header X-Agent-Key, disimpan sebagai
 * environment variable di kedua sisi.
 *
 * Arah komunikasi selalu dari agent ke cloud — cloud tidak pernah menghubungi
 * agent. Jadi tidak perlu membuka port, tidak perlu IP publik, tidak perlu
 * konfigurasi firewall. Agent bisa jalan di jaringan kampus atau rumah.
 */
export function isAgentAuthorized(request: Request): boolean {
  // .trim() bukan basa-basi: nilai yang ditempel lewat dashboard atau dikirim
  // lewat pipe shell sering membawa spasi atau newline di ujung, dan
  // perbandingan byte-per-byte akan menolaknya tanpa petunjuk apa pun.
  const expected = process.env.AGENT_KEY?.trim();
  if (!expected) return false;

  const provided = request.headers.get("x-agent-key")?.trim();
  if (!provided) return false;

  const a = Buffer.from(provided);
  const b = Buffer.from(expected);
  // Panjang berbeda tidak boleh short-circuit sebelum perbandingan konstan-waktu.
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

export function unauthorized(): Response {
  return Response.json({ error: "X-Agent-Key tidak valid" }, { status: 401 });
}
