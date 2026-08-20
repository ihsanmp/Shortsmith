"""Pemeriksaan hasil render: apakah sambungannya benar-benar bersih.

## Kenapa modul ini ada

Seluruh perapian batas di `rapikan.py` bekerja pada RENCANA — timestamp yang
menunjuk ke dalam rekaman sumber. Yang akhirnya didengar orang adalah berkas
hasil render, dan di antara keduanya masih ada renderer, fade, dan pembulatan
ke grid frame. Setiap kali ada laporan "ada suara bocor di detik sekian",
pemeriksaannya selalu berakhir di sini: membuka hasilnya, mengukur energi audio
tepat di sambungannya, dan melihat apakah ia jatuh di tengah kata.

Modul ini melakukan pemeriksaan itu sendiri, setiap kali, tanpa menunggu ada
yang melapor. Idenya diambil dari `video-use` (browser-use), yang menjalankan
evaluasi terhadap keluaran yang sudah dirender — bukan terhadap rencananya —
sebelum menunjukkannya ke pengguna.

## Kenapa ia melaporkan, bukan menggagalkan

Sambungan yang berisik itu cacat mutu, bukan kerusakan. Job yang sudah berjalan
belasan menit tidak boleh dibuang karena satu sambungan yang kurang rapi; yang
dibutuhkan adalah catatan yang menyebut detik ke berapa, supaya bisa diperiksa
tanpa harus menonton ulang seluruhnya.

## Kenapa ambangnya -30 dB

Pada job yang sudah rapi, batas-batasnya terukur di sekitar -100 dB — praktis
diam. Percakapan berada jauh di atas -30 dB. Ambang di antara keduanya memberi
jarak lebar ke dua arah, jadi ia tidak berbunyi karena derau ruangan, dan tidak
diam saat sebuah kata benar-benar terpenggal.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .rapikan import _pcm, _semua_frame

log = logging.getLogger(__name__)

# Lebar jendela di sekitar sambungan yang diperiksa, dalam detik. Cukup sempit
# supaya yang terukur memang sambungannya, bukan kalimat di sekitarnya.
JENDELA = 0.06

# Di atas ini, sambungan dianggap jatuh di tengah suara.
AMBANG_RMS = 0.0316  # -30 dBFS

# Sambungan pertama dan terakhir dilewati: keduanya adalah awal dan akhir video,
# bukan sambungan antara dua potongan.


@dataclass
class Sambungan:
    indeks: int
    t: float
    rms: float

    @property
    def db(self) -> float:
        return 20 * math.log10(self.rms) if self.rms > 0 else -120.0

    @property
    def berisik(self) -> bool:
        return self.rms > AMBANG_RMS


def _batas_timeline(edl: Any) -> list[float]:
    """Detik-detik di timeline HASIL tempat dua potongan bersambung.

    Bentuk EDL-nya dua macam. Format satu jalur menyimpan potongan di `cuts`;
    format overlay memisahkan audio dan video, dan yang menentukan sambungan
    suara adalah `audio.cuts` — bukan slot videonya, yang berganti di tempat
    lain dan memang boleh berganti saat orangnya sedang bicara.
    """
    potongan = getattr(getattr(edl, "audio", None), "cuts", None) or getattr(edl, "cuts", [])

    batas: list[float] = []
    t = 0.0
    for c in potongan[:-1]:
        t += c.durasi
        batas.append(t)
    return batas


def periksa(hasil: str | Path, edl: Any) -> list[Sambungan]:
    """Ukur energi audio di tiap sambungan pada berkas hasil.

    Kembalikan seluruh sambungan beserta ukurannya — bukan hanya yang berisik —
    supaya pemanggilnya bisa melaporkan sebaran, bukan cuma daftar keluhan.
    """
    try:
        import numpy as np  # noqa: F401
    except ImportError:
        log.debug("numpy tidak ada — pemeriksaan hasil dilewati")
        return []

    batas = _batas_timeline(edl)
    if not batas:
        return []

    keluar: list[Sambungan] = []
    for i, t in enumerate(batas, 1):
        x = _pcm(str(hasil), max(0.0, t - JENDELA / 2), JENDELA)
        if x is None or len(x) == 0:
            continue
        frames = _semua_frame(x)
        if len(frames) == 0:
            continue
        # Puncak, bukan rata-rata. Fade 12 ms di renderer menekan tepat di titik
        # sambungannya; rata-rata seluruh jendela akan ikut tertekan olehnya dan
        # menyembunyikan kata yang terpenggal persis di sebelahnya.
        keluar.append(Sambungan(indeks=i, t=t, rms=float(max(frames))))

    return keluar


def laporkan(hasil: str | Path, edl: Any) -> int:
    """Periksa lalu tulis ringkasannya ke log. Kembalikan jumlah yang berisik.

    Tidak pernah melempar: pemeriksaan mutu yang bisa menjatuhkan job justru
    menambah cara baru untuk gagal, pada tahap ketika seluruh pekerjaan berat
    sudah selesai.
    """
    try:
        sambungan = periksa(hasil, edl)
    except Exception as exc:  # noqa: BLE001
        log.debug("pemeriksaan hasil gagal (%s) — diabaikan", exc)
        return 0

    if not sambungan:
        return 0

    berisik = [s for s in sambungan if s.berisik]
    urut = sorted(s.db for s in sambungan)
    median = urut[len(urut) // 2]

    if not berisik:
        log.info(
            "      sambungan bersih: %d diperiksa, median %.0f dB",
            len(sambungan), median,
        )
        return 0

    log.warning(
        "      %d dari %d sambungan jatuh di tengah suara (median %.0f dB):",
        len(berisik), len(sambungan), median,
    )
    # Yang paling keras lebih dulu — itu yang paling mungkin terdengar.
    for s in sorted(berisik, key=lambda s: -s.rms)[:5]:
        log.warning("        potongan %d berakhir di %.2fs — %.0f dB", s.indeks, s.t, s.db)

    return len(berisik)
