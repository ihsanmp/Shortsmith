"""Ukur gaya visual video contoh: berapa banyak adegan yang berulang.

## Pertanyaan yang dijawab

Dua contoh yang dikirim pengguna ternyata mewakili dua gaya berbeda:

- Contoh A: seluruhnya B-roll. Tiap shot adegan baru, tidak ada wajah pembicara
  dalam bingkai tetap, tanpa caption.
- Contoh B: pembicara duduk di meja mengisi sekitar 60% durasi, diselingi B-roll.

Bedanya bukan selera — ia mengubah cara render. Kalau agent memakai angka tetap,
ia hanya bisa meniru salah satunya, dan pengguna harus mengedit kode setiap kali
ganti gaya. Modul ini membuat angkanya DIUKUR dari contohnya sendiri.

## Cara mengukurnya tanpa mengenali wajah

Gaya "pembicara + B-roll" punya satu ciri yang bisa dihitung: bingkai pembicara
selalu **sama** — kamera diam, latar sama, subjek di posisi sama. Jadi shot-shot
itu saling mirip secara piksel. Montase B-roll sebaliknya: tiap shot berbeda.

Jadi yang diukur bukan "apakah ini wajah", melainkan "apakah ada satu tampilan
yang berulang jauh lebih sering daripada yang lain". Satu frame diambil dari
tengah tiap shot, diperkecil jadi 9x8 abu-abu, lalu dijadikan dHash — sidik jari
64 bit yang membandingkan terang antar piksel bertetangga. Shot dengan jarak
Hamming kecil dianggap tampilan yang sama.

Pendekatan ini buta terhadap isi: ia tidak tahu mana wajah, mana mobil. Yang
diketahuinya cuma pengulangan — dan justru itu yang membedakan kedua gaya.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import SETTINGS

log = logging.getLogger(__name__)

# Dua sidik jari dianggap tampilan yang sama kalau bedanya di bawah ini.
# 10 dari 64 bit memberi ruang untuk perbedaan gerak dan pencahayaan tanpa
# menyatukan adegan yang benar-benar berbeda.
AMBANG_HAMMING = 10

# Klaster harus cukup besar sebelum disebut "tampilan berulang". Dua shot mirip
# bisa terjadi kebetulan di montase mana pun.
MIN_ANGGOTA = 3
MIN_PORSI = 0.15


@dataclass(frozen=True)
class GayaVisual:
    porsi_berulang: float  # bagian durasi yang ditempati tampilan paling sering
    anggota: int  # berapa shot masuk klaster itu
    total_shot: int

    def ringkas(self) -> str:
        if self.porsi_berulang <= 0:
            return f"tidak ada tampilan berulang dari {self.total_shot} shot -> montase penuh"
        return (
            f"{self.anggota}/{self.total_shot} shot memakai tampilan yang sama "
            f"({self.porsi_berulang:.0%} durasi) -> gaya pembicara + B-roll"
        )


def _dhash(frame: np.ndarray) -> int:
    """Sidik jari 64 bit: bandingkan tiap piksel dengan tetangga kanannya."""
    beda = frame[:, 1:] > frame[:, :-1]
    bit = 0
    for nilai in beda.flatten():
        bit = (bit << 1) | int(nilai)
    return bit


def _ambil_frame(path: str | Path, detik: float) -> np.ndarray | None:
    """Satu frame 9x8 abu-abu, langsung dari ffmpeg tanpa file perantara."""
    cmd = [
        SETTINGS.ffmpeg, "-v", "error",
        "-ss", f"{detik:.3f}",
        "-i", str(path),
        "-frames:v", "1",
        "-vf", "scale=9:8,format=gray",
        "-f", "rawvideo", "-pix_fmt", "gray",
        "-",
    ]
    hasil = subprocess.run(cmd, capture_output=True)
    if hasil.returncode != 0 or len(hasil.stdout) < 72:
        return None
    return np.frombuffer(hasil.stdout[:72], dtype=np.uint8).reshape(8, 9)


def ukur_gaya(path: str | Path, panjang_shot: list[float]) -> GayaVisual:
    """Ukur porsi durasi yang ditempati tampilan yang paling sering berulang."""
    if len(panjang_shot) < MIN_ANGGOTA:
        return GayaVisual(0.0, 0, len(panjang_shot))

    # Titik tengah tiap shot — bukan awalnya, karena awal shot sering masih
    # berisi sisa transisi dari shot sebelumnya.
    tengah: list[float] = []
    jalan = 0.0
    for p in panjang_shot:
        tengah.append(jalan + p / 2)
        jalan += p

    sidik: list[tuple[int, float]] = []
    for t, p in zip(tengah, panjang_shot):
        f = _ambil_frame(path, t)
        if f is not None:
            sidik.append((_dhash(f), p))

    if len(sidik) < MIN_ANGGOTA:
        return GayaVisual(0.0, 0, len(panjang_shot))

    # Klaster sederhana: tiap sidik jari jadi calon pusat, hitung siapa saja yang
    # dekat. Dengan puluhan shot, biaya O(n^2)-nya tidak berarti apa-apa.
    total = sum(p for _, p in sidik)
    terbaik_durasi = 0.0
    terbaik_anggota = 0
    for pusat, _ in sidik:
        anggota = [(h, p) for h, p in sidik if bin(h ^ pusat).count("1") <= AMBANG_HAMMING]
        durasi = sum(p for _, p in anggota)
        if durasi > terbaik_durasi:
            terbaik_durasi, terbaik_anggota = durasi, len(anggota)

    porsi = terbaik_durasi / total if total else 0.0
    if terbaik_anggota < MIN_ANGGOTA or porsi < MIN_PORSI:
        return GayaVisual(0.0, 0, len(panjang_shot))

    return GayaVisual(round(porsi, 3), terbaik_anggota, len(panjang_shot))
