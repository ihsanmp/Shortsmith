# Shortsmith

Mesin pemotong video otomatis yang berjalan di komputermu sendiri.

Membuat klip pendek dari rekaman panjang adalah kerja berulang yang isinya
keputusan kecil-kecil: bagian mana yang kuat, di mana memotongnya supaya tidak
memotong napas orang, bingkainya harus ke mana saat orangnya bergerak. Semuanya
bisa dikerjakan tangan, dan semuanya memakan sore.

Shortsmith memindahkan keputusan-keputusan itu sekali, lalu memakainya berulang.
Kamu mengirim beberapa video contoh; darinya ia mengambil bukan kesan melainkan
**ukuran** — ritme potongan, rasio layar, gaya subtitle, porsi durasi yang
menampilkan pembicara, seberapa rapat wajah dibingkai. Itu yang disebut konsep,
dan konsep itu yang mengarahkan video berikutnya.

Untuk tiap video kamu bisa menambahkan brief yang mengikat: narasi yang wajib
sampai, kesan yang diinginkan, tujuan campaign, dan ajakan di akhir. Diisi,
keempatnya jadi syarat hasil — bukan bahan pertimbangan.

Satu rekaman masuk. Beberapa klip 40–90 detik keluar, sudah dipotong di titik
yang benar, dibingkai mengikuti orangnya, diberi subtitle, dikasih musik,
diratakan kenyaringannya, dan ditulis keterangan unggahannya.

> Penjelasan lengkap cara kerjanya ada di [`shortsmith/docs/cara-kerja.html`](shortsmith/docs/cara-kerja.html) —
> buka di peramban.

---

## Bentuknya dua bagian

| | Di mana | Tugasnya |
|---|---|---|
| **`shortsmith/agent`** | PC-mu | Semua kerja berat: transkrip, deteksi wajah, pemilihan potongan, render |
| **`shortsmith/web`** | Vercel | Memberi perintah dan melihat hasil. Tidak pernah menyentuh satu frame pun |

Keduanya tidak pernah saling memerintah. Web menaruh pekerjaan di antrean
(Postgres), dan agent yang bertanya "ada kerjaan?" tiap sepuluh detik. Karena
hubungannya berupa tarikan, PC-mu boleh mati kapan saja: agent mengirim denyut
tiap 30 detik, dan job yang denyutnya berhenti lebih dari lima menit kembali ke
antrean dengan sendirinya.

Bahan mentah tidak perlu naik ke internet sama sekali — agent bisa membacanya
langsung dari folder di disk. Yang keluar dari rumahmu cuma hasil rendernya.

---

## Menjalankan agent

Butuh **Python 3.11+**, **ffmpeg** di PATH, dan perintah **`claude`** yang sudah
login.

```bash
cd shortsmith/agent
python -m venv .venv
.venv/Scripts/activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Buat `agent/.env` berisi alamat panel web dan kunci agent:

```
SHORTSMITH_API_URL=https://…
AGENT_KEY=…
SHORTSMITH_BAHAN_DIR=…          # folder bahan mentah, opsional
SHORTSMITH_HASIL_DIR=…          # folder hasil render, opsional
```

Periksa dulu bahwa semuanya terpasang, baru nyalakan:

```bash
python -m shortsmith.cli doctor
python -m shortsmith.cli daemon
```

Di Windows ada `jalankan-daemon.cmd` (jendela terminal) dan
`jalankan-daemon.vbs` (tanpa jendela, untuk startup).

Perintah lainnya:

| | |
|---|---|
| `concept` | Membuat konsep dari video contoh |
| `analyze` | Menghasilkan peta rekaman tanpa merender |
| `render` | Menjalankan satu pipeline penuh dari terminal, tanpa antrean |
| `pantau` | Menjaga folder unduhan; klip baru otomatis masuk ke folder bahan |
| `pasok` | Membuat klip B-roll baru lewat Claude + Veo — **berbayar**, ke akun Google-mu |
| `prepare-model` | Mengonversi model transkrip ke OpenVINO (iGPU/NPU) |

## Menjalankan panel web

Butuh **Node 20+**.

```bash
cd shortsmith/web
npm install
npm run dev                     # http://localhost:3000
```

Variabel yang dibaca — isinya diambil dari `.env.local`, atau dari dashboard
Vercel saat dideploy:

```
DATABASE_URL          Postgres (Supabase)
SESSION_SECRET        rahasia penanda tangan cookie sesi
AGENT_KEY             harus sama dengan milik agent
APP_PASSWORD          kata sandi masuk
S3_ENDPOINT           penyimpanan hasil (Backblaze B2)
S3_BUCKET
S3_REGION
S3_ACCESS_KEY_ID
S3_SECRET_ACCESS_KEY
```

`npm run dev` mengisi nilai boneka untuk variabel yang belum ada di mesin ini,
supaya tampilan tetap bisa diperiksa tanpa membawa rahasia produksi ke lokal.
`scripts/cookie-lokal.ts` mencetak cookie pemilik untuk server lokal itu.

Perintah yang sering dipakai:

```bash
npm run typecheck               # tsc + pemeriksa sintaks yang bocor ke teks JSX
npm test                        # sesi + antrean, diuji pada Postgres sungguhan (PGlite)
npx tsx scripts/cek-konsistensi.ts   # keadaan data yang tidak masuk akal
```

---

## Prinsip

**Ukur dulu, tanya model belakangan.** Apa pun yang bisa dihitung, dihitung —
ritme, rasio, format, porsi pembicara, kerapatan bingkai — karena hasil hitungan
selalu lebih bisa dipercaya daripada penilaian model. AI dipakai hanya untuk yang
benar-benar tidak terukur: memilih momen mana yang layak masuk, dan membaca gaya
subtitle dari beberapa frame.

**Arah gagal ditentukan lebih dulu.** Satu klip gagal dari lima tidak
menggagalkan empat sisanya. Kuota model yang habis tidak membakar jatah
percobaan. Keterangan yang gagal ditulis tidak membuang render yang sudah
berhasil. Keluaran yang salah tanpa satu pun keluhan adalah kegagalan paling
mahal, karena ia baru ketahuan setelah ditonton.

**Kode berbahasa Indonesia.** Nama fungsi, variabel, komentar, dan pesan log
ditulis dalam bahasa yang dipakai orang yang mengerjakannya. Komentar menjelaskan
*kenapa*, bukan *apa* — sering dengan angka yang mendasarinya.
