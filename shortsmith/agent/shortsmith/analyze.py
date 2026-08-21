"""Tahap analisis: membaca video mentah menjadi satu VideoMap.

Analisis dijalankan LANGSUNG dari file sumber — tidak ada transcode di sini.
Whisper dan silencedetect tidak peduli soal VFR (keduanya bekerja dari audio),
jadi normalisasi CFR ditunda sampai tahap render, di mana ia hanya diterapkan
pada segmen yang benar-benar terpilih.

PySceneDetect hanya dipakai untuk file B-roll. Video suara satu-take tidak
punya potongan keras sama sekali, jadi menjalankannya di sana selalu kosong; yang
menentukan titik potong di rekaman bicara adalah jeda hening + timestamp per kata.
File B-roll sebaliknya sering berupa kompilasi berisi puluhan adegan, dan di situ
deteksi adegan justru yang paling menentukan.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from .config import SETTINGS
from .models import Adegan, MediaInfo, SilenceGap, TranscriptSegment, VideoMap, Word
from .probe import probe, run_capture_stderr

log = logging.getLogger(__name__)

_SILENCE_START = re.compile(r"silence_start:\s*([0-9.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*([0-9.]+)")
_MEAN_VOLUME = re.compile(r"mean_volume:\s*(-?[0-9.]+) dB")

# Di bawah level ini, track audio praktis tidak berisi apa-apa.
AMBANG_HENING_DB = -60.0


class AudioKosong(RuntimeError):
    """Track audio ada tapi tidak berisi suara."""


def mean_volume_db(path: str | Path) -> float:
    """Rata-rata level audio. Mengembalikan -91 dB untuk keheningan digital."""
    stderr = run_capture_stderr(
        [
            SETTINGS.ffmpeg, "-hide_banner", "-nostats",
            "-i", str(path),
            "-af", "volumedetect",
            "-f", "null", "-",
        ]
    )
    m = _MEAN_VOLUME.search(stderr)
    return float(m.group(1)) if m else -99.0


def detect_silence(
    path: str | Path, *, threshold_db: int = -32, min_durasi: float = 0.45
) -> list[SilenceGap]:
    """Cari jeda hening lewat filter silencedetect ffmpeg."""
    stderr = run_capture_stderr(
        [
            SETTINGS.ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i", str(path),
            "-af", f"silencedetect=noise={threshold_db}dB:d={min_durasi}",
            "-f", "null",
            "-",
        ]
    )

    gaps: list[SilenceGap] = []
    pending: float | None = None
    for line in stderr.splitlines():
        if (m := _SILENCE_START.search(line)) is not None:
            pending = float(m.group(1))
        elif (m := _SILENCE_END.search(line)) is not None and pending is not None:
            end = float(m.group(1))
            if end > pending:
                gaps.append(SilenceGap(start=pending, end=end))
            pending = None
    log.info("silencedetect: %d jeda ditemukan", len(gaps))
    return gaps


def transcribe(
    path: str | Path, backend: str | None = None
) -> tuple[list[TranscriptSegment], list[Word]]:
    """Transkrip lewat backend yang dipilih (lihat shortsmith/asr.py)."""
    from .asr import transcribe as _transcribe

    segments, words = _transcribe(path, backend)
    log.info("transkrip: %d segmen, %d kata", len(segments), len(words))
    return segments, words


# Adegan yang lebih pendek dari ini bukan adegan — biasanya kedipan transisi,
# flash, atau salah deteksi. Memakainya sebagai slot akan menghasilkan gambar
# yang berkelebat sebelum sempat terbaca.
ADEGAN_MIN = 0.8

# Berapa banyak adegan yang dibawa ke tahap pelabelan.
#
# Batas ini soal ongkos, dan ongkosnya terukur. Satu rekaman podcast 61 menit
# menghasilkan 916 adegan; tiap adegan dilabeli satu panggilan model, dan
# seluruhnya memakan hampir dua jam plus 916 panggilan berbayar — untuk video
# keluaran 72 detik yang hanya memakai 15 potongan.
#
# 150 dipilih karena `penata` dilarang memakai satu klip dua kali, jadi yang
# benar-benar dibutuhkan adalah SEBANYAK slotnya. Video terpanjang yang wajar
# di sini berkisar 15-20 slot; 150 memberi sekitar sepuluh pilihan untuk tiap
# slot, dan pilihan ke-sebelas tidak pernah mengubah keputusan.
MAKS_ADEGAN = 150


# Bilah hitam yang lebih tipis dari ini diabaikan: beda beberapa piksel biasanya
# artefak encoding, bukan letterbox sungguhan, dan memotongnya tidak memperbaiki
# apa pun sambil menambah risiko salah potong.
MIN_BILAH = 8

# Sebuah piksel dianggap "terang" di atas nilai ini, dan sebuah baris dianggap
# ISI kalau cukup banyak pikselnya terang.
#
# Dulu yang dipakai rata-rata kecerahan baris, dan itu SALAH ukur. Rata-rata
# bisa diangkat segelintir piksel sangat terang di tepi. Terukur pada bahan
# pengguna, satu baris di dalam bilah hitam:
#
#     y= 41  rata-rata 8.20  ->  lolos ambang lama (8.0)
#            tapi hanya 4.9% pikselnya terang; sisanya hitam pekat
#     y=229  rata-rata 29.5  ->  91.1% piksel terang  = isi yang sesungguhnya
#
# Satu baris itu membuat seluruh berkas diukur sebagai "isi mulai y=41",
# sehingga 188 baris hitam ikut terbawa ke hasil sebagai bilah. Ia juga membuat
# pemecahan adegan mengira bilahnya "membuka" padahal tidak.
#
# Pecahan piksel memisahkan keduanya dengan jarak sangat lebar: bilah asli
# 0-5%, isi asli 83-96%. Ambang 20% duduk jauh dari keduanya.
AMBANG_PIKSEL = 16
AMBANG_ISI = 0.20

# Jumlah frame yang disampel per rentang. Ganjil supaya mediannya satu nilai
# nyata, bukan rata-rata dua tetangga.
SAMPEL_BILAH = 5


# Simpangan baku kecerahan di bawah ini berarti adegannya rata tanpa isi —
# hitam total, putih polos, atau kartu warna. Diukur pada 135 adegan bahan
# pengguna, pemisahannya tidak ambigu:
#
#     2 adegan kosong    : detail 0.00 dan 0.14
#     adegan gelap sah   : detail 14.06 (terendah berikutnya)
#     persentil 5 semua  : detail 24.5
#
# Tanpa penjagaan ini, adegan hitam lolos SEMUA pemeriksaan lain — cropdetect
# tidak melihat bilah karena semuanya hitam, tidak ada wajah untuk dikenali,
# dan aturan "tanpa wajah tetap dipakai" meloloskannya. Hasilnya klip hitam
# 3,5 detik di tengah video, dengan hanya subtitle yang terlihat.
MIN_DETAIL = 5.0


def deteksi_bilah(
    path: str | Path, *, mulai: float | None = None, panjang: float | None = None
) -> str:
    """Cari bilah hitam yang TERBAKAR di dalam gambar, kembalikan rect crop ffmpeg.

    Banyak klip stok dan hasil unduhan sudah membawa letterbox sinematik di
    dalam gambarnya. Contoh nyata dari bahan pengguna:

        Mencari Ilham di Bangkok : berkas 2304x1440, isi 2304x980
        Video Project 2          : berkas 1920x1080, isi 1920x816

    Memotong berkas semacam itu ke 9:16 akan MEMBAWA SERTA bilahnya, sehingga
    hasilnya punya bilah hitam di atas dan bawah meski rasionya sudah benar.

    `mulai`/`panjang` membatasi pemeriksaan ke satu bagian saja. Ini bukan
    penghematan, melainkan syarat kebenaran: bilah bisa hanya ada di SEBAGIAN
    berkas. Satu file kompilasi pengguna terdeteksi bersih di tingkat berkas,
    tapi adegan pada detik 35 punya bilah 331px di bawah — sampel tingkat berkas
    kebetulan jatuh di bagian yang tidak berbilah. Diperiksa per adegan, kasus
    itu tertangkap.

    Batas gambar diukur langsung dari piksel: baris atau kolom dianggap ISI kalau
    cukup banyak pikselnya terang — lihat AMBANG_ISI untuk kenapa pecahan piksel,
    bukan rata-rata. Beberapa frame disampel lalu diambil MEDIAN-nya; lihat
    komentar di badan fungsi untuk kenapa median, dan kenapa cropdetect ffmpeg
    tidak dipakai lagi.

    Kembalikan "" kalau tidak ada bilah yang berarti.
    """
    import cv2
    import numpy as np

    media = probe(path)
    if not media.durasi or not media.width or not media.height:
        return ""

    awal = 0.0 if mulai is None else max(0.0, mulai)
    rentang = media.durasi if panjang is None else min(panjang, media.durasi - awal)
    if rentang <= 0:
        return ""

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return ""

    batas: list[tuple[int, int, int, int]] = []
    try:
        for i in range(SAMPEL_BILAH):
            t = awal + rentang * (i + 1) / (SAMPEL_BILAH + 1)
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            abu = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            terang = abu > AMBANG_PIKSEL
            isi_v = np.flatnonzero(terang.mean(axis=1) > AMBANG_ISI)
            isi_h = np.flatnonzero(terang.mean(axis=0) > AMBANG_ISI)
            if isi_v.size == 0 or isi_h.size == 0:
                continue  # frame kosong — bukan bahan untuk mengukur bilah
            batas.append(
                (int(isi_v[0]), int(isi_v[-1]), int(isi_h[0]), int(isi_h[-1]))
            )
    finally:
        cap.release()

    if not batas:
        return ""

    # MEDIAN antar frame, bukan union atau ekstrem.
    #
    # Versi sebelumnya memakai cropdetect ffmpeg dengan reset=0, yang mengambil
    # UNION semua frame dalam jendela sampel. Satu frame terang sesaat — fade-in,
    # kilatan, judul — melebarkan rect secara permanen. Diukur pada bahan
    # pengguna, satu adegan di awal berkas Bangkok dilaporkan 2304x1368 padahal
    # isinya 2304x980; hasilnya bilah 263px kembali muncul di video jadi.
    #
    # Median tahan terhadap frame nyeleneh dari kedua arah sekaligus: fade yang
    # membuat rect terlalu lebar, maupun adegan gelap yang membuatnya terlalu
    # sempit.
    atas = int(np.median([b[0] for b in batas]))
    bawah = int(np.median([b[1] for b in batas]))
    kiri = int(np.median([b[2] for b in batas]))
    kanan = int(np.median([b[3] for b in batas]))

    terbaik_w = kanan - kiri + 1
    terbaik_h = bawah - atas + 1
    x0, y0 = kiri, atas

    if terbaik_w <= 0 or terbaik_h <= 0:
        return ""

    # Lebar dan tinggi genap — encoder yuv420p menolak dimensi ganjil.
    terbaik_w -= terbaik_w % 2
    terbaik_h -= terbaik_h % 2

    buang_v = media.height - terbaik_h
    buang_h = media.width - terbaik_w
    if buang_v < MIN_BILAH and buang_h < MIN_BILAH:
        return ""

    # Jangan pernah membuang lebih dari separuh gambar. Kalau pengukuran sampai
    # menyarankan itu, yang terbaca hampir pasti adegan gelap, bukan bilah.
    if terbaik_h < media.height / 2 or terbaik_w < media.width / 2:
        log.warning(
            "pengukuran bilah menyarankan potongan ekstrem (%dx%d dari %dx%d) — diabaikan",
            terbaik_w, terbaik_h, media.width, media.height,
        )
        return ""

    log.debug(
        "bilah hitam: isi %dx%d dari %dx%d (@%.1fs)",
        terbaik_w, terbaik_h, media.width, media.height, awal,
    )
    return f"{terbaik_w}:{terbaik_h}:{x0}:{y0}"


# Selisih tinggi isi gambar yang masih dianggap sama, dalam piksel. Di atas ini
# bilahnya benar-benar berubah, bukan sekadar derau pengukuran.
TOLERANSI_BILAH = 24

# Berapa kali per detik batas gambar diperiksa saat mencari titik perubahan.
FPS_PINDAI = 4

# Jarak dari kedua ujung adegan yang tidak ikut dipindai, dalam detik.
TEPI_PINDAI = 0.2


def _batas_isi(frame) -> tuple[int, int] | None:
    """Baris pertama dan terakhir yang berisi gambar, atau None kalau kosong."""
    import cv2
    import numpy as np

    terang = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) > AMBANG_PIKSEL
    isi = np.flatnonzero(terang.mean(axis=1) > AMBANG_ISI)
    return (int(isi[0]), int(isi[-1])) if isi.size else None


def pecah_bilah(path: str | Path, mulai: float, panjang: float) -> list[float]:
    """Titik-titik waktu di dalam satu adegan tempat bilah hitamnya BERUBAH.

    Bilah tidak selalu tetap sepanjang satu adegan. Contoh terukur dari bahan
    pengguna, satu adegan 7,28 detik:

        0,3 - 1,7s : isi y=229..1210  (982 tinggi, berbilah)
        2,5 - 7,1s : isi y= 41..1411  (1370 tinggi, hampir penuh)

    Bingkainya melebar di tengah shot tanpa pergantian gambar, jadi deteksi
    adegan tidak memecahnya. Satu rect untuk seluruh adegan pasti salah di salah
    satu bagian: pakai yang besar, bagian berbilah membawa bilahnya; pakai yang
    kecil, bagian penuh kehilangan gambar.

    Kembalikan daftar waktu potong (tanpa titik awal). Kosong berarti bilahnya
    tetap sepanjang adegan — kasus yang paling umum.
    """
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return []

    # Ujung adegan disisihkan. Frame tepat di batas adegan sering masih memuat
    # sisa transisi dari shot sebelumnya, dan batas gambarnya berbeda dari isi
    # adegan yang sebenarnya. Tanpa jarak ini, adegan yang bilahnya tetap pun
    # ikut terpecah — terukur pada satu adegan yang seluruhnya 982 tinggi tapi
    # dilaporkan berubah di detik pertamanya.
    awal = mulai + TEPI_PINDAI
    rentang = panjang - 2 * TEPI_PINDAI
    if rentang <= 0:
        cap.release()
        return []

    sampel: list[tuple[float, tuple[int, int]]] = []
    try:
        n = max(2, int(rentang * FPS_PINDAI))
        for i in range(n):
            t = awal + rentang * i / (n - 1)
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            b = _batas_isi(frame)
            if b is not None:
                sampel.append((t, b))
    finally:
        cap.release()

    # Perubahan harus DIKONFIRMASI sampel berikutnya. Satu frame menyimpang
    # sendirian adalah kedipan atau salah baca, bukan bingkai yang berubah, dan
    # memecah adegan karenanya hanya memotong-motong bahan tanpa alasan.
    potong: list[float] = []
    acuan = sampel[0][1] if sampel else None
    for i in range(1, len(sampel) - 1):
        t, b = sampel[i]
        berikut = sampel[i + 1][1]
        if acuan is None:
            acuan = b
            continue
        beda = max(abs(b[0] - acuan[0]), abs(b[1] - acuan[1]))
        lanjut = max(abs(berikut[0] - b[0]), abs(berikut[1] - b[1]))
        if beda > TOLERANSI_BILAH and lanjut <= TOLERANSI_BILAH:
            potong.append(round(t, 3))
            acuan = b

    return potong


def pecah_adegan(path: str | Path) -> list[Adegan]:
    """Pecah satu file B-roll menjadi adegan-adegan terpisah.

    Satu file kompilasi sering memuat puluhan adegan berbeda. Tanpa pemecahan
    ini, potongan 1,25 detik diambil dari posisi sembarang dan bisa jatuh tepat
    di perpindahan adegan — satu slot berisi dua gambar tak berhubungan, yang
    terlihat seperti kesalahan render.

    Kalau deteksi gagal atau tidak menemukan apa pun, seluruh file dianggap satu
    adegan. Itu perilaku lama, jadi kegagalan di sini tidak pernah lebih buruk
    dari sebelumnya.
    """
    try:
        from scenedetect import ContentDetector, detect
    except ImportError:
        log.warning("PySceneDetect tidak ada - file dianggap satu adegan utuh")
        return []

    try:
        scenes = detect(str(path), ContentDetector(threshold=27.0))
    except Exception as exc:  # noqa: BLE001 - deteksi scene punya banyak mode gagal
        log.warning("deteksi adegan gagal (%s) - file dianggap satu adegan utuh", exc)
        return []

    from .wajah import periksa_adegan

    hasil: list[Adegan] = []
    kosong = 0
    dipecah = 0
    for a, b in scenes:
        mulai, selesai = a.get_seconds(), b.get_seconds()
        if selesai - mulai < ADEGAN_MIN:
            continue

        # Satu adegan bisa berisi lebih dari satu bingkai. Dipecah dulu di titik
        # bilahnya berubah, karena satu rect crop tidak bisa benar untuk dua
        # bingkai sekaligus — lihat pecah_bilah.
        titik = pecah_bilah(path, mulai, selesai - mulai)
        batas = [mulai, *titik, selesai]
        if titik:
            dipecah += 1

        for awal, akhir in zip(batas, batas[1:]):
            if akhir - awal < ADEGAN_MIN:
                continue
            # Diperiksa per bagian, bukan sekali untuk seluruh berkas — lihat
            # deteksi_bilah untuk kasus yang memaksanya.
            crop = deteksi_bilah(path, mulai=awal, panjang=akhir - awal)
            # Wajah dicari SETELAH bilah ditentukan, supaya koordinatnya berada
            # di ruang yang sama dengan yang dilihat filter crop di renderer.
            temuan = periksa_adegan(path, mulai=awal, panjang=akhir - awal, crop=crop)
            if temuan is not None and temuan.detail < MIN_DETAIL:
                kosong += 1
                continue
            hasil.append(
                Adegan(
                    src=str(Path(path).resolve()),
                    start=awal,
                    end=akhir,
                    crop=crop,
                    fokus_x=temuan.fokus_x if temuan else None,
                    fokus_y=temuan.fokus_y if temuan else None,
                    sidik=temuan.sidik if temuan else None,
                    arah=temuan.arah if temuan else 0.0,
                )
            )

    if dipecah:
        log.info("%d adegan dipecah lagi karena bilahnya berubah di tengah", dipecah)

    hasil = _ringkas(hasil)

    berbilah = sum(1 for a in hasil if a.crop)
    berwajah = sum(1 for a in hasil if a.fokus_x is not None)
    log.info(
        "adegan terdeteksi: %d dipakai dari %d (minimal %.1fs), "
        "%d berbilah hitam, %d berwajah, %d kosong dibuang",
        len(hasil), len(scenes), ADEGAN_MIN, berbilah, berwajah, kosong,
    )
    return hasil


def _ringkas(adegan: list[Adegan]) -> list[Adegan]:
    """Kurangi jumlah adegan ke MAKS_ADEGAN, merata sepanjang durasi.

    ## Kenapa disebar merata, bukan diambil yang pertama

    Mengambil 150 pertama dari sebuah rekaman satu jam berarti seluruh pustaka
    B-roll datang dari sepuluh menit pembuka. Video keluarannya lalu terlihat
    seperti dirangkai dari satu bagian saja, dan lima puluh menit sisanya tidak
    pernah punya kesempatan muncul.

    ## Kenapa bukan yang terpanjang

    Adegan terpanjang adalah adegan yang paling lama tidak berubah — kamera diam
    pada pembicara yang sedang bicara. Memilih menurut panjang akan mengisi
    pustaka dengan gambar yang paling tidak bergerak, yaitu justru yang paling
    tidak berguna sebagai B-roll.

    Jarak tetap di sepanjang daftar mempertahankan sebaran waktunya, dan daftar
    ini memang sudah urut waktu karena dibangun dari hasil deteksi adegan.
    """
    if len(adegan) <= MAKS_ADEGAN:
        return adegan

    langkah = len(adegan) / MAKS_ADEGAN
    dipilih = [adegan[int(i * langkah)] for i in range(MAKS_ADEGAN)]
    log.info(
        "adegan diringkas: %d -> %d, disebar merata sepanjang durasi "
        "(pelabelan %d panggilan lebih sedikit)",
        len(adegan), len(dipilih), (len(adegan) - len(dipilih) + 7) // 8,
    )
    return dipilih


def build_map(
    path: str | Path,
    *,
    skip_transcript: bool = False,
    broll: bool = False,
    asr_backend: str | None = None,
) -> VideoMap:
    """Rakit VideoMap untuk satu video mentah.

    `broll=True` menandai video yang hanya diambil gambarnya. Bedanya bukan
    sekadar melewati transkrip:

    - **Hening bukan kesalahan.** Klip B-roll memang lazim tanpa suara, atau
      bersuara tapi tidak dipakai. Menerapkan AudioKosong di sini akan membuat
      seluruh job gagal hanya karena satu klip stok tidak bersuara.
    - **Deteksi hening dilewati.** Jeda hening dipakai untuk mencari titik
      potong ucapan. Di klip yang suaranya dibuang, hasilnya tidak berarti apa-apa.

    Yang tersisa untuk B-roll hanyalah `probe`: durasi, dimensi, fps. Itu memang
    seluruh yang dibutuhkan penata untuk menempatkannya di timeline.
    """
    media: MediaInfo = probe(path)
    log.info(
        "sumber: %.1fs, %dx%d @ %.2ffps, audio=%s, vfr=%s",
        media.durasi, media.width, media.height, media.fps, media.punya_audio, media.vfr,
    )
    if media.vfr:
        log.warning(
            "sumber terdeteksi variable frame rate — segmen akan dinormalkan ke CFR %dfps "
            "saat render",
            SETTINGS.fps,
        )

    segments: list[TranscriptSegment] = []
    words: list[Word] = []
    silences: list[SilenceGap] = []

    if broll:
        log.info("peran B-roll — hanya gambar yang dipakai, audio dan transkrip dilewati")
        media.crop = deteksi_bilah(path)
        adegan = pecah_adegan(path)
        # Label disimpan di peta video, jadi satu set bahan hanya dilabeli sekali
        # seumur hidupnya — render berikutnya tidak memanggil model lagi.
        from .pelabel import labeli
        labeli(adegan)
        return VideoMap(media=media, adegan=adegan)
    elif media.punya_audio:
        # Adanya track audio tidak berarti ada suaranya. Rekaman layar sering
        # punya track yang hening total; kalau dibiarkan, Whisper akan
        # BERHALUSINASI di atas keheningan (biasanya frasa seperti "Terima kasih")
        # dan pipeline membangun video dari transkrip yang tidak pernah diucapkan.
        # Jauh lebih baik berhenti di sini dengan pesan yang jelas.
        level = mean_volume_db(path)
        log.info("level audio rata-rata: %.1f dB", level)
        if level < AMBANG_HENING_DB:
            raise AudioKosong(
                f"Track audio ada tapi hening ({level:.0f} dB, ambang "
                f"{AMBANG_HENING_DB:.0f} dB). Tidak ada ucapan untuk dijadikan dasar "
                f"pemilihan potongan. Periksa apakah mikrofon terekam saat pengambilan."
            )

        silences = detect_silence(path)
        if not skip_transcript:
            segments, words = transcribe(path, asr_backend)
    else:
        log.warning("tidak ada track audio — melewati transkrip dan deteksi hening")

    # Rekaman suara pun bisa berupa hasil unduhan yang sudah dibingkai hitam.
    media.crop = deteksi_bilah(path)
    return VideoMap(media=media, segments=segments, words=words, silences=silences)
