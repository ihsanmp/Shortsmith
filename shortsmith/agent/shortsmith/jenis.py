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

## Apa yang diukur dari contoh yang dikirim pengguna

    AMV  kuroshin031      1024x576 16:9        shot 0,32s  2,10/dtk  tanpa subtitle
    AMV  hatsune_arima0    576x746  3:4 potret  shot 0,33s  2,02/dtk  tanpa subtitle
    CINE rpm.cinema        576x1024 9:16 potret shot 1,90s  0,35/dtk  tanpa subtitle
    CINE bubbawubba7      1280x720  16:9        shot 1,03s  0,68/dtk  tanpa subtitle
    POD  thecliper554     1024x576  16:9        shot 2,00s  0,26/dtk  SUBTITLE terbakar

Rasio berbeda-beda di semua kategori, jadi ia bukan penanda apa pun. Yang
memisahkan dengan bersih cuma dua hal:

  - **Ritme.** AMV 0,32-0,33 detik per shot; sisanya 1,0-2,0 detik. Beda hampir
    enam kali lipat, dan tidak ada yang berada di antaranya.
  - **Subtitle.** Ada pada podcast (dan short); tidak ada pada cinematic dan AMV.

Cinematic dan podcast TIDAK terpisah oleh ritme — 1,90 lawan 2,00 detik praktis
sama. Yang membedakan keduanya adalah ada tidaknya ucapan yang perlu dibaca.

Ritme itu sengaja TIDAK diatur di file ini. Ia justru hal yang paling tepat
diukur lewat konsep: buat konsep dari beberapa video contoh, dan
`avg_shot_length` terisi dari bahan yang sebenarnya — bukan dari angka yang
diketik seseorang di sini.
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

# `rasio: None` berarti JANGAN ditimpa — pakai apa pun yang ditetapkan konsep.
#
# AMV dan cinematic sempat dipaksa 16:9 di sini. Keduanya terbantah oleh contoh
# yang dikirim pengguna, yang rasionya justru berbeda-beda semua:
#
#     AMV kuroshin031      1024x576  16:9
#     AMV hatsune_arima0    576x746  3:4 potret
#     cinematic rpm.cinema  576x1024 9:16 potret
#
# Rasio bukan penanda jenis — ia mengikuti ke mana videonya diunggah, dan itu
# sudah diukur konsep dari video contohnya sendiri.
#
# Short tetap dipaksa 9:16, dan itu bukan pengecualian yang sembarangan: TikTok,
# Reels, dan Shorts memang mensyaratkannya. Itu tuntutan platform, bukan selera
# gaya yang bisa diukur dari bahan.
ATURAN: dict[str, dict] = {
    "short": {"rasio": "9:16", "subtitle": True, "gain_db": GAIN_LATAR},
    "cinematic": {"rasio": None, "subtitle": False, "gain_db": GAIN_LATAR},
    "amv": {"rasio": None, "subtitle": False, "gain_db": GAIN_UTAMA},
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
