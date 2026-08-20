# Shortsmith — Web

Antarmuka, pustaka konsep, dan antrean job. Next.js App Router, deploy ke Vercel.

Ini Milestone 4–6. Bagian agent (yang benar-benar merender) ada di `../agent`.

---

## Status: apa yang sudah terbukti

| Bagian | Status |
|---|---|
| Typecheck + production build (16 route + middleware) | **Terbukti** — `tsc --noEmit` bersih, `next build` lolos |
| SQL antrean: claim, heartbeat, reaper, retry | **Terbukti** — 22 assertion terhadap Postgres asli (PGlite) |
| Sesi login: tanda tangan, kedaluwarsa, anti-pemalsuan | **Terbukti** — 12 assertion |
| Gerbang autentikasi | **Terbukti** — diuji lewat HTTP terhadap server produksi |
| Daemon agent: dispatch, pembatalan, pelaporan gagal | **Terbukti** — 4 skenario dengan API stub |
| Alur end-to-end lewat Postgres + storage sungguhan | **Belum dijalankan** — butuh DATABASE_URL dan bucket |

Perintah verifikasi:

```bash
npm run typecheck && npm run test && npm run build
```

---

## Autentikasi

Dua jalur yang terpisah sepenuhnya:

| Jalur | Mekanisme | Dijaga oleh |
|---|---|---|
| Browser → web | Password + cookie sesi bertanda tangan | `middleware.ts` |
| Agent → web | Header `X-Agent-Key` | `lib/auth.ts` per-route |

Middleware melewatkan `/api/jobs/*` karena agent bukan browser dan tidak punya
cookie. Semua route lain — termasuk `/api/upload-token` — wajib punya sesi.
Endpoint itu mencetak izin tulis ke bucket; membiarkannya terbuka sama saja
menyediakan hosting file gratis bagi siapa pun yang menemukan URL-nya.

Cookie berisi `<expiry>.<hmac-sha256(expiry)>` — tidak ada state di server.
Memperpanjang masa berlaku tanpa tanda tangan baru akan ditolak (ada test-nya).
Memakai Web Crypto, bukan `node:crypto`, karena middleware berjalan di Edge
runtime.

Cookie diberi flag `Secure` saat `NODE_ENV=production`. Vercel selalu HTTPS jadi
aman; tapi kalau kamu menjalankan `next start` sendiri di HTTP biasa, login tidak
akan menempel — pakai `npm run dev` untuk itu.

Kalau `SESSION_SECRET` tidak ada, middleware menolak semua request dengan 500.
Gagal tertutup, bukan terbuka.

---

## Kenapa S3-compatible, bukan Vercel Blob

Presigned URL adalah HTTP PUT/GET biasa — browser bisa, agent Python bisa, curl
bisa. Tidak ada protokol SDK khusus yang harus diimplementasikan dua kali di dua
bahasa. Selain itu video besar menghabiskan kuota tier gratis Vercel Blob dengan
cepat, sementara Cloudflare R2 tidak menagih egress sama sekali — dan pola kerja
di sini justru banyak egress: agent mengunduh mentah, mengunggah hasil, browser
mengunduh hasil.

Untuk development lokal, MinIO bisa dipakai tanpa mengubah kode — cukup ganti
`S3_ENDPOINT`.

---

## Arsitektur

```
Browser  ──presigned PUT──────────────►  Object storage (R2/S3)
   │                                            ▲
   │ POST /api/projects                         │ presigned PUT
   ▼                                            │
Vercel  ◄──── GET /api/jobs/next ──────  Agent (PC lokal)
   │          POST .../heartbeat                │
   │          POST .../status                   │ presigned GET
   ▼                                            ▼
Postgres                                  DaVinci / FFmpeg
```

**Byte video tidak pernah melewati serverless function.** API route hanya
menerbitkan URL bertanda tangan. Ini bukan optimasi — batas body Vercel ~4.5 MB
membuatnya keharusan.

**Agent tidak pernah memegang kredensial storage.** `/api/jobs/next` mengembalikan
URL unduh dan unggah yang sudah ditandatangani. Kalau `AGENT_KEY` bocor, yang
bocor hanyalah kemampuan mengambil job — bukan akses penuh ke bucket.

---

## Antrean job

Ini bagian yang paling mudah salah, jadi diuji paling ketat.

**Race saat mengambil job.** Draf konsep awal hanya menyebut "ambil satu job
pending, tandai processing" tanpa menyebut atomisitas. Dua agent yang polling
bersamaan — atau satu agent yang di-restart saat request sebelumnya masih
terbang — bisa mengambil job yang sama dan merender dua kali. Solusinya satu
statement:

```sql
UPDATE jobs SET status = 'processing', ...
 WHERE id = (SELECT id FROM jobs WHERE status = 'pending'
             ORDER BY created_at LIMIT 1
             FOR UPDATE SKIP LOCKED)
RETURNING ...
```

**Heartbeat.** Agent mengirim sinyal tiap 30 detik. Kalau server tidak menerimanya
lebih dari 5 menit, job dikembalikan ke `pending` — ini yang menangani PC mati
mendadak, listrik padam, atau agent crash. Reaper dipanggil lazily setiap kali
antrean disentuh; tidak perlu cron terpisah.

Arah sebaliknya juga ditangani: kalau heartbeat dijawab "job ini bukan milikmu
lagi", agent membatalkan pekerjaannya. Tanpa itu, job yang sudah diambil alih
akan dirender dua kali.

**Retry.** Maksimal 2. Kegagalan yang masih punya jatah kembali ke `pending`;
setelah itu `failed` permanen dengan pesan yang bisa dibaca user.

---

## Environment variable

`.env.example` belum memuat dua variabel autentikasi browser — tambahkan sendiri:

| Variabel | Keterangan |
|---|---|
| `DATABASE_URL` | Postgres, pakai connection string yang **pooled** |
| `S3_ENDPOINT` `S3_BUCKET` `S3_REGION` | R2 / S3 / MinIO |
| `S3_ACCESS_KEY_ID` `S3_SECRET_ACCESS_KEY` | kredensial storage |
| `S3_FORCE_PATH_STYLE` | `true` untuk R2 dan MinIO, `false` untuk AWS S3 |
| `AGENT_KEY` | kunci bersama web ↔ agent |
| `APP_PASSWORD` | **(tambahkan)** password yang diketik di `/login` |
| `SESSION_SECRET` | **(tambahkan)** kunci penanda tangan cookie; menggantinya memaksa login ulang |

Buat nilai acak untuk `AGENT_KEY` dan `SESSION_SECRET`:

```bash
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

## Setup lokal

```bash
npm install
npm run db:push                # buat tabel
npm run dev
```

Pakai `npm run dev`, bukan `next start`, untuk pengembangan lokal — di
`NODE_ENV=production` cookie diberi flag `Secure` dan tidak akan menempel di
`http://localhost`.

## Deploy ke Vercel

```bash
npx vercel --prod
```

Sebelum itu, set ketujuh environment variable di atas di **Project Settings →
Environment Variables** (Production). Lalu jalankan migrasi sekali terhadap
database produksi:

```bash
npm run db:push
```

Setelah deploy, arahkan agent ke domain produksinya:

```powershell
$env:SHORTSMITH_API_URL = "https://<proyekmu>.vercel.app"
$env:AGENT_KEY = "<nilai yang sama dengan di Vercel>"
python -m shortsmith.cli daemon
```

### Menjalankan agent terhadap web ini

```powershell
$env:SHORTSMITH_API_URL = "http://localhost:3000"
$env:AGENT_KEY = "<kunci yang sama>"
cd ..\agent
python -m shortsmith.cli daemon
```

---

## Kontrak API

### Dipakai browser

| Method | Endpoint | Fungsi |
|---|---|---|
| POST | `/api/upload-token` | Terbitkan presigned URL untuk upload langsung |
| GET | `/api/concepts` | Daftar konsep untuk dropdown |
| POST | `/api/concepts` | Buat konsep baru + job `profile_extraction` |
| GET/PATCH/POST | `/api/concepts/[id]` | Baca, edit `profile_json`, duplikat |
| GET | `/api/projects` | Daftar project |
| POST | `/api/projects` | Simpan metadata + job `render` |
| GET | `/api/projects/[id]` | Polling status dan hasil |

### Dipakai agent

Semua memerlukan header `X-Agent-Key`.

| Method | Endpoint | Fungsi |
|---|---|---|
| GET | `/api/jobs/next` | Ambil satu job pending, tandai processing |
| POST | `/api/jobs/[id]/heartbeat` | Tanda agent masih hidup (+ progress) |
| POST | `/api/jobs/[id]/status` | Laporkan `done` atau `failed` |

`/api/jobs/next` mengembalikan semuanya sekaligus: profil konsep, brief, URL
unduh input, dan URL unggah output. Satu panggilan, tidak perlu bolak-balik.

---

## Struktur

```
web/
├── db/schema.ts          concept_profiles, projects, assets, jobs
├── lib/
│   ├── auth.ts           X-Agent-Key, perbandingan konstan-waktu
│   ├── queue-sql.ts      SQL antrean — dipisah supaya bisa diuji apa adanya
│   ├── jobs.ts           pembungkus + sinkronisasi status project
│   ├── storage.ts        presigned URL S3-compatible
│   └── upload.ts         upload browser dengan progress
├── test/queue.test.ts    22 assertion terhadap Postgres (PGlite)
└── app/
    ├── page.tsx                     landing + daftar project
    ├── project/new, project/[id]    upload & status
    ├── concepts/…                   pustaka + editor profil
    └── api/…                        7 route browser + 3 route agent
```

`lib/queue-sql.ts` sengaja dipisah dari `lib/jobs.ts`: yang dieksekusi di test
adalah query yang sama persis dengan yang dikirim ke produksi, bukan salinannya.

---

## Yang belum dikerjakan

- **Autentikasi user.** Semua orang yang tahu URL bisa membuat project. Untuk
  tool internal tim itu mungkin cukup; untuk publik jelas tidak.
- **Notifikasi saat selesai.** Sekarang user harus membuka halaman project.
  Halaman itu memang memperbarui sendiri dan berhenti polling saat job selesai,
  tapi tidak ada notifikasi keluar.
- **Pembersihan storage.** Video mentah tidak pernah dihapus otomatis.
