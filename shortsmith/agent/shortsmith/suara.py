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

        # Gain musik dihitung DI SINI, memakai pengukuran yang sudah ada.
        #
        # Kenyaringan ucapan baru saja diukur untuk perataan di atas; mengukur
        # ulang berarti menjalankan ebur128 kedua kali atas audio yang sama.
        # Dan tempat ini benar secara urutan: musik sudah menempel di EDL, dan
        # ucapannya sudah rata -- jadi yang dijadikan acuan adalah tingkat
        # akhir, bukan tingkat sebelum diratakan.
        musik = getattr(edl, "music", None)
        hidup = [x for x in nilai if x is not None]
        if musik is not None and hidup:
            t, v = profil_lagu(musik.src)
            if v:
                # Bagian tengah lagu, bukan seluruhnya: intro dan ekor yang
                # memudar menarik rata-ratanya turun, dan yang akan terdengar
                # adalah bagian yang dipilih pilih_bagian -- bukan intronya.
                tengah = [
                    x for x, tt in zip(v, t)
                    if 0.1 * t[-1] <= tt <= 0.9 * t[-1]
                ] or v
                musik.gain_db = gain_musik_untuk(
                    float(np.median(tengah)), float(np.median(hidup)), musik.gain_db
                )

        return sum(1 for c in cuts if c.gain_db)
    except Exception:  # noqa: BLE001
        log.warning("perataan suara dilewati", exc_info=True)
        return 0


# --------------------------------------------------------------------------
# Memilih bagian lagu yang dipakai
# --------------------------------------------------------------------------

# Seberapa berat keragaman dihukum saat memilih bagian lagu.
#
# Bukan sekadar "pilih yang paling keras". Lagu ini dipasang DI BAWAH ucapan,
# dan bagian yang naik-turun tajam menarik perhatian menjauh dari yang bicara --
# persis kebalikan dari gunanya musik latar. Setengah berarti satu satuan
# simpangan baku menghapus setengah satuan kenyaringan.
BOBOT_RAGAM = 0.5

# Jarak antar titik awal yang dicoba, dalam detik. Lebih rapat tidak mengubah
# pilihan secara berarti karena kenyaringan lagu bergerak lambat.
LANGKAH_CARI = 5.0


def profil_lagu(src: str) -> tuple[list[float], list[float]]:
    """(detik, LUFS sesaat) sepanjang lagu. Kosong kalau gagal dibaca."""
    hasil = subprocess.run(
        [SETTINGS.ffmpeg, "-hide_banner", "-i", src, "-af", "ebur128", "-f", "null", "-"],
        capture_output=True,
        text=True,
        errors="replace",
    )
    t: list[float] = []
    v: list[float] = []
    for baris in hasil.stderr.split("\n"):
        m = _POLA.search(baris)
        if m:
            nilai = float(m.group(2))
            if nilai > HENING_LUFS:
                t.append(float(m.group(1)))
                v.append(nilai)
    return t, v


def pilih_bagian(src: str, durasi: float) -> float:
    """Detik mulai bagian lagu yang paling pantas untuk video sepanjang ini.

    ## Kenapa tidak dari detik nol

    Lagu punya intro. Terukur pada satu lagu nyata sepanjang 218 detik::

        0-20 detik      sekitar -13,5 LUFS   <- intro
        20-200 detik    sekitar  -6,5 LUFS   <- badan lagu
        210 detik ke atas       -15,9 LUFS   <- memudar

    Untuk klip 77 detik, memulai dari nol cuma merugi 1,3 LU karena intronya
    terencerkan oleh sisanya. Untuk klip 20-30 detik, hampir SELURUH klip berisi
    intro -- bagian lagu yang paling tidak dikenali orang.

    ## Kenapa bukan sekadar bagian paling keras

    Musik ini dipasang di bawah ucapan. Bagian yang naik-turun tajam menarik
    perhatian menjauh dari yang bicara, jadi keragamannya ikut dihukum lewat
    BOBOT_RAGAM. Yang dicari bagian yang mantap, bukan yang paling dramatis.

    Kembalikan 0.0 kalau lagunya tidak bisa dibaca atau terlalu pendek untuk
    dipilih-pilih -- perilaku lama, dan tidak pernah lebih buruk dari itu.
    """
    if durasi <= 0:
        return 0.0
    try:
        t, v = profil_lagu(src)
    except Exception:  # noqa: BLE001
        return 0.0
    if len(t) < 10 or t[-1] <= durasi:
        return 0.0

    tt = np.array(t)
    vv = np.array(v)
    terbaik, skor_terbaik = 0.0, -1e9
    mulai = 0.0
    while mulai + durasi <= tt[-1]:
        sel = vv[(tt >= mulai) & (tt < mulai + durasi)]
        if sel.size >= 5:
            skor = float(np.median(sel)) - BOBOT_RAGAM * float(np.std(sel))
            if skor > skor_terbaik:
                skor_terbaik, terbaik = skor, mulai
        mulai += LANGKAH_CARI

    if terbaik > 0:
        log.info(
            "bagian lagu dipilih: mulai %.0f detik (skor %.1f, lawan %.1f dari awal)",
            terbaik,
            skor_terbaik,
            float(np.median(vv[tt < durasi]))
            - BOBOT_RAGAM * float(np.std(vv[tt < durasi])),
        )
    return terbaik


# Seberapa jauh musik latar berada DI BAWAH ucapan, dalam LU.
#
# Angka ini yang menggantikan gain tetap, dan alasannya terukur. Gain tetap
# -20 dB mengandaikan lagu dan rekaman berada di tingkat yang mirip. Pada satu
# pasangan nyata keduanya berjauhan 17 LU::
#
#     ucapan di video    -23,4 LUFS
#     badan lagu          -6,4 LUFS   <- di-master jauh lebih keras
#     gain -20 dB    ->  musik -26,4 LUFS, hanya 3,0 LU di bawah ucapan
#
# Tiga LU praktis sama kerasnya: musiknya bersaing dengan yang bicara, bukan
# menemaninya. Delapan belas adalah tengah dari patokan umum 15-20 LU untuk
# musik latar di bawah ucapan.
SEPARASI_LU = 18.0

# Batas keras gain, dalam dB. Lagu yang direkam sangat pelan tidak dinaikkan
# sampai deraunya ikut terdengar, dan lagu yang sangat keras tidak dipotong
# sampai hilang sama sekali.
GAIN_MIN_DB = -42.0
GAIN_MAKS_DB = -12.0


def gain_musik_untuk(lagu_lufs: float | None, ucapan_lufs: float | None,
                     bawaan: float = -20.0) -> float:
    """Gain lagu supaya ia duduk SEPARASI_LU di bawah ucapan.

    Kembalikan `bawaan` kalau salah satu tidak terukur — menebak dari satu sisi
    saja lebih buruk daripada memakai angka yang sudah dikenal.
    """
    if lagu_lufs is None or ucapan_lufs is None:
        return bawaan
    gain = (ucapan_lufs - SEPARASI_LU) - lagu_lufs
    gain = max(GAIN_MIN_DB, min(GAIN_MAKS_DB, gain))
    log.info(
        "gain lagu dihitung: ucapan %.1f, lagu %.1f -> %.1f dB (terpisah %.1f LU)",
        ucapan_lufs, lagu_lufs, gain, ucapan_lufs - (lagu_lufs + gain),
    )
    return round(gain, 1)
