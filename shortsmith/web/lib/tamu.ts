/**
 * Halaman yang boleh dilihat sesi tamu.
 *
 * Daftar ini dipakai di dua tempat yang harus sepakat: middleware, yang menolak
 * tamu masuk ke halaman lain, dan navbar, yang menggambar isinya sesuai peran.
 * Selama keduanya menyimpan salinannya sendiri, keduanya bisa berbeda pendapat
 * tentang orang yang sama — dan yang terlihat pengguna adalah navbar tamu di
 * halaman yang hanya bisa dibuka pemilik.
 *
 * Ini daftar IZIN, bukan daftar larangan: halaman baru tertutup untuk tamu
 * sampai seseorang memutuskan sebaliknya. Untuk batas yang menjaga rekaman
 * pribadi, arah gagalnya harus tertutup.
 *
 * Modul ini sengaja tidak mengimpor apa pun. Ia ikut ke bundel peramban lewat
 * navbar, dan `lib/session.ts` — tempat yang paling wajar untuknya — membawa
 * serta rahasia sesi dan kriptografinya.
 */
export function bolehDilihatTamu(pathname: string): boolean {
  return (
    pathname === "/" ||
    pathname === "/about" ||
    pathname === "/profile" ||
    pathname === "/api/sesi"
  );
}
