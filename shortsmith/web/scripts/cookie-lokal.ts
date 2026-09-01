/**
 * Mencetak cookie sesi pemilik untuk server lokal.
 *
 * Halaman yang menarik — daftar project, proses, konsep — semuanya di balik
 * middleware, jadi tanpa cookie yang sah `npm run dev` cuma bisa memperlihatkan
 * beranda dan halaman masuk.
 *
 * Cookie ini ditandatangani dengan rahasia BONEKA dari `dev-lokal.mjs`, jadi ia
 * hanya sah di mesin ini dan tidak berlaku di mana pun lagi. Rahasia sungguhan
 * tidak pernah dibawa ke sini.
 *
 *     npx tsx scripts/cookie-lokal.ts
 *
 * Lalu tempel keluarannya di konsol peramban:
 *
 *     document.cookie = "<keluaran>; path=/; max-age=86400"
 */
import { COOKIE_NAME, createSessionToken } from "../lib/session";
import { RAHASIA_BONEKA } from "./dev-lokal.mjs";

createSessionToken(RAHASIA_BONEKA, { peran: "pemilik" }).then((t) => {
  console.log(`${COOKIE_NAME}=${t}`);
});
