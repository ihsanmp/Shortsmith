"""Jenis video: apa yang benar-benar ia ubah, dan apa yang tidak.

## Yang ditimpa

Dua hal, dan keduanya sudah bisa dikendalikan pipeline sejak sebelum modul ini
ada — jadi tidak ada yang perlu ditebak:

  - **Rasio keluaran.** 9:16 untuk short; cinematic dan podcast mengikuti
    konsepnya.
  - **Subtitle.** Dibakar untuk short dan podcast, karena keduanya menjual apa
    yang diucapkan. Dimatikan untuk cinematic: teks di dalam bingkai yang
    ditujukan untuk ditonton besar terbaca sebagai tempelan, bukan bagian dari
    gambarnya.

## Yang TIDAK ditimpa, dan kenapa

Gaya potongannya sendiri — panjang tiap shot, ritme, cara membuka. Itu diukur
dari video contoh saat konsep dibuat, dan itulah satu-satunya sumber yang
pernah mengukur sesuatu. Menetapkannya dari sebuah label jenis berarti mengarang
angka yang tidak berasal dari bahan mana pun, lalu menyajikannya seolah hasil
analisis.

## Kenapa rasio tidak dipaksa untuk cinematic dan podcast

Karena terukur bahwa rasio bukan penanda jenis. Contoh yang pernah dikirim
pengguna, semuanya berbeda meski kategorinya sama::

    CINE rpm.cinema        576x1024 9:16 potret  shot 1,90s  tanpa subtitle
    CINE bubbawubba7      1280x720  16:9         shot 1,03s  tanpa subtitle
    CINE sdmedia.hk        576x1024 9:16 potret  shot 2,07s  82% gelap
    POD  thecliper554     1024x576  16:9         shot 2,00s  SUBTITLE terbakar

Rasio mengikuti ke mana videonya diunggah, dan itu sudah diukur konsep dari
video contohnya sendiri.

Short tetap dipaksa 9:16, dan itu bukan pengecualian sembarangan: TikTok,
Reels, dan Shorts memang mensyaratkannya. Itu tuntutan platform, bukan selera
gaya yang bisa diukur dari bahan.

Cinematic dan podcast juga TIDAK terpisah oleh ritme — 1,90 lawan 2,00 detik
praktis sama. Yang membedakan keduanya adalah ada tidaknya ucapan yang perlu
dibaca, dan itulah satu-satunya hal yang ditimpa di sini.

## AMV pernah ada di sini

Ia dibuang: program ini tidak lagi mengedit AMV. Bersamanya hilang satu-satunya
jenis yang digerakkan lagu dan bukan ucapan — jadi tidak ada lagi kasus di mana
lagu perlu naik jadi jalur utama, dan tidak ada lagi jenis tanpa ucapan yang
ritmenya jauh berbeda dari sisanya.
"""

from __future__ import annotations

import logging
from copy import deepcopy

from .models import ConceptProfile

log = logging.getLogger(__name__)

# Kekerasan lagu relatif terhadap suara utama, dalam dB.
#
# Satu nilai saja sekarang: -20 dB adalah latar yang jelas terdengar tanpa
# menutupi ucapan. Ketiga jenis yang tersisa punya ucapan yang perlu dilindungi,
# jadi tidak ada yang membutuhkan angka kedua.
GAIN_LATAR = -20.0

# `rasio: None` berarti JANGAN ditimpa — pakai apa pun yang ditetapkan konsep.
# Alasannya, beserta ukurannya, ada di docstring modul.
ATURAN: dict[str, dict] = {
    "short": {"rasio": "9:16", "subtitle": True, "gain_db": GAIN_LATAR},
    "cinematic": {"rasio": None, "subtitle": False, "gain_db": GAIN_LATAR},
    # Podcast: ada ucapan, jadi subtitle menyala seperti short — tapi rasionya
    # TIDAK dipaksa. Contoh yang diukur 16:9 lanskap, dan klip podcast memang
    # beredar di lanskap maupun potret tergantung tujuan unggahnya.
    "podcast": {"rasio": None, "subtitle": True, "gain_db": GAIN_LATAR},
}


def gain_musik(jenis: str) -> float:
    """Kekerasan lagu untuk jenis ini, dalam dB."""
    return ATURAN.get(jenis, ATURAN["short"])["gain_db"]


def terapkan_jenis(
    profile: ConceptProfile, jenis: str, rasio: str = "auto"
) -> ConceptProfile:
    """Kembalikan SALINAN profil dengan setelan jenis diterapkan.

    `rasio` adalah pilihan eksplisit pengguna dan MENANG atas apa pun. Ia yang
    paling tahu ke mana videonya akan diunggah, dan lima contoh yang pernah
    diukur punya lima rasio berbeda di kategori yang sama — jadi tidak ada
    tebakan dari jenis yang bisa mengalahkannya.

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
    # yang diganti di sini. `None` berarti biarkan apa adanya.
    if rasio and rasio != "auto":
        p.aspect_ratio = rasio
        sumber_rasio = "pilihan pengguna"
    elif aturan["rasio"] is not None:
        p.aspect_ratio = aturan["rasio"]
        sumber_rasio = f"bawaan {jenis}"
    else:
        sumber_rasio = "dari konsep"
    p.caption.ada = bool(aturan["subtitle"])

    log.info(
        "jenis '%s': rasio %s, subtitle %s, lagu %.0f dB",
        jenis,
        f"{p.aspect_ratio} ({sumber_rasio})",
        "ya" if aturan["subtitle"] else "tidak",
        aturan["gain_db"],
    )
    return p
