import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";

import * as schema from "./schema";

const connectionString = process.env.DATABASE_URL?.trim();
if (!connectionString) {
  throw new Error("DATABASE_URL belum diset.");
}

// Vercel menjalankan tiap function di instance terpisah dan mendaur ulangnya;
// satu koneksi per instance mencegah ledakan jumlah koneksi ke Postgres.
// prepare:false wajib untuk connection pooler transaction-mode (PgBouncer/Supabase).
const globalForDb = globalThis as unknown as { __sql?: ReturnType<typeof postgres> };

const sql =
  globalForDb.__sql ??
  postgres(connectionString, {
    max: 1,
    prepare: false,
    idle_timeout: 20,

    // Tanpa batas waktu menyambung, postgres.js MENUNGGU SELAMANYA saat pooler
    // penuh. Fungsi Vercel lalu menggantung sampai dibunuh di detik ke-300 —
    // sambil terus menahan slot koneksi yang justru sedang diperebutkan.
    //
    // Daemon memanggil /api/jobs/next tiap 30 detik. Satu fungsi menggantung
    // 300 detik berarti sepuluh fungsi menumpuk sebelum yang pertama dilepas:
    // antreannya tumbuh lebih cepat daripada terurai, dan seluruh API mati
    // meski databasenya sendiri sehat (SELECT 1 dari mesin lokal: 676 ms).
    //
    // Gagal cepat jauh lebih baik: agent tinggal mencoba lagi 30 detik kemudian,
    // dan slot koneksinya langsung kembali ke kolam.
    connect_timeout: 10,
  });

if (process.env.NODE_ENV !== "production") globalForDb.__sql = sql;

export const db = drizzle(sql, { schema });
export { schema };
