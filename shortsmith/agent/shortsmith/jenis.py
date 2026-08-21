"""Jenis video: apa yang benar-benar ia ubah, dan apa yang tidak.

## Yang ditimpa

Tiga hal, dan ketiganya sudah bisa dikendalikan pipeline sejak sebelum modul ini
ada — jadi tidak ada yang perlu ditebak:

  - **Rasio keluaran.** 9:16 untuk short, 16:9 untuk cinematic dan AMV.
  - **Subtitle.** Dibakar untuk short; dimatikan untuk dua lainnya, karena teks
    di dalam bingkai lanskap yang ditujukan untuk ditonton besar terbaca sebagai
    tempelan, bukan bagian dari gambarnya.
  - **Kekerasan lagu.** Latar yang pelan untuk short dan cinematic; jalur utama
    yang keras untuk AMV.

## Yang TIDAK ditimpa, dan kenapa

Gaya potongannya sendiri — panjang tiap shot, ritme, cara membuka. Itu diukur
dari video contoh saat konsep dibuat, dan itulah satu-satunya sumber yang pernah
mengukur sesuatu. Menetapkannya dari sebuah label jenis berarti mengarang angka
yang tidak berasal dari bahan mana pun, lalu menyajikannya seolah hasil analisis.

Konsekuensinya jujur: memilih "AMV" tidak membuat potongannya mengikuti ketukan
lagu. Untuk itu dibutuhkan deteksi ketukan dan penjadwalan potongan terhadapnya —
pekerjaan tersendiri yang belum ada di pipeline ini.
"""

from __future__ import annotations

import logging
from copy import deepcopy

from .models import ConceptProfile

log = logging.getLogger(__name__)

# Kekerasan lagu relatif terhadap suara utama, dalam dB.
#
# -20 dB adalah latar yang jelas terdengar tanpa menutupi ucapan. Untuk AMV
# tidak ada ucapan yang perlu dilindungi, jadi lagunya naik menjadi jalur utama.
GAIN_LATAR = -20.0
GAIN_UTAMA = -3.0

ATURAN: dict[str, dict] = {
    "short": {"rasio": "9:16", "subtitle": True, "gain_db": GAIN_LATAR},
    "cinematic": {"rasio": "16:9", "subtitle": False, "gain_db": GAIN_LATAR},
    "amv": {"rasio": "16:9", "subtitle": False, "gain_db": GAIN_UTAMA},
}


def gain_musik(jenis: str) -> float:
    """Kekerasan lagu untuk jenis ini, dalam dB."""
    return ATURAN.get(jenis, ATURAN["short"])["gain_db"]


def terapkan_jenis(profile: ConceptProfile, jenis: str) -> ConceptProfile:
    """Kembalikan SALINAN profil dengan setelan jenis diterapkan.

    Salinan, bukan perubahan di tempat: profil yang sama bisa dipakai lagi oleh
    job berikutnya lewat cache, dan menyuntikkan setelan satu job ke dalamnya
    akan membuat job kedua diam-diam mewarisi jenis job pertama.
    """
    aturan = ATURAN.get(jenis)
    if aturan is None:
        log.warning("jenis video '%s' tidak dikenal — diperlakukan sebagai short", jenis)
        aturan = ATURAN["short"]

    p = deepcopy(profile)

    # `aspect_ratio` disimpan sebagai string di profil, dan diterjemahkan jadi
    # piksel oleh `resolution_for()` saat EDL dibangun — jadi cukup stringnya
    # yang diganti di sini.
    p.aspect_ratio = aturan["rasio"]
    p.caption.ada = bool(aturan["subtitle"])

    log.info(
        "jenis '%s': %s, subtitle %s, lagu %.0f dB",
        jenis,
        aturan["rasio"],
        "ya" if aturan["subtitle"] else "tidak",
        aturan["gain_db"],
    )
    return p
