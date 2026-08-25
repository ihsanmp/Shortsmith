"""Pelajari aspek video contoh yang tidak bisa diukur, dengan melihatnya.

## Pembagian kerja: ukur dulu, lihat kalau tidak terukur

Sebagian besar gaya bisa DIHITUNG dari video contoh, dan hasil hitungan selalu
lebih dipercaya daripada penilaian model:

  - ritme shot, durasi, jumlah potongan  -> PySceneDetect (profile.py)
  - rasio                                 -> probe (profile.py)
  - format satu-jalur vs overlay          -> korelasi shot & celah bicara (format_video.py)
  - porsi pembicara                       -> pengulangan sidik jari frame (gaya_visual.py)

Yang tersisa adalah gaya caption, dan itu tidak bisa dihitung. Saya sudah
mencoba: membandingkan perubahan antar-frame di dalam satu shot memberi angka
1,92 untuk contoh tanpa caption dan 2,12 untuk contoh bercaption — bertumpang
tindih, jadi pada dasarnya menebak. Detektor setipis itu menghasilkan video yang
seluruh captionnya keliru tanpa satu pun peringatan.

Maka untuk bagian ini saja, frame-nya DILIHAT. Beberapa frame diambil dari
tengah shot, lalu dibaca sekaligus dalam satu panggilan supaya model bisa
menimbang sendiri mana yang mewakili — satu frame terlalu mudah menyesatkan.

## Kenapa identitas `pelabel`

Ini klasifikasi pendek atas beberapa gambar, bukan penilaian editorial. Model
kecil sudah cukup, dan inilah tempat model besar paling boros. Lihat identitas.py.

## Kegagalan tidak pernah menggagalkan job

Kalau `claude` tidak ada, waktunya habis, atau jawabannya bukan JSON yang
dikenali, fungsi ini mengembalikan None dan pemanggilnya memakai bawaan. Gaya
caption yang meleset merugikan; job yang gagal total lebih merugikan.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import SETTINGS
from .identitas import model_untuk, sebab_gagal
from .models import CaptionStyle
from .probe import probe

log = logging.getLogger(__name__)

# Cukup untuk melihat pola tanpa membuat panggilan jadi berat. Caption biasanya
# muncul hampir sepanjang video, jadi enam titik sudah mewakili.
JUMLAH_FRAME = 6

# Lebar frame yang dikirim. 480px cukup untuk membaca teks caption yang memang
# dibuat besar agar terbaca di layar ponsel.
LEBAR = 480

PROMPT = """\
Kamu memeriksa beberapa frame dari SATU video short untuk menentukan gaya \
caption-nya. Frame-frame ini diambil dari titik yang berbeda di video yang sama.

Lihat semua file berikut, lalu jawab HANYA dengan satu objek JSON tanpa \
penjelasan apa pun di luarnya:

{daftar}

Format jawaban:
{{
  "ada": true atau false,
  "posisi": "atas" atau "tengah" atau "tengah-bawah",
  "gaya": "kata-per-kata" atau "frasa",
  "huruf_besar": true atau false,
  "max_kata": angka 1 sampai 8,
  "alasan": "satu kalimat singkat"
}}

Aturan penilaian:
- "ada" bernilai false kalau TIDAK ADA teks caption yang dibakar ke gambar. \
Abaikan teks yang memang bagian dari adegan: papan nama, layar laptop, merek \
di baju, tulisan di gedung, watermark aplikasi. Yang dihitung hanya teks \
subtitle yang mengikuti ucapan.
- Kalau sebagian frame ada captionnya dan sebagian tidak, jawab true — caption \
memang tidak muncul terus-menerus.
- "gaya" bernilai "kata-per-kata" kalau tiap tampilan hanya memuat SATU kata.
- "posisi" dinilai dari titik tengah teks terhadap tinggi layar.
- "max_kata" adalah jumlah kata terbanyak yang terlihat dalam satu tampilan.
"""


def _ambil_frame(path: str | Path, detik: float, tujuan: Path) -> bool:
    cmd = [
        SETTINGS.ffmpeg, "-v", "error",
        "-ss", f"{detik:.3f}",
        "-i", str(path),
        "-frames:v", "1",
        "-vf", f"scale={LEBAR}:-1",
        "-y", str(tujuan),
    ]
    return subprocess.run(cmd, capture_output=True).returncode == 0 and tujuan.exists()


def _titik_sampel(panjang_shot: list[float], durasi: float) -> list[float]:
    """Titik tengah shot, disebar merata. Jatuh ke pembagian rata kalau tak ada shot."""
    if not panjang_shot:
        return [durasi * (i + 0.5) / JUMLAH_FRAME for i in range(JUMLAH_FRAME)]

    tengah: list[float] = []
    jalan = 0.0
    for p in panjang_shot:
        tengah.append(jalan + p / 2)
        jalan += p

    if len(tengah) <= JUMLAH_FRAME:
        return tengah
    langkah = len(tengah) / JUMLAH_FRAME
    return [tengah[int(i * langkah)] for i in range(JUMLAH_FRAME)]


def _json_dari(teks: str) -> dict | None:
    bersih = teks.strip()
    if bersih.startswith("```"):
        bersih = "\n".join(b for b in bersih.splitlines() if not b.strip().startswith("```"))
    awal, akhir = bersih.find("{"), bersih.rfind("}")
    if awal < 0 or akhir <= awal:
        return None
    try:
        return json.loads(bersih[awal : akhir + 1])
    except json.JSONDecodeError:
        return None


def pelajari_caption(
    path: str | Path, panjang_shot: list[float], *, timeout: int = 240
) -> CaptionStyle | None:
    """Baca gaya caption dari video contoh. None kalau tidak bisa disimpulkan."""
    claude = shutil.which("claude")
    if not claude:
        log.warning("perintah `claude` tidak ada — gaya caption memakai bawaan")
        return None

    durasi = probe(path).durasi
    titik = _titik_sampel(panjang_shot, durasi)

    with tempfile.TemporaryDirectory(prefix="shortsmith_frame_") as tmp:
        folder = Path(tmp)
        berkas: list[Path] = []
        for i, t in enumerate(titik):
            f = folder / f"frame_{i:02d}.png"
            if _ambil_frame(path, t, f):
                berkas.append(f)

        if not berkas:
            log.warning("tidak ada frame yang bisa diambil — gaya caption memakai bawaan")
            return None

        daftar = "\n".join(f"- {f.resolve()}" for f in berkas)
        model = model_untuk("pelabel")
        log.info("membaca gaya caption dari %d frame (model %s)", len(berkas), model)

        try:
            proc = subprocess.run(
                [
                    claude, "-p",
                    "--output-format", "json",
                    "--model", model,
                    # Read diperlukan supaya frame-nya bisa dibuka. Tidak ada
                    # tool lain yang diizinkan: tugas ini hanya melihat gambar.
                    "--allowedTools", "Read",
                ],
                input=PROMPT.format(daftar=daftar),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            log.warning("pembacaan gaya caption melewati %ds — memakai bawaan", timeout)
            return None

        if proc.returncode != 0:
            log.warning(
                "pembacaan gaya caption gagal (kode %s): %s — memakai bawaan",
                proc.returncode, sebab_gagal(proc),
            )
            return None

        luar = _json_dari(proc.stdout)
        isi = _json_dari(luar.get("result", "")) if luar else None
        if not isi:
            log.warning("jawaban gaya caption tidak terbaca — memakai bawaan")
            return None

    if not isi.get("ada", True):
        log.info("gaya caption: TIDAK ADA caption di video contoh (%s)", isi.get("alasan", ""))
        return CaptionStyle(ada=False)

    gaya = CaptionStyle(
        ada=True,
        posisi=isi.get("posisi") if isi.get("posisi") in {"atas", "tengah", "tengah-bawah"} else "tengah",
        gaya=isi.get("gaya") if isi.get("gaya") in {"frasa", "kata-per-kata"} else "kata-per-kata",
        huruf_besar=bool(isi.get("huruf_besar", True)),
        max_kata=max(1, min(8, int(isi.get("max_kata", 4) or 4))),
    )
    log.info(
        "gaya caption: %s, %s, huruf besar=%s, maks %d kata (%s)",
        gaya.posisi, gaya.gaya, gaya.huruf_besar, gaya.max_kata, isi.get("alasan", ""),
    )
    return gaya
