import { NextResponse, type NextRequest } from "next/server";

import { COOKIE_NAME, verifySessionToken } from "@/lib/session";
import { bolehDilihatTamu } from "@/lib/tamu";

/**
 * Gerbang tunggal untuk seluruh sisi browser.
 *
 * Dua jalur sengaja dilewati:
 *
 *   /api/jobs/*   — dipakai agent, punya autentikasinya sendiri (X-Agent-Key).
 *   /api/agent/*  — sama: agent melapor ke sini, dijaga X-Agent-Key.
 *                  Agent bukan browser dan tidak punya cookie.
 *   /api/tugas/next dan /api/tugas/<id>/hasil — dua sisi agent dari antrean
 *                  tugas. Sengaja disebut SATU PER SATU, bukan sebagai awalan
 *                  /api/tugas: awalan itu akan ikut membebaskan POST /api/tugas
 *                  (pengguna membuat permintaan) dan GET /api/tugas/<id>
 *                  (pengguna membaca hasilnya), sehingga siapa pun tanpa cookie
 *                  bisa menyuruh `claude -p` berjalan di PC pemilik agent dan
 *                  membaca prompt milik orang lain.
 *   /login       — kalau ini ikut dijaga, tidak ada yang bisa masuk.
 *   /api/daftar  — pendaftaran akun; ia dijaga kata sandi undangannya sendiri.
 *
 * Sisanya, termasuk /api/upload-token, wajib punya cookie sesi yang sah.
 * Endpoint itu mencetak izin tulis ke bucket; membiarkannya terbuka sama saja
 * menyediakan hosting file gratis untuk siapa pun yang menemukan URL-nya.
 */
export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (
    pathname.startsWith("/api/jobs") ||
    pathname.startsWith("/api/agent") ||
    pathname === "/api/tugas/next" ||
    (pathname.startsWith("/api/tugas/") && pathname.endsWith("/hasil")) ||
    pathname === "/login" ||
    pathname === "/api/login" ||
    pathname === "/api/daftar"
  ) {
    return NextResponse.next();
  }

  const secret = process.env.SESSION_SECRET?.trim();
  if (!secret) {
    // Gagal tertutup, bukan terbuka: tanpa secret, tidak ada yang boleh lewat.
    return NextResponse.json(
      { error: "SESSION_SECRET belum diset di server." },
      { status: 500 },
    );
  }

  const token = request.cookies.get(COOKIE_NAME)?.value;
  const sesi = await verifySessionToken(secret, token);
  if (sesi) {
    if (sesi.peran === "tamu") {
      // Tamu tidak boleh MENGUBAH apa pun. Metode yang jadi ukuran, bukan
      // daftar rute: rute baru yang mengubah sesuatu otomatis ikut terjaga,
      // sedangkan daftar rute harus diingat untuk diperbarui — dan yang harus
      // diingat cepat atau lambat terlupakan.
      const membaca = request.method === "GET" || request.method === "HEAD";
      if (!membaca) {
        return NextResponse.json(
          { error: "Mode tamu hanya bisa melihat. Masuk dengan akun untuk mengubah." },
          { status: 403 },
        );
      }

      // Dan tamu juga tidak boleh MELIHAT isi milik pemiliknya.
      //
      // Ini daftar IZIN, bukan daftar larangan. Bedanya menentukan apa yang
      // terjadi pada rute yang belum ada: dengan daftar larangan, halaman baru
      // otomatis terbuka untuk tamu sampai seseorang ingat menambahkannya —
      // dengan daftar izin, ia tertutup sampai seseorang memutuskan sebaliknya.
      // Untuk batas yang menjaga rekaman pribadi, arah gagalnya harus tertutup.
      // Daftarnya hidup di `lib/tamu.ts` karena navbar harus membacanya juga.
      if (!bolehDilihatTamu(pathname)) {
        if (pathname.startsWith("/api/")) {
          return NextResponse.json(
            { error: "Mode tamu tidak bisa membuka bagian ini. Masuk dengan akun." },
            { status: 403 },
          );
        }
        // Dialihkan ke beranda, bukan ke halaman masuk. Tamu SUDAH punya sesi
        // yang sah; melemparnya ke form masuk terbaca seperti sesinya rusak.
        const beranda = new URL("/", request.url);
        beranda.searchParams.set("tamu", "terbatas");
        return NextResponse.redirect(beranda);
      }
    }
    return NextResponse.next();
  }

  // API menjawab 401 supaya fetch di klien bisa menanganinya; halaman dialihkan.
  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "Belum login" }, { status: 401 });
  }

  const login = new URL("/login", request.url);
  if (pathname !== "/") login.searchParams.set("next", pathname);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: [
    // Semua kecuali aset statis. Berkas di /public ikut dikecualikan lewat
    // ekstensinya: tanpa itu, video latar dashboard menempuh seluruh
    // pemeriksaan sesi sebelum satu byte pun dikirim — ongkos yang tidak
    // membeli apa pun, karena halaman yang memuatnya sudah dijaga.
    "/((?!_next/static|_next/image|favicon.ico|.*\.(?:mp4|webm|png|jpg|jpeg|svg|webp|ico|woff2?)$).*)",
  ],
};
