import type { NextConfig } from "next";

const config: NextConfig = {
  // postgres.js dan AWS SDK harus dijalankan sebagai modul Node asli,
  // bukan di-bundle oleh Turbopack untuk server components.
  serverExternalPackages: ["postgres"],
};

export default config;
