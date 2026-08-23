"""Rapikan batas potongan suara ke jeda hening yang sungguhan.

## Masalah yang diperbaiki

Model memilih rentang dari transkrip, dan timestamp transkrip **bersambung**:
akhir satu kata persis jadi awal kata berikutnya. Akibatnya setiap potongan
dimulai tepat saat kata pertama mulai berbunyi dan berakhir tepat saat kata
terakhir habis — nol ruang napas di kedua ujung.

Diukur pada satu job nyata: 38 dari 38 batas punya ruang 0,000 detik. Yang
terdengar bukan cuma tergesa. Timestamp Whisper juga hanya perkiraan, biasanya
meleset beberapa puluh milidetik, sehingga konsonan penutup ikut terpotong.

## Kenapa jeda hening, bukan timestamp kata

Menghitung ruang dari timestamp kata selalu menghasilkan nol, karena Whisper
tidak pernah menyisakan celah di antara kata — ia membagi waktu secara kontinu.
Angka itu tidak mencerminkan audionya sama sekali.

`silencedetect` mengukur audio yang sebenarnya. Di rekaman yang sama ia
menemukan 385 jeda, dan 11 dari 38 batas ternyata SUDAH berada di dalam salah
satunya. 17 lagi berjarak kurang dari 0,15 detik — cukup dekat untuk digeser
tanpa mengubah kalimat yang terpilih.

## Yang tidak bisa diperbaiki di sini

Sisanya jatuh di tengah frasa yang memang tidak punya jeda. Menggesernya jauh
akan mengubah isi kalimat, dan itu bukan wewenang modul ini. Untuk batas
semacam itu, fade pendek di renderer yang menanggungnya.
"""

from __future__ import annotations

import logging
import subprocess

from .models import PlannedCut, SilenceGap, Word

log = logging.getLogger(__name__)

# Seberapa jauh sebuah batas boleh digeser untuk mencapai jeda. Di atas ini,
# pergeseran mulai memakan atau membuang kata, dan potongan tidak lagi berisi
# kalimat yang dipilih model.
TOLERANSI = 0.15

# Ruang napas yang disisakan saat batas DIGESER masuk ke jeda: sedikit hening
# sebelum suara masuk, dan sedikit ekor setelah suara habis.
NAPAS = 0.08

# Batas atas hening yang dibiarkan menempel di ujung potongan. Di bawah ini
# tidak diapa-apakan; di atas ini dipangkas supaya tidak ada dead air panjang.
#
# Angka ini sengaja longgar. Versi pertama modul ini memangkas setiap batas ke
# NAPAS, termasuk yang sudah berada di dalam hening — dan pengukuran menunjukkan
# itu keliru: dua dari empat pangkasan besar ternyata membuang audio dengan
# puncak -21 dB dan -25 dB, hanya belasan desibel di bawah ucapan. Itu tarikan
# napas sebelum bicara. Membuangnya justru membuat suara terdengar LEBIH
# mendadak, persis kebalikan dari tujuan modul ini.
MAKS_HENING = 0.40


def _jeda_dekat(t: float, jeda: list[SilenceGap], toleransi: float) -> SilenceGap | None:
    """Jeda yang memuat `t`, atau yang tepinya paling dekat dalam toleransi."""
    terdekat: SilenceGap | None = None
    terbaik = toleransi
    for g in jeda:
        if g.start <= t <= g.end:
            return g
        d = min(abs(t - g.start), abs(t - g.end))
        if d <= terbaik:
            terbaik, terdekat = d, g
    return terdekat


# Toleransi tepi saat memeriksa apakah sebuah titik ada di tengah kata.
# Timestamp Whisper meleset beberapa puluh milidetik, jadi memotong tepat di
# angka tepi kata masih dianggap aman.
TEPI_KATA = 0.02


def _di_tengah_kata(t: float, kata: list[Word]) -> Word | None:
    for k in kata:
        if k.start + TEPI_KATA < t < k.end - TEPI_KATA:
            return k
    return None


def rapikan_batas(
    cuts: list[PlannedCut],
    jeda: list[SilenceGap],
    kata: list[Word] | None = None,
    *,
    toleransi: float = TOLERANSI,
    napas: float = NAPAS,
) -> tuple[int, int]:
    """Geser in/out tiap potongan ke jeda hening terdekat, di tempat.

    `kata` adalah pagar pengaman, dan bukan hiasan: `silencedetect` mengukur
    LEVEL audio, sehingga bagian pelan DI DALAM sebuah kata bisa ikut terbaca
    sebagai hening. Versi pertama modul ini menggeser batas ke titik semacam itu
    tanpa memeriksa apa pun, dan hasilnya terukur: dari 0 batas yang jatuh di
    tengah kata, menjadi 8 dari 38. Yang terdengar adalah penggalan kata —
    persis "suara kecampur" yang dilaporkan.

    Sekarang setiap kandidat posisi diperiksa dulu. Kalau ia mendarat di tengah
    kata, pergeseran DIBATALKAN dan batas aslinya dipertahankan. Karena rencana
    dari model selalu berbatas di tepi kata, aturan ini menjamin perapian tidak
    pernah membuat keadaan lebih buruk daripada tidak dirapikan sama sekali.

    Kembalikan (jumlah_awal_dirapikan, jumlah_akhir_dirapikan).
    """
    if not jeda:
        return 0, 0

    daftar_kata = kata or []

    def aman(t: float) -> bool:
        return _di_tengah_kata(t, daftar_kata) is None

    urut = sorted(jeda, key=lambda g: g.start)
    n_awal = n_akhir = 0

    for cut in cuts:
        # --- awal potongan ---
        g = _jeda_dekat(cut.in_, urut, toleransi)
        if g is not None:
            if g.start <= cut.in_ <= g.end:
                # Sudah di dalam hening: ruang napasnya sudah ada. Hanya
                # dipangkas kalau dead air-nya benar-benar panjang.
                sisa = g.end - cut.in_
                baru = g.end - MAKS_HENING if sisa > MAKS_HENING else cut.in_
            else:
                # Di luar hening — inilah kasus yang benar-benar perlu ditolong.
                # Geser masuk supaya ada hening pendek sebelum suara mulai.
                baru = max(g.start, g.end - napas)

            if abs(baru - cut.in_) > 1e-3 and baru < cut.out and aman(baru):
                cut.in_ = round(baru, 3)
                n_awal += 1

        # --- akhir potongan ---
        g = _jeda_dekat(cut.out, urut, toleransi)
        if g is not None:
            if g.start <= cut.out <= g.end:
                sisa = cut.out - g.start
                baru = g.start + MAKS_HENING if sisa > MAKS_HENING else cut.out
            else:
                baru = min(g.end, g.start + napas)

            if abs(baru - cut.out) > 1e-3 and baru > cut.in_ and aman(baru):
                cut.out = round(baru, 3)
                n_akhir += 1

    if n_awal or n_akhir:
        log.info(
            "batas dirapikan ke jeda hening: %d awal + %d akhir dari %d potongan",
            n_awal, n_akhir, len(cuts),
        )
    return n_awal, n_akhir


# ==========================================================================
# Perapian lapis kedua: berdasarkan energi audio, bukan timestamp
# ==========================================================================

# Sejauh mana batas boleh dipanjangkan KE LUAR untuk mencapai titik hening.
# Diukur pada satu job nyata: 100 ms memberi -9 dB, 150 ms memberi -25 dB, dan
# 200 ms hanya menambah 2 dB lagi. Jadi 150 ms adalah titik jenuhnya.
JENDELA_ENERGI = 0.15

# Pergeseran hanya dilakukan kalau titik barunya benar-benar jauh lebih sunyi.
# Tanpa syarat ini, di tengah ucapan yang mengalir terus modul ini akan
# menggeser batas ke titik acak yang kebetulan sedikit lebih pelan.
MIN_PERBAIKAN_DB = 6.0

# Perpanjangan minimum yang SELALU diterapkan, ada atau tidak ada titik sunyi.
#
# Timestamp Whisper ketat di DALAM rentang akustik kata: konsonan pembuka dan
# ekor peluruhan jatuh di luarnya. Kalau kata sebelumnya berbunyi terus tanpa
# jeda, syarat "harus lebih sunyi" tidak pernah terpenuhi dan batas dibiarkan
# apa adanya — hasilnya "dunia" terdengar jadi "unia".
#
# 50 ms cukup untuk memuat konsonan pembuka (plosif sekitar 20-40 ms) dan
# terlalu pendek untuk terdengar sebagai kata lain yang menyelinap masuk.
MARGIN_MIN = 0.05

_SR = 16000
_HOP = 0.005


def _pcm(src: str, mulai: float, durasi: float) -> "np.ndarray | None":
    import numpy as np

    from .config import SETTINGS

    hasil = subprocess.run(
        [
            SETTINGS.ffmpeg, "-v", "error",
            "-ss", f"{max(0.0, mulai):.3f}",
            "-i", str(src),
            "-t", f"{durasi:.3f}",
            "-vn", "-ac", "1", "-ar", str(_SR),
            "-f", "s16le", "-",
        ],
        capture_output=True,
    )
    if hasil.returncode != 0 or not hasil.stdout:
        return None
    return np.frombuffer(hasil.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def _semua_frame(x: "np.ndarray") -> "np.ndarray":
    """RMS per frame 10 ms, melangkah 5 ms."""
    import numpy as np

    hop = int(_HOP * _SR)
    win = int(0.010 * _SR)
    n = (len(x) - win) // hop
    return np.array([np.sqrt(np.mean(x[i * hop : i * hop + win] ** 2)) for i in range(max(0, n))])


def _titik_tersunyi(x: "np.ndarray") -> tuple[int, float, float]:
    """Kembalikan (indeks frame tersunyi, rms di situ, rms di frame pertama)."""
    import numpy as np

    frames = _semua_frame(x)
    if len(frames) == 0:
        return 0, 0.0, 0.0
    i = int(np.argmin(frames))
    return i, float(frames[i]), float(frames[0])


# Lebar pencarian dua arah. Lebih lebar dari JENDELA_ENERGI karena celah antar
# kata yang benar bisa jauh dari angka Whisper — terukur 220 ms pada satu kasus.
# Seberapa jauh hening dicari dari batas yang dipilih model, ke dua arah.
#
# Sempat 0,30 detik, dan itu terlalu sempit -- terukur pada satu hasil nyata,
# lebih dari separuh sambungan jatuh di tengah ucapan::
#
#     18 batas diperiksa
#      2 punya hening di dalam jendela 0,30 detik
#      5 punya hening, tapi 0,52-0,85 detik jauhnya
#     11 tidak punya hening yang memenuhi syarat sama sekali
#
# Aritmetikanya menjelaskan sendiri: rekaman itu punya sekitar 12 pita hening
# per 60 detik, satu tiap lima detik. Jendela 0,6 detik total pada jeda yang
# muncul tiap lima detik memberi peluang sekitar 12% -- dan yang terukur 2 dari
# 7, persis di situ.
#
# 0,90 menampung jarak terjauh yang terukur (0,85 detik). Lebih lebar lagi mulai
# memindahkan batas sejauh satu frasa penuh, dan yang didapat bukan potongan
# yang lebih bersih melainkan potongan yang isinya berbeda dari yang direncanakan.
JENDELA_CARI = 0.90

# Batas tidak boleh bergeser lebih dari sekian bagian panjang potongannya.
#
# Jendela yang lebar aman untuk potongan empat detik, tapi tidak untuk potongan
# satu detik: memindahkan batasnya 0,9 detik mengubah hampir seluruh isinya.
# Seperempat berarti potongan 4 detik boleh bergeser 1 detik, dan potongan 1
# detik hanya 0,25 detik.
MAKS_GESER_BAGIAN = 0.25

# Titik yang dipilih harus sunyi SUNGGUHAN, bukan sekadar paling sunyi di
# antara yang ada. Tanpa syarat absolut ini, pencarian di tengah kalimat akan
# memilih lembah kecil di antara dua suku kata dan memindahkan batas ke sana —
# yang justru memperparah pemenggalan.
AMBANG_HENING_MUTLAK = 0.0056  # ~-45 dB

# Panjang MINIMAL pita hening yang boleh dijadikan batas.
#
# Sunyi saja tidak cukup — konsonan letup (p, t, k, b, d, g) punya fase tutup
# yang benar-benar sunyi DI TENGAH kata. Terukur pada bahan pengguna, batas
# yang jatuh di dalam kata "stop" duduk di pita sunyi 100 ms, dan yang
# terdengar adalah ekornya: "top".
#
# Jeda antar kata jauh lebih panjang. Diukur di batas yang benar pada berkas
# yang sama: 380 ms, 540 ms, 540 ms. Ambang 200 ms duduk jauh dari keduanya.
MIN_HENING_LEBAR = 0.20


def _geser_ke_hening(src: str, t: float, jendela: float) -> float | None:
    """Titik paling sunyi di sekitar `t`, dicari ke DUA arah.

    ## Kenapa dua arah

    Versi sebelumnya hanya mencari ke luar — `out` maju, `in_` mundur — dengan
    alasan bahwa memanjangkan selalu menambah audio dan tidak pernah memenggal.
    Alasan itu benar, tapi asumsinya salah: ia menganggap batas selalu berada
    SEBELUM heningnya.

    Timestamp Whisper tidak cukup presisi untuk itu. Terukur pada satu batas
    nyata di bahan pengguna:

        146,08 - 146,20   -106 s/d -120 dB   hening sungguhan
        146,23             -23,6 dB          suara benar-benar mulai
        146,42             -16,7 dB          "awal kata" versi Whisper

    Whisper terlambat 190 ms, jadi batas yang tampak rapi di tepi kata justru
    duduk di tengah suku kata — dan yang terdengar adalah penggalan "du".
    Heningnya ada di BELAKANG batas, tempat yang tidak pernah dilihat pencarian
    satu arah.

    Yang menentukan letak batas adalah audionya, bukan angka dari transkrip.
    """
    import numpy as np

    # Audio diambil LEBIH LEBAR dari jendela pencarian.
    #
    # Panjang pita hening harus diukur utuh; kalau jendelanya memotong pita,
    # jeda 380 ms terbaca 80 ms dan ikut tertolak syarat MIN_HENING_LEBAR.
    # Yang dibatasi jendela adalah titik yang boleh DIPILIH, bukan rentang yang
    # boleh diukur — dua hal berbeda yang sempat gua satukan.
    lebih = MIN_HENING_LEBAR * 2
    x = _pcm(src, t - jendela - lebih, (jendela + lebih) * 2)
    if x is None or len(x) < int(0.03 * _SR):
        return None
    frames = _semua_frame(x)
    if len(frames) == 0:
        return None

    # Kumpulkan pita hening yang cukup PANJANG, bukan sekadar frame tersunyi.
    # Frame tersunyi bisa berada di dalam fase tutup konsonan — lihat
    # MIN_HENING_LEBAR untuk kenapa itu menghasilkan penggalan kata.
    sunyi = frames <= AMBANG_HENING_MUTLAK
    min_frame = max(1, int(MIN_HENING_LEBAR / _HOP))
    pita: list[tuple[int, int]] = []
    i = 0
    while i < len(sunyi):
        if sunyi[i]:
            j = i
            while j + 1 < len(sunyi) and sunyi[j + 1]:
                j += 1
            if j - i + 1 >= min_frame:
                pita.append((i, j))
            i = j + 1
        else:
            i += 1
    if not pita:
        return None

    # Titik yang boleh dipilih tetap dibatasi jendela pencarian.
    awal_pcm = t - jendela - lebih
    batas_kiri = (t - jendela - awal_pcm) / _HOP
    batas_kanan = (t + jendela - awal_pcm) / _HOP
    layak = [r for r in pita if r[1] >= batas_kiri and r[0] <= batas_kanan]
    if not layak:
        return None

    # Pita terdekat dari batas sekarang, lalu ambil TENGAHNYA — bukan tepinya.
    # Tengah memberi jarak aman terbesar ke suara di kedua sisi, sehingga sedikit
    # kesalahan pemotongan di renderer tetap tidak menyentuh kata.
    posisi_now = (t - awal_pcm) / _HOP
    a, b = min(layak, key=lambda r: abs((r[0] + r[1]) / 2 - posisi_now))
    titik = min(max((a + b) / 2, batas_kiri), batas_kanan)
    return awal_pcm + titik * _HOP


def rapikan_kata(cuts: list[PlannedCut], kata: list[Word]) -> int:
    """Geser batas yang membelah kata ke tepi kata itu, ke arah LUAR.

    ## Kenapa ini tahap tersendiri

    Dua tahap perapian yang sudah ada tidak bisa menangani kasus ini:

    - `rapikan_batas` menempel ke jeda hening, dan silencedetect hanya
      melaporkan jeda lebih panjang dari 0,45 detik. Batas yang membelah kata
      hampir tidak pernah punya jeda sepanjang itu di dekatnya.
    - `rapikan_energi` memanjangkan sedikit ke titik paling sunyi, tapi ia
      berangkat dari batas yang sudah salah dan hanya bergerak beberapa puluh
      milidetik — tidak cukup untuk keluar dari tengah kata.

    Akibatnya batas yang dipilih model bisa lolos apa adanya. Terukur pada satu
    job nyata: 15 dari 20 batas membelah kata di rencana model, dan tetap 15
    setelah kedua tahap itu berjalan. Yang terdengar adalah kata yang terpenggal
    di tengah — persis keluhan "ada kata yang ke-skip".

    ## Kenapa selalu ke luar

    Batas awal digeser ke AWAL kata, batas akhir ke AKHIR kata. Keduanya
    MENAMBAH audio, sehingga kata yang tersentuh terdengar utuh. Menggeser ke
    dalam juga menghasilkan batas yang bersih, tapi dengan membuang kata yang
    tadinya ada — dan kata yang hilang jauh lebih terasa daripada kata tambahan.
    """
    diubah = 0
    for cut in cuts:
        w = _di_tengah_kata(cut.in_, kata)
        if w is not None and w.start < cut.in_:
            cut.in_ = round(max(0.0, w.start), 3)
            diubah += 1

        w = _di_tengah_kata(cut.out, kata)
        if w is not None and w.end > cut.out:
            cut.out = round(w.end, 3)
            diubah += 1

    if diubah:
        log.info("batas digeser keluar dari tengah kata: %d dari %d", diubah, len(cuts) * 2)
    return diubah


def _pagar_maju(t: float, kata: list[Word]) -> float | None:
    """Sejauh mana `out` boleh maju tanpa masuk ke kata berikutnya."""
    for w in kata:
        if w.start >= t:
            return w.start
    return None


def _pagar_mundur(t: float, kata: list[Word]) -> float | None:
    """Sejauh mana `in_` boleh mundur tanpa masuk ke kata sebelumnya."""
    batas = None
    for w in kata:
        if w.end <= t:
            batas = w.end
        elif w.start >= t:
            break
    return batas


def rapikan_energi(
    cuts: list[PlannedCut],
    src: str,
    kata: list[Word] | None = None,
    *,
    jendela: float = JENDELA_ENERGI,
    min_perbaikan_db: float = MIN_PERBAIKAN_DB,
) -> int:
    """Panjangkan batas potongan ke titik hening terdekat, diukur dari audionya.

    ## Kenapa ini perlu meski batas sudah tepat di tepi kata

    Timestamp Whisper adalah perkiraan, dan ia sistematis meleset ke arah yang
    sama: batas kata ditaruh SEBELUM ekor kata benar-benar habis. Diukur pada
    satu batas nyata — akhir kata "ide" sebelum "gue":

        +0ms   -30.3 dB   <- batas versi Whisper, ekor masih berbunyi keras
        +80ms  -65.0 dB
        +130ms -82.9 dB   <- hening sungguhan
        +169ms -56.9 dB   <- "gue" baru mulai di sini

    Memotong di +0ms memenggal kata di tengah peluruhannya pada -30 dB. Itulah
    yang terdengar sebagai "bocor antar kata": bukan kata lain yang ikut masuk,
    melainkan kata yang ada dipotong sebelum selesai.

    `silencedetect` tidak menolong di sini karena ia hanya melaporkan hening
    yang lebih panjang dari 0,45 detik — jeda antar kata seperti ini tidak
    pernah terdeteksi.

    ## Arahnya selalu KE LUAR

    `in_` mundur, `out` maju. Keduanya MENAMBAH audio, bukan membuang: yang
    ditambahkan adalah ekor kata yang memang seharusnya terdengar. Memotong ke
    dalam justru akan memperparah pemenggalan.
    """
    import numpy as np

    diubah = 0
    for cut in cuts:
        # Pencarian dua arah lebih dulu — ia yang menangani kasus batas yang
        # sudah terlanjur berada di dalam suara. Kalau ia menemukan hening yang
        # jelas, itulah letak batas yang benar dan sisanya tidak perlu.
        sudah: set[str] = set()
        batas_geser = max(0.05, cut.durasi * MAKS_GESER_BAGIAN)
        for sisi in ("out", "in_"):
            lama_t = getattr(cut, sisi)
            baru = _geser_ke_hening(src, lama_t, JENDELA_CARI)
            if baru is None:
                continue
            # Jendela lebar tidak boleh berarti geseran sebesar apa pun. Lihat
            # MAKS_GESER_BAGIAN: yang benar untuk potongan empat detik merusak
            # potongan satu detik.
            if abs(baru - lama_t) > batas_geser:
                continue
            if sisi == "out" and cut.in_ < baru:
                cut.out = round(baru, 3)
                sudah.add(sisi)
                diubah += 1
            elif sisi == "in_" and baru < cut.out:
                cut.in_ = round(max(0.0, baru), 3)
                sudah.add(sisi)
                diubah += 1

        # --- pemanjangan halus, hanya untuk sisi yang BELUM ditempatkan ---
        #
        # Sisi yang sudah ditempatkan pencarian dua arah dilewati. Menggesernya
        # lagi 50 ms ke luar akan membawanya KELUAR dari hening yang baru saja
        # ditemukan — memperbaiki lalu merusak lagi dalam satu fungsi yang sama.
        if "out" not in sudah:
            maju = MARGIN_MIN
            x = _pcm(src, cut.out, jendela)
            if x is not None and len(x) > int(0.03 * _SR):
                i, rms_min, rms_asal = _titik_tersunyi(x)
                if rms_asal > 0 and 20 * np.log10(
                    max(rms_min, 1e-6) / rms_asal
                ) <= -min_perbaikan_db:
                    maju = max(maju, i * _HOP)
            # Dipagari kata berikutnya. Tanpa ini, pemanjangan yang dimaksudkan
            # menangkap ekor kata justru MASUK ke kata sesudahnya.
            pagar = _pagar_maju(cut.out, kata) if kata else None
            cut.out = round(
                cut.out + maju if pagar is None else min(cut.out + maju, pagar), 3
            )
            diubah += 1

        if "in_" not in sudah:
            # Jendelanya [in_ - jendela, in_], jadi frame TERAKHIR-lah yang
            # berada di batas sekarang dan jadi pembanding.
            mundur = MARGIN_MIN
            x = _pcm(src, cut.in_ - jendela, jendela)
            if x is not None and len(x) > int(0.03 * _SR):
                i, rms_min, _ = _titik_tersunyi(x)
                frames = _semua_frame(x)
                rms_asal = float(frames[-1]) if len(frames) else 0.0
                if rms_asal > 0 and 20 * np.log10(
                    max(rms_min, 1e-6) / rms_asal
                ) <= -min_perbaikan_db:
                    mundur = max(mundur, jendela - i * _HOP)
            pagar = _pagar_mundur(cut.in_, kata) if kata else None
            calon = cut.in_ - mundur
            cut.in_ = round(
                max(0.0, calon if pagar is None else max(calon, pagar)), 3
            )
            diubah += 1

    # --- pagar terakhir: potongan tidak boleh saling melangkahi ---
    #
    # Jendela pencarian yang lebar membuat `out` sebuah potongan bisa maju
    # melewati `in_` potongan berikutnya. Kalau keduanya memang bersambung di
    # rekaman -- dan itu terjadi; terukur ada dua batas yang persis sama di satu
    # EDL nyata -- hasilnya adalah audio yang sama terdengar DUA KALI di
    # sambungan.
    #
    # Terukur pada uji pelebaran jendela: satu tumpang tindih tercipta dari 9
    # potongan. Kecil, tapi yang terdengar adalah kata yang diulang, dan itu
    # jauh lebih kentara daripada potongan yang sedikit terpenggal.
    ditarik = 0
    for a, b in zip(cuts, cuts[1:]):
        if a.out > b.in_ and a.in_ < b.in_:
            a.out = round(b.in_, 3)
            ditarik += 1

    if diubah:
        log.info("batas dirapikan ke titik hening audio: %d dari %d", diubah, len(cuts) * 2)
    if ditarik:
        log.info("%d batas ditarik kembali agar potongan tidak tumpang tindih", ditarik)
    return diubah
