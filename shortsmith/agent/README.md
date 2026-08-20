# Shortsmith — Agent

Pipeline lokal: satu video mentah panjang → satu short video vertikal 9:16 dengan caption.

Ini bagian **agent** (Milestone 1–3 dari roadmap). Web, database, dan antrean job
(Milestone 4–6) belum ada — agent ini masih dijalankan dari terminal.

---

## Status: apa yang sudah terbukti

| Bagian | Status |
|---|---|
| Renderer FFmpeg (potong, 9:16, punch-in, caption, musik) | **Terbukti** — dijalankan end-to-end, output diverifikasi |
| Penurunan caption dari timestamp | **Terbukti** — remap sumber→output diuji, kata di luar potongan tidak bocor |
| Validasi EDL (clamp, tolak rentang mustahil) | **Terbukti** — timestamp mengada-ada tertangkap sebelum render |
| Transkrip (OpenVINO iGPU/NPU, faster-whisper CPU) | **Belum dijalankan** — butuh konversi model dulu |
| Keputusan LLM | **Belum dijalankan** — butuh `ANTHROPIC_API_KEY` |
| Renderer Resolve | **Belum diuji sama sekali** — butuh Resolve Studio, lihat catatan di bawah |

---

## Perbedaan dari dokumen konsep awal

Empat penyimpangan yang disengaja, semuanya karena alasan teknis:

**1. Transcode dipindah ke belakang.** Dokumen mentranscode seluruh rekaman ke
DNxHR sebelum analisis. Untuk rekaman 30 menit itu ≈20–25 GB dan beberapa menit
kerja, padahal Whisper dan silencedetect bekerja dari audio dan tidak peduli VFR.
Di sini analisis jalan dari file asli, dan normalisasi CFR hanya diterapkan pada
segmen yang benar-benar terpilih — dari 30 menit menjadi ~45 detik.

**2. PySceneDetect tidak dipakai untuk video mentah.** Ia mendeteksi potongan
keras; rekaman satu-take tidak punya satu pun, jadi hasilnya kosong. Alat itu
hanya dipakai di `profile.py`, untuk video contoh yang memang sudah diedit. Yang
menentukan titik potong di rekaman talking-head adalah **jeda hening + timestamp
per kata**.

**3. Caption tidak ditulis LLM.** Model hanya memilih rentang waktu. Teks dan
waktu caption dipetakan secara deterministik dari timestamp Whisper melalui EDL
(`t_output = t_sumber − cut.in + offset`). Nol halusinasi, nol biaya token,
presisi penuh.

**4. Musik masuk skema EDL.** Tidak ada di dokumen asli, padahal short video
hampir selalu butuh.

**5. Durasi video contoh tidak mengikat durasi hasil.** Dokumen menyebut "total
durasi yang menyimpang jauh dari target konsep ditolak". Itu keliru arah: angka
durasi di konsep berasal dari rata-rata panjang video contohmu, dan panjang
contoh bukan spesifikasi — ia cuma gambaran gaya. Video contoh 1:30 yang
menghasilkan 2:30 itu wajar; yang menentukan panjang hasil adalah materinya.

Validator sekarang **tidak membandingkan hasil dengan durasi contoh sama sekali**.
Ia hanya menangkap dua keadaan yang memang menandakan kegagalan, dan keduanya
diukur terhadap hal yang relevan:

| Pemeriksaan | Diukur terhadap | Alasan |
|---|---|---|
| Hasil < 8 detik | angka absolut | Itu bukan video — model gagal memilih |
| Hasil > 85% rekaman | **rekaman mentah** | Praktis tidak ada yang dipotong |

Dari video contoh 1:30, hasil 0:45 sampai 10:00 semuanya lewat. Durasi contoh
hanya masuk ke prompt, dengan instruksi eksplisit bahwa itu bukan angka yang
harus dikejar.

---

## Autentikasi model: tidak perlu API key

Tahap keputusan editing punya dua backend, dipilih lewat `DECIDER`:

| `DECIDER` | Autentikasi | Kapan dipakai |
|---|---|---|
| **`claude-cli`** (default) | Kredensial **langganan** Claude yang sudah ada | Alat pribadi di mesin sendiri |
| `api` | `ANTHROPIC_API_KEY` + kredit | Layanan yang di-deploy dan dipakai orang lain |

`claude-cli` memanggil `claude -p --output-format json` lewat subprocess. Karena
Claude Code sudah login dengan langganan, **tidak perlu API key maupun beli
kredit**. Untuk server tanpa login interaktif, pakai `CLAUDE_CODE_OAUTH_TOKEN`
dari `claude setup-token`.

Dua detail implementasi yang penting:

- **Prompt dikirim lewat stdin, bukan argumen.** Transkrip 30 menit bisa lebih
  dari 30.000 karakter, sementara batas baris perintah Windows 32.767 karakter.
  Lewat argumen, job panjang akan gagal secara acak.
- **`--output-format json`, bukan `text`.** Mode `text` mencampur peringatan
  konfigurasi ke stdout bersama jawabannya; mode JSON memisahkannya ke field
  `.result` dan sekalian melaporkan `is_error` dan biaya setara.

Karena jalur CLI tidak punya structured output yang dijamin server, bentuk JSON
diminta lewat prompt lalu diverifikasi pydantic. Kalau tidak valid, model diminta
memperbaiki satu kali sebelum job dinyatakan gagal.

---

## Instalasi

```bash
cd shortsmith/agent
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
```

FFmpeg (wajib):

```bash
winget install Gyan.FFmpeg
```

Restart terminal setelah install agar PATH ter-update, lalu:

```bash
python -m shortsmith.cli doctor
```

---

## Hasil benchmark di Core Ultra 7 155H

Diukur pada audio 60 detik, model whisper-small int8, mesin ini sendiri:

| Backend | Load | Inferensi | Kecepatan | Timestamp per kata |
|---|---:|---:|---:|---|
| **faster-whisper CPU** | 1,6 s | 14,9 s | **4,0x** | **ya, sungguhan** |
| OpenVINO — Arc iGPU | 5,9 s | 16,5 s | 3,6x | tidak (diinterpolasi) |
| OpenVINO — CPU | 1,9 s | 17,0 s | 3,5x | tidak (diinterpolasi) |
| OpenVINO — AI Boost NPU | 106,5 s | 21,3 s | 2,8x | **tidak ada sama sekali** |

Kesimpulan yang tidak saya duga sebelum mengukur: **faster-whisper di CPU menang
di semua sumbu.** Ia paling cepat, tidak perlu konversi model, dan satu-satunya
yang memberi timestamp per kata yang benar-benar diukur.

**NPU adalah pilihan terburuk di sini**, bukan yang terbaik. Selain paling lambat,
ia butuh 106 detik hanya untuk mengompilasi model, dan `WhisperPipeline`
mengembalikan **nol potongan bertimestamp** di NPU — padahal seluruh penurunan
caption bergantung pada timestamp. Jadi jalur NPU secara fungsional tidak terpakai
untuk beban kerja ini, bukan sekadar lebih lambat.

Kenapa iGPU tidak membantu: whisper-small kecil, dan hambatannya ada di decoder
autoregresif yang terikat latensi, bukan throughput. Sementara int8 di CPU sudah
sangat teroptimasi, apalagi dengan 16 core.

Karena itu **default-nya sekarang `faster-whisper`**. Jalur OpenVINO tetap ada
kalau kamu ingin mengukur ulang dengan model lain.

---

## Transkrip di Intel Core Ultra (Arc iGPU / AI Boost NPU)

faster-whisper (CTranslate2) **tidak punya jalur NPU maupun iGPU sama sekali** —
ia CPU/CUDA saja. Untuk memakai Arc atau AI Boost, jalurnya OpenVINO.

Konversi model dulu (sekali saja):

```bash
# Arc iGPU — rekomendasi utama
python -m shortsmith.cli prepare-model --device GPU -o models/whisper-small-gpu

# AI Boost NPU — butuh graph statis, jadi direktori terpisah
python -m shortsmith.cli prepare-model --device NPU -o models/whisper-small-npu
```

Lalu pilih saat menjalankan:

```powershell
$env:ASR_BACKEND = "openvino"
$env:OV_DEVICE   = "GPU"                        # atau NPU / CPU
$env:OV_MODEL_DIR = "models/whisper-small-gpu"
```

**Mana yang sebaiknya dipakai.** Di Core Ultra 7 155H, **Arc iGPU biasanya lebih
cepat daripada NPU** untuk Whisper — NPU-nya ~11 TOPS dan dukungan Whisper di
OpenVINO masih lebih terbatas di sana (butuh bentuk statis, sebagian beban jatuh
balik ke CPU). Keunggulan NPU adalah efisiensi daya, bukan kecepatan mentah:
berguna kalau agent jalan lama sambil laptop dipakai kerja. Ukur sendiri —
kedua jalur sudah disediakan supaya bisa dibandingkan.

**Konsekuensi yang harus disadari.** OpenVINO `WhisperPipeline` hanya
mengembalikan timestamp **per potongan**, bukan per kata. Waktu tiap kata di
jalur ini **diinterpolasi** proporsional panjang karakter. Teks caption tetap
akurat (tetap datang dari transkrip, tidak mengada-ada), tapi presisi waktunya
turun dari ~50 ms ke ~150 ms. Untuk caption per frasa itu tidak terasa. Kalau
butuh gaya kata-per-kata yang ketat, pakai `ASR_BACKEND=faster-whisper` (CPU).

---

## Pemakaian

```bash
# 1. Buat konsep dari 2-4 video contoh (sekali di awal)
python -m shortsmith.cli concept \
  --nama vlog-cepat --samples contoh1.mp4 contoh2.mp4 contoh3.mp4 \
  --gaya-bahasa "santai, kalimat pendek" \
  --cta "ajak nonton video panjangnya" \
  -o concepts/vlog-cepat.json

# 2. Penggunaan harian
python -m shortsmith.cli render rekaman.mp4 \
  --concept concepts/vlog-cepat.json \
  --brief "fokus ke bagian yang bahas manajemen waktu" \
  -o hasil.mp4

# Lihat EDL dulu tanpa render (murah, cepat)
python -m shortsmith.cli render rekaman.mp4 --concept concepts/vlog-cepat.json --dry-run
```

Setiap tahap menulis artefaknya ke `.shortsmith/<job_id>/` dan tahap yang
artefaknya sudah ada akan dilewati. Jadi mengulang render dengan brief berbeda
tidak menjalankan Whisper lagi. Pakai `--refresh` untuk memaksa hitung ulang.

```
.shortsmith/<job_id>/
├── map.json       peta video mentah (transkrip + jeda hening)
├── plan.json      rencana potongan dari LLM
├── edl.json       EDL lengkap — kontrak ke renderer
├── captions.ass   caption yang dibakar
├── seg_*.mov      segmen CFR
└── hasil.json     ringkasan job
```

---

## Environment variable

| Variabel | Default | Keterangan |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | wajib untuk tahap keputusan |
| `RENDERER` | `ffmpeg` | `ffmpeg` \| `resolve` |
| `ASR_BACKEND` | `openvino` | `openvino` \| `faster-whisper` |
| `OV_DEVICE` | `GPU` | `GPU` (Arc) \| `NPU` (AI Boost) \| `CPU` |
| `OV_MODEL_DIR` | `models/whisper-small-ov` | hasil `prepare-model` |
| `WHISPER_LANGUAGE` | `id` | kosongkan untuk deteksi otomatis |
| `SHORTSMITH_MODEL` | `claude-opus-5` | model untuk keputusan editing |
| `SHORTSMITH_FPS` | `30` | frame rate output |
| `FFMPEG_PATH` / `FFPROBE_PATH` | dari PATH | override kalau tidak di PATH |

---

## Catatan tentang renderer Resolve

`renderer/resolve.py` ditulis sesuai API DaVinciResolveScript tapi **belum pernah
dijalankan terhadap instalasi Resolve yang nyata**. Anggap belum terbukti sampai
kamu menjalankannya sendiri.

Syaratnya: Resolve **Studio** (versi gratis tidak mengizinkan scripting
eksternal), Resolve harus sudah berjalan dengan GUI terbuka, dan
`Preferences → System → General → External scripting using: Local`.

Bagian paling rapuh adalah penyisipan caption Text+ — ia dibungkus try/except
dan kalau gagal render tetap dilanjutkan tanpa caption, karena keluar video tanpa
teks lebih baik daripada job gagal total.

Untuk potong + caption + punch-in, jalur FFmpeg mengungguli Resolve di hampir
semua dimensi yang penting di sini: tanpa lisensi, tanpa PC harus menyala dengan
GUI terbuka, tidak bisa dibekukan dialog modal, dan bisa paralel. Resolve baru
menang kalau kamu benar-benar butuh grading atau template Fusion.

---

## Struktur

```
shortsmith/
├── config.py       semua setting, dibaca dari environment
├── models.py       skema pydantic: ConceptProfile, VideoMap, CutPlan, EDL
├── probe.py        pembungkus ffprobe/ffmpeg + preflight
├── analyze.py      peta video: transkrip + jeda hening
├── asr.py          backend transkrip: OpenVINO (iGPU/NPU) & faster-whisper (CPU)
├── captions.py     penurunan caption deterministik + penulisan ASS
├── decide.py       LLM → rencana potongan + validasi
├── profile.py      ekstraksi concept profile dari video contoh
├── pipeline.py     orkestrator
├── cli.py          antarmuka baris perintah
└── renderer/
    ├── base.py     interface Renderer
    ├── ffmpeg.py   implementasi utama (terbukti)
    └── resolve.py  implementasi alternatif (belum terbukti)
```

## Langkah berikutnya

1. Konversi model OpenVINO, lalu `render` satu rekaman asli end-to-end.
2. Bandingkan `OV_DEVICE=GPU` vs `NPU` vs `ASR_BACKEND=faster-whisper` pada
   rekaman yang sama, ukur waktunya.
3. Buat dua konsep dari video contoh berbeda dan cek apakah output dari rekaman
   mentah yang sama benar-benar terasa berbeda. Ini menguji hipotesis inti
   "ganti konsep tanpa ubah kode" — perlakukan sebagai hipotesis, bukan asumsi.
4. Baru bangun web + antrean (Milestone 4–6).
