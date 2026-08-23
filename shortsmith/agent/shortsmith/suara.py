"""Meratakan kenyaringan antar potongan suara, supaya sambungannya tidak melonjak.

## Masalah yang diukur

Satu potongan bisa diambil dari menit ke-6 dan potongan berikutnya dari menit
ke-40. Di antara keduanya pembicara berpindah posisi, mendekat ke mikrofon, atau
sekadar bicara lebih keras — dan sambungannya terdengar sebagai volume yang
tiba-tiba berubah.

Terukur dengan ebur128 pada satu hasil render nyata, kenyaringan sesaat (LUFS)
tepat sebelum dan sesudah tiap sambungan::

    t= 2,91   -16,5 -> -22,6    6,1 LU
    t=38,75   -18,7 -> -12,2    6,5 LU
    t=57,80   -22,9 -> -13,3    9,6 LU
    t=63,02   -13,2 -> -17,5    4,3 LU

    median 3,5 LU   maks 9,6 LU   di atas 3 LU: 4 dari 8

Tiga LU sudah terdengar sebagai perubahan; sembilan terdengar seperti ada yang
memutar tombol volume di tengah video.

## Kenapa ini BUKAN sekadar salinan dari warna.py

Bentuk penyelesaiannya memang sama — ukur, cari median, koreksi sebagian dengan
batas. Tapi angkanya berbeda, dan alasannya berbeda.

Untuk gambar, gelap yang disengaja adalah bagian dari karyanya: contoh cinematic
pengguna terukur 67-82% piksel gelap, dan meratakannya habis akan menghapus
justru hal yang membuatnya cinematic. Karena itu koreksinya lemah (0,55).

Untuk suara, tidak ada yang setara. Perbedaan kenyaringan ANTAR POTONGAN yang
diambil dari menit yang berjauhan bukan ekspresi — ia artefak penyuntingan.
Yang memang ekspresi adalah dinamika DI DALAM satu potongan, dan itu sama
sekali tidak disentuh di sini: yang diterapkan cuma satu penguatan tetap per
potongan, bukan kompresi.

Karena itu koreksinya lebih kuat (0,75) dengan batas ±6 dB.
"""

from __future__ import annotations

import logging
import re
import subprocess

import numpy as np

from .config import SETTINGS

log = logging.getLogger(__name__)

# Seberapa jauh tiap potongan ditarik ke median. Lihat docstring modul untuk
# alasan angkanya lebih tinggi daripada padanannya di warna.py.
KEKUATAN = 0.75

# Batas keras penguatan, dalam dB. Di luar ini, potongan yang memang direkam
# jauh lebih pelan akan ikut menyeret derau latarnya naik sampai terdengar.
BATAS_DB = 6.0

# Di bawah ini perubahannya tidak terdengar, dan menambahkan satu filter per
# potongan untuk sesuatu yang tidak terdengar cuma menambah pekerjaan.
ABAI_DB = 0.5

# Kenyaringan di bawah ini dianggap hening, bukan bagian dari ucapan. Tanpa
# penyaringan ini, jeda panjang di dalam sebuah potongan menarik mediannya turun
# dan potongan itu ikut dikeraskan berlebihan.
HENING_LUFS = -70.0

_POLA = re.compile(r"t:\s*([\d.]+)\s+.*?M:\s*(-?[\d.]+)")


def ukur(src: str, mulai: float, akhir: float) -> float | None:
    """Kenyaringan median satu rentang, dalam LUFS. None kalau gagal.

    Dipakai median, bukan nilai terpadu (integrated) yang dilaporkan ebur128 di
    akhir: rentang yang memuat jeda panjang punya nilai terpadu yang jauh lebih
    rendah daripada yang sebenarnya terdengar, dan potongan itu akan dikeraskan
    untuk mengejar angka yang dibuat oleh keheningannya sendiri.
    """
    durasi = max(0.0, akhir - mulai)
    if durasi <= 0:
        return None
    hasil = subprocess.run(
        [
            SETTINGS.ffmpeg, "-hide_banner",
            "-ss", f"{mulai:.3f}", "-t", f"{durasi:.3f}",
            "-i", src,
            "-vn", "-af", "ebur128",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        errors="replace",
    )
    nilai = [
        float(m.group(2))
        for m in (_POLA.search(b) for b in hasil.stderr.split("\n"))
        if m and float(m.group(2)) > HENING_LUFS
    ]
    return float(np.median(nilai)) if nilai else None


def ratakan(kenyaringan: list[float | None]) -> list[float]:
    """Ubah hasil pengukuran jadi penguatan per potongan, dalam dB.

    Panjangnya sama dengan masukan; potongan yang tidak terukur mendapat 0.
    """
    hidup = [x for x in kenyaringan if x is not None]
    if len(hidup) < 2:
        # Satu potongan tidak bisa melonjak terhadap apa pun.
        return [0.0] * len(kenyaringan)

    target = float(np.median(hidup))
    keluar: list[float] = []
    dikoreksi = 0

    for x in kenyaringan:
        if x is None:
            keluar.append(0.0)
            continue
        # LUFS sudah dalam skala dB, jadi selisihnya langsung jadi penguatan.
        gain = (target - x) * KEKUATAN
        gain = max(-BATAS_DB, min(BATAS_DB, gain))
        if abs(gain) < ABAI_DB:
            keluar.append(0.0)
            continue
        keluar.append(round(gain, 2))
        dikoreksi += 1

    log.info(
        "perataan suara: target %.1f LUFS, %d dari %d potongan dikoreksi",
        target, dikoreksi, len(kenyaringan),
    )
    return keluar


def ratakan_edl(edl) -> int:
    """Isi `gain_db` tiap potongan suara di EDL. Kembalikan jumlah yang dikoreksi.

    Tidak pernah melempar: perataan ini penghalusan, dan hasil yang kenyaringannya
    melonjak masih jauh lebih berguna daripada job yang gagal karena
    penghalusnya bermasalah.
    """
    try:
        spine = getattr(edl, "audio", None)
        cuts = getattr(spine, "cuts", None) if spine is not None else None
        if not cuts or len(cuts) < 2:
            return 0

        src = spine.src
        nilai = [ukur(src, c.in_, c.out) for c in cuts]
        for c, g in zip(cuts, ratakan(nilai)):
            c.gain_db = g
        return sum(1 for c in cuts if c.gain_db)
    except Exception:  # noqa: BLE001
        log.warning("perataan suara dilewati", exc_info=True)
        return 0
