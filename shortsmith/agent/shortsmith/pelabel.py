"""Pelabel: memberi tiap adegan B-roll satu label pendek tentang isinya.

## Kenapa ini perlu

Penyusun B-roll sebelumnya mekanis: kocok, bagikan, jangan berulang. Ia tidak
tahu apa pun tentang gambar yang dipilihnya, jadi kalimat tentang "orang yang
selalu punya alasan" bisa disandingkan dengan shot mobil mewah, dan tidak ada
di dalam sistem yang bisa tahu itu salah.

Untuk mencocokkan gambar dengan makna kalimat, gambarnya harus bisa dibaca
sebagai teks lebih dulu. Itu tugas satu-satunya file ini.

## Kenapa Haiku, dan kenapa sekali saja

Melabeli "dua orang main catur di ruangan remang" adalah klasifikasi pendek yang
model kecil pun sudah benar — lihat identitas `pelabel` di identitas.py. Yang
lebih penting: hasilnya DISIMPAN di peta video, jadi satu set bahan hanya pernah
dilabeli satu kali. Render kedua, ketiga, dan seterusnya dari bahan yang sama
tidak memanggil model sama sekali.

Gambar dikirim berkelompok, bukan satu per panggilan. Biaya terbesar di sini
adalah ongkos tetap tiap panggilan CLI, bukan gambarnya.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import SETTINGS
from .identitas import model_untuk
from .models import Adegan

log = logging.getLogger(__name__)

# Berapa gambar per panggilan. Terlalu sedikit membuat ongkos tetap CLI
# mendominasi; terlalu banyak membuat model kehilangan jejak nomor gambarnya
# dan mulai tertukar antar label.
PER_KELOMPOK = 8

# Berapa kelompok dikerjakan berbarengan.
#
# Tiap kelompok adalah satu proses `claude -p` yang menunggu jawaban dari
# jaringan — jadi waktunya habis untuk MENUNGGU, bukan untuk menghitung.
# Menjalankannya berurutan membiarkan mesin menganggur hampir sepanjang waktu.
#
# Terukur pada satu job nyata: 916 adegan menjadi 115 kelompok, tiap kelompok
# sekitar 59 detik, seluruhnya berderet — sekitar 1 jam 54 menit untuk pekerjaan
# yang sebagian besarnya adalah diam.
#
# Empat, bukan lebih: tiap panggilan menagih kuota model yang sama, dan
# menaikkannya terlalu tinggi menukar antrean di sini dengan penolakan karena
# terlalu sering meminta.
PARALEL = max(1, int(os.environ.get("SHORTSMITH_LABEL_PARALEL", "4")))

# Lebar frame yang dikirim. Label yang diminta hanya beberapa kata, jadi detail
# halus tidak menambah apa pun selain waktu unggah.
LEBAR_FRAME = 512

BATAS_DETIK = 180


class PelabelError(RuntimeError):
    pass


def _tulis_frame(adegan: Adegan, tujuan: Path) -> bool:
    """Ambil satu frame wakil dari tengah adegan, dengan bilah hitam dibuang."""
    vf = f"crop={adegan.crop}," if adegan.crop else ""
    cmd = [
        SETTINGS.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{(adegan.start + adegan.end) / 2:.2f}",
        "-i", adegan.src,
        "-frames:v", "1",
        "-vf", f"{vf}scale={LEBAR_FRAME}:-1",
        str(tujuan),
    ]
    subprocess.run(cmd, capture_output=True)
    return tujuan.exists() and tujuan.stat().st_size > 0


def _minta_label(berkas: list[tuple[int, Path]]) -> dict[int, str]:
    claude = shutil.which("claude")
    if not claude:
        raise PelabelError("Perintah `claude` tidak ada di PATH.")

    daftar = "\n".join(f"Gambar {i}: {p}" for i, p in berkas)
    prompt = (
        "Kamu melabeli klip video untuk pustaka B-roll.\n\n"
        "Baca setiap gambar di bawah ini, lalu beri SATU label pendek bahasa "
        "Indonesia (3-8 kata) yang menyebutkan: siapa/apa yang terlihat, sedang "
        "apa, dan di mana.\n\n"
        "Sebutkan juga nuansanya bila jelas (misalnya 'sendirian', 'sibuk', "
        "'mewah', 'lelah') karena label ini nanti dicocokkan dengan makna "
        "kalimat, bukan cuma bendanya.\n\n"
        f"{daftar}\n\n"
        'Balas HANYA JSON: {"1": "label", "2": "label", ...} '
        "dengan nomor persis seperti di atas."
    )

    proc = subprocess.run(
        [
            claude, "-p",
            "--output-format", "json",
            "--model", model_untuk("pelabel"),
            "--allowedTools", "Read",
        ],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=BATAS_DETIK,
    )
    if proc.returncode != 0:
        raise PelabelError(f"`claude -p` gagal (exit {proc.returncode}): {proc.stderr[-300:]}")

    amplop = json.loads(proc.stdout)
    teks = amplop.get("result") or ""
    awal, akhir = teks.find("{"), teks.rfind("}")
    if awal < 0 or akhir < 0:
        raise PelabelError(f"Keluaran pelabel tidak mengandung JSON: {teks[:200]}")

    mentah = json.loads(teks[awal : akhir + 1])
    return {int(k): str(v).strip() for k, v in mentah.items() if str(v).strip()}


def labeli(adegan: list[Adegan]) -> int:
    """Isi `label` untuk adegan yang belum punya. Kembalikan berapa yang terisi.

    Kegagalan di sini TIDAK menggagalkan render. Adegan tanpa label tetap bisa
    dipakai penyusun mekanis seperti sebelumnya; yang hilang hanya kemampuan
    mencocokkan makna. Menjatuhkan seluruh job karena satu panggilan label gagal
    akan menukar cacat kecil dengan kegagalan total.
    """
    perlu = [a for a in adegan if not a.label]
    if not perlu:
        return 0

    log.info("pelabel: %d adegan perlu dilabeli (model %s)", len(perlu), model_untuk("pelabel"))
    terisi = 0
    tmp = Path(tempfile.mkdtemp(prefix="shortsmith-label-"))

    def satu_kelompok(mulai: int) -> int:
        """Labeli satu kelompok. Kembalikan berapa yang terisi.

        Dijalankan dari beberapa thread sekaligus. Tidak ada state yang dibagi:
        nama berkas frame memakai `mulai` sehingga unik antar kelompok, dan tiap
        pemanggilan hanya menyentuh objek Adegan miliknya sendiri.
        """
        kelompok = perlu[mulai : mulai + PER_KELOMPOK]
        berkas: list[tuple[int, Path]] = []
        for n, a in enumerate(kelompok, start=1):
            f = tmp / f"f{mulai + n:04d}.jpg"
            if _tulis_frame(a, f):
                berkas.append((n, f))

        if not berkas:
            return 0

        try:
            hasil = _minta_label(berkas)
        except (PelabelError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
            log.warning("pelabel gagal untuk satu kelompok (%s) — dilewati", exc)
            return 0

        n_isi = 0
        for n, _ in berkas:
            if n in hasil:
                kelompok[n - 1].label = hasil[n]
                n_isi += 1
        return n_isi

    try:
        awal = list(range(0, len(perlu), PER_KELOMPOK))
        log.info(
            "pelabel: %d kelompok, %d dikerjakan berbarengan", len(awal), PARALEL
        )
        selesai = 0
        with ThreadPoolExecutor(max_workers=PARALEL) as pool:
            for n_isi in pool.map(satu_kelompok, awal):
                terisi += n_isi
                selesai += 1
                # Dihitung per kelompok SELESAI, bukan per indeks awal: dengan
                # beberapa thread, urutan selesainya tidak sama dengan urutan
                # mulainya, dan melaporkan indeks awal membuat angkanya
                # melompat-lompat mundur.
                if selesai % 5 == 0 or selesai == len(awal):
                    log.info(
                        "pelabel: %d/%d kelompok selesai (%d adegan berlabel)",
                        selesai, len(awal), terisi,
                    )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    log.info("pelabel: %d adegan berlabel", terisi)
    return terisi
