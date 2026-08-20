"""Pembangkit ritme potongan.

Panjang tiap slot visual dihasilkan di sini, bukan diminta ke LLM. Alasannya
sederhana: ritme itu statistik, dan model bahasa buruk dalam menghasilkan deret
angka yang konsisten terhadap rata-rata dan deviasi tertentu. Kode menghasilkan
metronomnya; model hanya memutuskan klip mana yang mengisi tiap slot.

Angka yang ditiru diambil dari concept profile — yang pada gilirannya diukur dari
video contohmu. Pada contoh @pejuangclipper8: 22 shot dalam 27,5 detik, rata-rata
1,25 detik, deviasi 0,70, dan **mempercepat menjelang akhir** (1,7 -> 0,8 -> 0,5
-> 0,4). Percepatan itu bukan kebetulan; ia yang memberi rasa membangun.
"""

from __future__ import annotations

import logging
import random

from .models import ConceptProfile

log = logging.getLogger(__name__)

DURASI_MIN = 0.35   # di bawah ini potongan terasa seperti glitch, bukan cut
DURASI_MAKS = 4.0

# Sigma gaussian = std profil x faktor ini. Nilainya di atas 1 karena clamping
# di DURASI_MIN memangkas ekor bawah distribusi, sehingga deviasi hasil selalu
# lebih kecil daripada sigma yang diminta. Angka ini dikalibrasi dengan mengukur
# deviasi keluaran terhadap deviasi video contoh.
SIGMA_FAKTOR = 1.20


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def generate_slots(
    total: float,
    profile: ConceptProfile,
    *,
    percepatan: float = 0.45,
    seed: int | None = None,
) -> list[tuple[float, float]]:
    """Bagi durasi `total` menjadi rentang (mulai, panjang) mengikuti ritme konsep.

    `percepatan` 0 berarti tempo rata dari awal sampai akhir; 0,45 berarti
    potongan di ujung akhir sekitar 45% lebih pendek daripada di awal.
    """
    stat = profile.metrik.get("avg_shot_length")
    mean = stat.mean if stat and stat.mean > 0 else 1.4
    std = stat.std if stat else mean * 0.4

    rng = random.Random(seed)
    slots: list[tuple[float, float]] = []
    cursor = 0.0

    while cursor < total - DURASI_MIN:
        posisi = cursor / total if total else 0.0

        # Percepatan dibuat SIMETRIS terhadap rata-rata: di awal sedikit lebih
        # panjang, di akhir sedikit lebih pendek, sehingga reratanya tetap
        # mendarat di angka profil. Kalau hanya dikurangi ke arah akhir,
        # rata-rata keseluruhan ikut melorot dan ritmenya tidak lagi cocok.
        faktor = 1.0 + percepatan / 2.0 - percepatan * posisi
        target = mean * faktor

        panjang = _clamp(rng.gauss(target, std * SIGMA_FAKTOR), DURASI_MIN, DURASI_MAKS)
        sisa = total - cursor

        # Jangan tinggalkan ekor yang terlalu pendek untuk berdiri sendiri.
        if sisa - panjang < DURASI_MIN:
            panjang = sisa

        # Bulatkan DULU, baru majukan cursor dengan nilai yang sama persis.
        # Kalau cursor maju dengan nilai penuh sementara yang disimpan sudah
        # dibulatkan, selisihnya menumpuk dan meninggalkan celah di timeline.
        panjang = round(panjang, 3)
        slots.append((round(cursor, 3), panjang))
        cursor = round(cursor + panjang, 3)

    if not slots:
        slots = [(0.0, round(total, 3))]

    # Rapikan slot terakhir supaya totalnya persis menutup durasi audio.
    t_akhir, d_akhir = slots[-1]
    sisa = round(total - t_akhir, 3)
    if sisa > 0 and abs(sisa - d_akhir) > 1e-9:
        slots[-1] = (t_akhir, sisa)

    panjangs = [d for _, d in slots]
    log.info(
        "ritme: %d slot untuk %.1fs (rata-rata %.2fs, target profil %.2fs, "
        "terpendek %.2fs, terpanjang %.2fs)",
        len(slots), total, sum(panjangs) / len(panjangs), mean, min(panjangs), max(panjangs),
    )
    return slots


def ringkas(slots: list[tuple[float, float]]) -> dict[str, float]:
    """Statistik ritme yang dihasilkan — untuk dibandingkan dengan profil."""
    import statistics

    d = [x for _, x in slots]
    return {
        "jumlah": len(d),
        "mean": round(statistics.fmean(d), 3),
        "std": round(statistics.pstdev(d) if len(d) > 1 else 0.0, 3),
        "min": round(min(d), 3),
        "max": round(max(d), 3),
    }
