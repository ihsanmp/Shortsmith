"""Deteksi format sebuah video contoh: satu jalur, atau audio + overlay B-roll.

## Kenapa ini yang paling menentukan

"Konsep" sebelum ini hanya mengukur tempo — durasi, jumlah potongan, panjang
shot rata-rata. Angkanya bisa tepat sasaran sementara hasilnya terasa asing,
karena yang membentuk gaya bukan tempo melainkan BENTUKNYA: apakah gambar terikat
pada suara, atau berjalan sendiri di atasnya.

Dua format itu tidak bisa saling meniru. Di format satu jalur, tiap potongan
harus memuat frasa utuh, sehingga panjang shot punya batas bawah alami sekitar
dua detik. Di format overlay, gambar boleh berganti tiap sedetik tanpa peduli
kalimatnya sampai mana. Menyetel parameter tidak akan pernah menjembataninya.

## Cara mengukurnya

Kalau video dipotong mengikuti ucapan, batas shot akan **jatuh di celah antar
kata** — itulah satu-satunya tempat memotong tanpa memenggal kata. Kalau gambar
berjalan sendiri, batas shot tersebar acak, tidak peduli di mana orangnya sedang
bicara.

Jadi yang diukur adalah proporsi batas shot yang mendarat di celah bicara. Angka
mentahnya sendiri tidak berarti apa-apa: video dengan banyak celah akan punya
proporsi tinggi karena kebetulan saja. Karena itu ia selalu dibandingkan dengan
**peluang acak** — berapa proporsi yang diharapkan kalau batas shot ditaburkan
sembarangan di sepanjang durasi. Rasio keduanya yang jadi bukti.

## Kenapa celah antar kata, bukan jeda hening

Versi pertama memakai `silencedetect`. Ia gagal justru pada format yang paling
ingin dikenali: video contoh dengan bed musik tidak pernah turun di bawah ambang
hening, sehingga TIDAK ADA jeda yang terdeteksi sama sekali — nol dari nol.
Kesimpulannya kebetulan benar, tapi lewat cabang darurat, bukan pengukuran. Dan
kegagalannya berbahaya ke arah sebaliknya: video wajah-bicara yang diberi musik
juga tidak punya jeda, dan akan salah terbaca sebagai overlay.

Batas antar kata dari transkrip kebal terhadap musik, karena ia mengukur di mana
suaranya ADA, bukan di mana levelnya rendah. Jeda hening tetap dipakai sebagai
cadangan kalau transkrip tidak tersedia.

Seluruh pengukuran ini memakai ffmpeg, PySceneDetect, dan Whisper lokal. Nol token.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import accumulate
from pathlib import Path

from .models import SilenceGap, Word

log = logging.getLogger(__name__)

# Celah antar kata yang lebih pendek dari ini bukan tempat memotong — itu cuma
# spasi antar suku kata. Ambang di bawah 0.15s membuat hampir seluruh video
# terlihat "penuh titik potong" dan pengukuran jadi tak bermakna.
MIN_CELAH = 0.18

# Toleransi kedekatan batas shot ke tepi jeda hening. Editor memotong "di
# sekitar" jeda, bukan tepat di frame pertama keheningan, dan deteksi shot
# sendiri punya galat beberapa frame.
TOLERANSI = 0.35

# Berapa kali lipat di atas peluang acak sebelum korelasinya dianggap nyata.
# 1.6 dipilih longgar dengan sengaja: salah menebak "satu jalur" hanya membuat
# hasil terasa lambat, sedangkan salah menebak "overlay" menghasilkan video
# yang gambarnya tidak nyambung sama sekali dengan yang diucapkan.
AMBANG_RASIO = 1.6

# Di bawah ini sampelnya terlalu sedikit untuk menyimpulkan apa pun.
MIN_BATAS = 4

# Celah sebesar ini atau lebih dianggap batas antar PENGGAL SUARA — tempat
# editor menyambung dua rekaman, bukan sekadar tarikan napas antar kalimat.
CELAH_PENGGAL = 0.40


@dataclass(frozen=True)
class HasilFormat:
    format: str  # "satu-jalur" | "overlay"
    teramati: float  # proporsi batas shot yang jatuh di jeda hening
    peluang: float  # proporsi yang diharapkan kalau ditaburkan acak
    rasio: float  # teramati / peluang
    jumlah_batas: int
    yakin: bool

    # Berapa penggal suara yang membentuk contoh ini.
    #
    # Besaran ini SANGAT berbeda dari jumlah shot, dan mencampurnya adalah
    # kesalahan yang mahal: satu contoh nyata punya 22 pergantian gambar tapi
    # audionya hanya 4 penggal. Menyuruh model membuat 21 sambungan suara
    # menghasilkan audio yang tersendat, karena tiap sambungan adalah tempat
    # room tone melompat dan konsonan terpotong.
    penggal_suara: int = 0

    @property
    def overlay(self) -> bool:
        return self.format == "overlay"

    def ringkas(self) -> str:
        if not self.yakin:
            return (
                f"format tidak bisa disimpulkan (hanya {self.jumlah_batas} batas shot) "
                f"-> dianggap {self.format}"
            )
        return (
            f"{self.format}: {self.teramati:.0%} batas shot jatuh di celah bicara, "
            f"peluang acak {self.peluang:.0%} (rasio {self.rasio:.1f}x)"
        )


def zona_dari_kata(words: list[Word], *, min_celah: float = MIN_CELAH) -> list[SilenceGap]:
    """Ubah timestamp per kata jadi daftar celah yang layak dipotong.

    Celah pembuka (sebelum kata pertama) dan penutup (setelah kata terakhir)
    sengaja TIDAK dimasukkan: hampir semua video punya keduanya, dan keduanya
    akan menaikkan peluang acak tanpa memberi informasi apa pun soal gaya potong.
    """
    urut = sorted(words, key=lambda w: w.start)
    zona: list[SilenceGap] = []
    for sebelum, sesudah in zip(urut, urut[1:]):
        if sesudah.start - sebelum.end >= min_celah:
            zona.append(SilenceGap(start=sebelum.end, end=sesudah.start))
    return zona


def _batas_shot(panjang_shot: list[float]) -> list[float]:
    """Ubah daftar PANJANG shot jadi daftar WAKTU batas antar shot.

    Batas terakhir dibuang: ujung video bukan keputusan memotong, ia cuma tempat
    videonya habis. Memasukkannya akan mencemari statistik pada video pendek.
    """
    if len(panjang_shot) < 2:
        return []
    return list(accumulate(panjang_shot))[:-1]


def _dekat_jeda(t: float, jeda: list[SilenceGap], toleransi: float) -> bool:
    return any(g.start - toleransi <= t <= g.end + toleransi for g in jeda)


def deteksi_format(
    panjang_shot: list[float],
    jeda: list[SilenceGap],
    durasi: float,
    *,
    toleransi: float = TOLERANSI,
) -> HasilFormat:
    """Simpulkan format dari panjang shot, jeda hening, dan durasi total."""
    batas = _batas_shot(panjang_shot)

    # Penggal suara = jumlah celah besar + 1. Celah kecil adalah napas antar
    # kalimat di dalam satu rekaman, bukan titik sambung.
    penggal = 1 + sum(1 for g in jeda if g.durasi >= CELAH_PENGGAL) if jeda else 0

    if len(batas) < MIN_BATAS or durasi <= 0:
        # Tanpa cukup data, jatuhkan ke satu jalur — pilihan yang lebih aman,
        # karena kegagalannya hanya membuat hasil terasa lambat.
        return HasilFormat("satu-jalur", 0.0, 0.0, 0.0, len(batas), yakin=False, penggal_suara=penggal)

    if not jeda:
        # Tidak ada celah bicara sama sekali. Ini BUKAN bukti overlay — bisa
        # juga berarti pengukurannya yang gagal (mis. transkrip kosong, atau
        # ambang hening tidak pernah tercapai karena ada musik). Menyimpulkan
        # format dari ketiadaan data adalah persis kesalahan yang membuat versi
        # pertama modul ini menjawab benar karena kebetulan.
        return HasilFormat("satu-jalur", 0.0, 0.0, 0.0, len(batas), yakin=False, penggal_suara=penggal)

    kena = sum(1 for t in batas if _dekat_jeda(t, jeda, toleransi))
    teramati = kena / len(batas)

    # Peluang acak: total lebar "zona jeda" (termasuk toleransi di kedua sisi)
    # dibagi durasi video. Inilah proporsi yang akan tercapai bahkan kalau batas
    # shot ditaburkan sembarangan.
    lebar = sum(g.durasi + 2 * toleransi for g in jeda)
    peluang = min(1.0, lebar / durasi)

    rasio = teramati / peluang if peluang > 0 else 0.0
    format_ = "satu-jalur" if rasio >= AMBANG_RASIO else "overlay"

    return HasilFormat(format_, teramati, peluang, rasio, len(batas), yakin=True, penggal_suara=penggal)


def deteksi_dari_file(path: str | Path) -> HasilFormat:
    """Ukur langsung dari satu file video. Dipakai saat ekstraksi konsep.

    Video contoh selalu pendek (puluhan detik), jadi mentranskripnya murah —
    beberapa detik komputasi. Itu harga yang pantas untuk pengukuran yang tidak
    runtuh begitu ada musik di belakang suaranya.
    """
    from .analyze import detect_silence
    from .asr import transcribe
    from .probe import probe
    from .profile import _detect_cuts

    media = probe(path)
    shots = _detect_cuts(path)

    zona: list[SilenceGap] = []
    sumber = "tidak ada audio"
    if media.punya_audio:
        try:
            _, words = transcribe(path)
            zona = zona_dari_kata(words)
            sumber = f"celah antar kata ({len(words)} kata)"
        except Exception as exc:  # noqa: BLE001 — ASR punya banyak mode gagal
            log.warning("transkrip contoh gagal (%s) — jatuh ke deteksi hening", exc)

        if not zona:
            zona = detect_silence(path)
            sumber = "jeda hening (cadangan)"

    hasil = deteksi_format(shots, zona, media.durasi)
    log.info("format %s [%s] -> %s", Path(path).name, sumber, hasil.ringkas())
    return hasil
