"""Meratakan eksposur antar klip, supaya potongannya tidak berkedip.

## Masalah yang diukur, bukan yang dibayangkan

Bahan mentah datang dari rekaman yang berbeda-beda — kamera lain, jam lain,
ruangan lain. Pipeline ini menyambungnya tanpa pernah menyentuh warnanya sama
sekali, jadi tiap potongan mewarisi eksposur aslinya. Terukur pada satu hasil
render nyata, kecerahan rata-rata (0-255) tepat sebelum dan sesudah tiap
pergantian klip di hasil jadinya::

    t= 3.83   27.6 -> 110.8   selisih 83.2
    t=10.10   85.2 ->  44.8   selisih 40.5
    t=24.83   43.1 ->  85.6   selisih 42.6
    t=27.77   87.9 ->  25.8   selisih 62.1
    t=30.70   24.9 ->  79.9   selisih 55.0

    median 26.7   maks 83.2   lompatan >25: 6 dari 12

Lompatan 27,6 ke 110,8 adalah empat kali lipat kecerahan dalam satu frame. Itu
bukan gaya, itu kelihatan seperti kesalahan.

## Kenapa menyamakan sepenuhnya justru salah

Menarik tiap klip ke satu kecerahan yang sama akan memaksa shot malam jadi
seterang shot siang. Gelap yang disengaja adalah bagian dari gambarnya — pada
contoh cinematic yang dikirim pengguna, 67-82 persen pikselnya memang gelap.
Meratakan habis akan menghapus justru hal yang membuatnya cinematic.

Jadi yang dilakukan di sini adalah koreksi SEBAGIAN: tiap klip ditarik
`KEKUATAN` bagian dari jarak menuju median timeline-nya sendiri, dan tidak
pernah lebih jauh dari `GAMMA_MIN..GAMMA_MAX`. Perbedaan antar shot tetap
terbaca; yang hilang cuma bagian ekstremnya.

## Kenapa median timeline, bukan angka tetap

Rujukan yang benar adalah video ini sendiri. Angka mutlak (misalnya "semua klip
ke 0,48") tidak tahu apa-apa soal apakah videonya memang gelap dari awal sampai
akhir — dan pada video yang seluruhnya gelap, ia akan mencerahkan semuanya.
Median timeline bergerak mengikuti bahannya: pada video gelap ia rendah, dan
klip-klipnya diratakan terhadap gelap itu.

Median, bukan rata-rata: satu klip yang sangat terang menggeser rata-rata cukup
jauh untuk menyeret semua klip lain menjauhi kecerahan mereka sendiri.
"""

from __future__ import annotations

import logging
import math
import subprocess
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

# Berapa bagian dari jarak menuju median yang ditempuh. 1,0 berarti semua klip
# jadi sama terang persis — dan itu yang justru dihindari (lihat docstring).
#
# 0,55 diuji dengan MERENDER ULANG satu video nyata dua kali dan mengukur
# hasilnya, bukan dengan menyimulasikannya::
#
#     lompatan di hasil jadi   median   rata   maks   di atas 25
#     sebelum                    26,7   31,1   83,2     6 dari 12
#     sesudah                    23,3   23,1   57,3     4 dari 12
#
# Jujur soal batasnya: perbaikan terbesar ada di kasus terburuk (maks turun
# 31%, rata-rata 26%), sementara tiga transisi yang tadinya mulus justru jadi
# sedikit lebih kasar. Sebabnya melekat pada rancangannya — koreksinya satu
# gamma untuk seluruh klip, dihitung dari kecerahan RATA-RATA klip itu,
# sedangkan yang benar-benar bertemu di titik potong adalah frame di TEPI-nya.
# Klip yang tepinya jauh berbeda dari rata-ratanya sendiri akan bergeser ke
# arah yang salah di titik itu.
#
# Sapuan terhadap tepi klip yang sebenarnya menunjukkan 0,75 dan 1,0 memberi
# angka lebih baik lagi (maks 34,0 dan 31,5). Keduanya tidak dipakai: 1,0
# berarti semua klip jadi sama terang persis, dan itu menghapus beda
# terang-gelap antar shot yang memang ada di bahannya. Angka-angka itu juga
# datang dari SATU video berisi 13 potongan — menyetel sampai angka terbaik di
# satu contoh adalah menyetel ke contoh itu, bukan ke bahan yang belum dilihat.
KEKUATAN = 0.55

# Batas keras. Gamma di luar rentang ini mulai meratakan bagian gelap jadi abu
# atau membakar bagian terang, dan pada titik itu koreksinya sendiri yang jadi
# cacat paling terlihat.
GAMMA_MIN = 0.80
GAMMA_MAX = 1.25

# Di bawah ini koreksinya tidak terlihat, dan menambahkan satu filter ffmpeg per
# potongan untuk perubahan yang tidak terlihat cuma memperlambat render.
GAMMA_ABAI = 0.02

# Berapa frame yang diambil per potongan. Satu frame bisa kebetulan jatuh di
# kilatan atau di potongan hitam antar-shot; tiga tersebar membuat satu frame
# menyimpang tidak menentukan seluruh koreksi klip itu.
CUPLIK = 3

# Luma yang sudah terlalu dekat 0 atau 1 membuat solusi gamma meledak (ln
# mendekati nol atau tak hingga). Klip seperti itu memang hampir hitam pekat
# atau hampir putih penuh, dan tidak ada gamma yang menolongnya.
LUMA_MIN = 0.02
LUMA_MAX = 0.98


@dataclass
class Ukuran:
    """Kecerahan satu potongan, ternormalisasi 0-1."""

    luma: float
    ok: bool = True


def _luma(src: str, t: float, crop: str = "") -> float | None:
    """Kecerahan rata-rata satu frame di detik `t` dari `src`.

    `crop` adalah crop pembuang bilah hitam yang sama dengan yang dipakai
    renderer. Ia WAJIB ikut di sini: bilah hitam yang terbakar di berkas asalnya
    ikut terhitung kalau tidak dibuang, dan sebuah klip 16:9 di dalam bingkai
    9:16 akan terukur jauh lebih gelap daripada gambarnya yang sebenarnya —
    lalu dikoreksi terang-terang, padahal yang gelap cuma bilahnya.
    """
    hasil = subprocess.run(
        [
            "ffmpeg", "-v", "error",
            "-ss", f"{max(0.0, t):.3f}",
            "-i", src,
            "-frames:v", "1",
            # Diperkecil dulu: yang dicari rata-rata, dan merata-ratakan 160
            # piksel memberi angka yang sama dengan merata-ratakan 1920 sambil
            # memindahkan pekerjaannya ke scaler.
            "-vf", (f"crop={crop}," if crop else "") + "scale=160:-1",
            "-f", "rawvideo", "-pix_fmt", "gray", "-",
        ],
        capture_output=True,
    )
    if hasil.returncode != 0 or not hasil.stdout:
        return None
    return float(np.frombuffer(hasil.stdout, dtype=np.uint8).mean()) / 255.0


def ukur(src: str, t_awal: float, t_akhir: float, crop: str = "") -> Ukuran:
    """Ukur kecerahan rentang yang benar-benar dipakai dari sebuah file.

    Rentangnya, bukan seluruh filenya: yang masuk ke hasil cuma potongan ini,
    dan sebuah file bisa berisi shot terang di menit pertama dan shot gelap di
    menit kelima.
    """
    durasi = max(0.0, t_akhir - t_awal)
    if durasi <= 0:
        return Ukuran(luma=0.0, ok=False)

    # Tepi dihindari: potongan sering dimulai atau berakhir tepat di transisi,
    # dan frame transisi tidak mewakili isi potongannya.
    titik = [t_awal + durasi * f for f in (0.25, 0.5, 0.75)][:CUPLIK]
    nilai = [v for v in (_luma(src, t, crop) for t in titik) if v is not None]
    if not nilai:
        log.warning("gagal mengukur kecerahan: %s @ %.2f", src, t_awal)
        return Ukuran(luma=0.0, ok=False)
    return Ukuran(luma=float(np.median(nilai)))


def _gamma(luma: float, target: float) -> float:
    """Gamma ffmpeg yang memindahkan `luma` sebagian jalan menuju `target`.

    `eq=gamma=g` di ffmpeg memetakan masukan ternormalisasi lewat pow(x, 1/g),
    jadi rata-ratanya bergerak dari m ke m**(1/g). Menyelesaikannya untuk tujuan
    t memberi g = ln(m) / ln(t) persis — tanpa mencoba-coba.
    """
    m = min(LUMA_MAX, max(LUMA_MIN, luma))
    t = min(LUMA_MAX, max(LUMA_MIN, target))

    # Tujuan sebagian: bergerak KEKUATAN bagian dari m ke t, di ruang log —
    # ruang yang sama tempat gamma bekerja, jadi langkahnya seragam untuk klip
    # gelap maupun terang.
    tujuan = math.exp(math.log(m) + KEKUATAN * (math.log(t) - math.log(m)))
    tujuan = min(LUMA_MAX, max(LUMA_MIN, tujuan))

    g = math.log(m) / math.log(tujuan)
    return min(GAMMA_MAX, max(GAMMA_MIN, g))


def ratakan(ukuran: list[Ukuran]) -> list[str]:
    """Ubah hasil pengukuran jadi satu filter ffmpeg per potongan.

    Mengembalikan daftar sepanjang masukan; entri yang tidak perlu dikoreksi
    berisi string kosong, dan pemanggil melewatkannya begitu saja.
    """
    hidup = [u.luma for u in ukuran if u.ok]
    if len(hidup) < 2:
        # Satu potongan tidak bisa melompat terhadap apa pun.
        return ["" for _ in ukuran]

    target = float(np.median(hidup))
    keluar: list[str] = []
    dikoreksi = 0

    for u in ukuran:
        if not u.ok:
            keluar.append("")
            continue
        g = _gamma(u.luma, target)
        if abs(g - 1.0) < GAMMA_ABAI:
            keluar.append("")
            continue
        keluar.append(f"eq=gamma={g:.3f}")
        dikoreksi += 1

    log.info(
        "perataan warna: target luma %.3f, %d dari %d potongan dikoreksi",
        target, dikoreksi, len(ukuran),
    )
    return keluar


def ratakan_edl(edl) -> int:
    """Isi field `warna` tiap potongan di sebuah EDL. Kembalikan jumlah koreksi.

    Menerima kedua bentuk EDL: yang berpotongan lurus (`.cuts`) maupun yang
    memisah gambar dari suara (`.video`). Yang diratakan hanya jalur GAMBAR —
    di format overlay, `.audio.cuts` tidak punya gambar untuk dikoreksi.

    Tidak pernah melempar. Perataan warna adalah penghalusan, bukan syarat
    hasilnya jadi; kalau pengukurannya gagal karena satu berkas tidak terbaca,
    render tetap harus berjalan dengan warna aslinya — bukan berhenti.
    """
    try:
        potongan = list(getattr(edl, "video", None) or getattr(edl, "cuts", []))
        if len(potongan) < 2:
            return 0

        ukuran = []
        for p in potongan:
            awal = float(p.in_)
            # Slot overlay menyimpan panjangnya sebagai `durasi`; potongan lurus
            # menyimpan ujungnya sebagai `out`. Keduanya menunjuk hal yang sama.
            akhir = float(p.out) if hasattr(p, "out") else awal + float(p.durasi)
            ukuran.append(ukur(p.src, awal, akhir, getattr(p, "crop", "") or ""))

        for p, filt in zip(potongan, ratakan(ukuran)):
            p.warna = filt

        return sum(1 for p in potongan if p.warna)
    except Exception:
        log.warning("perataan warna dilewati", exc_info=True)
        for p in list(getattr(edl, "video", None) or getattr(edl, "cuts", [])):
            p.warna = ""
        return 0
