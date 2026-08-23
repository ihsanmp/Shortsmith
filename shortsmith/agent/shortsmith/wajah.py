"""Deteksi wajah untuk menentukan ke mana jendela crop 9:16 diarahkan.

## Masalah yang dipecahkan

Crop 9:16 dari shot lebar sebelumnya diambil dari TENGAH frame. Itu asumsi yang
diam-diam salah: sinematografer membingkai untuk 16:9, dan subjeknya sering
sengaja ditaruh di sepertiga kiri atau kanan, bukan di tengah.

Contoh terukur dari bahan pengguna — satu shot 2304x980, wajah menghadap kamera
di x=968 (42% dari kiri):

    jendela 9:16 selebar 551px
    crop tengah  -> x 876..1428   (setir dan tangan; kepala terpotong tepi kiri)
    crop ke wajah -> x 693..1244  (wajah utuh di tengah bingkai)

Bahannya benar, framingnya yang salah. Yang dibutuhkan cuma satu angka per
adegan: di mana wajahnya.

## Kenapa YuNet, bukan model yang lebih pintar

Ini dijalankan ratusan kali per project, jadi harganya harus nol. YuNet berjalan
lokal dalam hitungan milidetik dan tidak memakai token sama sekali. Ia memang
lemah pada wajah yang menyamping penuh atau tertutup — dan itu justru cocok:
wajah yang tidak terdeteksi biasanya memang bukan wajah yang layak jadi pusat
bingkai. Saat ragu, kode ini mengembalikan None dan crop tengah tetap dipakai.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .kaidah import arah_pandang

log = logging.getLogger(__name__)

_MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL = _MODEL_DIR / "face_detection_yunet_2023mar.onnx"
MODEL_KENAL = _MODEL_DIR / "face_recognition_sface_2021dec.onnx"

# Ambang cosine bawaan SFace untuk "orang yang sama". Diukur pada bahan
# pengguna, jaraknya sangat lebar dan angka ini duduk nyaman di tengahnya:
#
#     wajah tokoh utama   : 0.59 .. 0.69
#     wajah orang lain    : -0.05 .. 0.06
#
# Tidak ada yang mendekati 0.363 dari kedua sisi, jadi keputusannya tidak
# rapuh terhadap pergeseran kecil.
AMBANG_SAMA = 0.363

# Ambang keyakinan YuNet. Bawaannya 0.9.
#
# Diturunkan ke 0.5 setelah satu kegagalan yang terukur: pada shot dua orang
# bermain catur, subjek utama terdeteksi dengan skor 0.70 — tepat di bawah
# ambang lama 0.75. Wajahnya ditolak, tidak ada titik fokus, dan crop jatuh ke
# tengah frame yang isinya papan catur. Subjeknya hilang dari bingkai.
#
# Wajah menyerong dan berpencahayaan rendah memang wajar mendapat skor sedang.
# Salah mengarahkan bingkai ke wajah yang meragukan jauh lebih ringan akibatnya
# daripada kehilangan subjek sama sekali, jadi ambangnya condong ke menerima.
AMBANG_SKOR = 0.5

# Wajah yang lebih kecil dari ini kemungkinan besar orang lewat di latar
# belakang. Mengarahkan bingkai ke sana akan membuang subjek utamanya.
MIN_LUAS_WAJAH = 0.004  # 0,4% dari luas frame

# Deteksi dijalankan pada frame yang diperkecil. Wajah yang layak jadi subjek
# selalu jauh lebih besar dari beberapa piksel, jadi resolusi penuh tidak
# menambah apa pun selain waktu.
LEBAR_DETEKSI = 640

_detektor: cv2.FaceDetectorYN | None = None
_ukuran_detektor: tuple[int, int] = (0, 0)


def tersedia() -> bool:
    return MODEL.exists()


def _ambil_detektor(w: int, h: int) -> cv2.FaceDetectorYN | None:
    """Detektor dipakai ulang antar pemanggilan — membuatnya tidak gratis."""
    global _detektor, _ukuran_detektor

    if not tersedia():
        return None
    if _detektor is None:
        _detektor = cv2.FaceDetectorYN.create(
            str(MODEL), "", (w, h), score_threshold=AMBANG_SKOR
        )
        _ukuran_detektor = (w, h)
    elif _ukuran_detektor != (w, h):
        _detektor.setInputSize((w, h))
        _ukuran_detektor = (w, h)
    return _detektor


def _urai_crop(rect: str) -> tuple[int, int, int, int] | None:
    """"w:h:x:y" -> (w, h, x, y)."""
    if not rect:
        return None
    try:
        w, h, x, y = (int(v) for v in rect.split(":"))
    except ValueError:
        return None
    return w, h, x, y


_pengenal: cv2.FaceRecognizerSF | None = None


def bisa_kenal() -> bool:
    return MODEL_KENAL.exists()


def _ambil_pengenal() -> cv2.FaceRecognizerSF | None:
    global _pengenal
    if not bisa_kenal():
        return None
    if _pengenal is None:
        _pengenal = cv2.FaceRecognizerSF.create(str(MODEL_KENAL), "")
    return _pengenal


def _wajah_terbesar(
    frame: np.ndarray,
) -> tuple[float, float, list[float] | None, float] | None:
    """Wajah terbesar: titik tengahnya sebagai pecahan (fx, fy), plus sidik identitas.

    Sidiknya dihitung dari frame yang SAMA, bukan lewat pemanggilan terpisah:
    membuka dan menggeser berkas video jauh lebih mahal daripada menjalankan
    kedua model, jadi memisahkannya akan menggandakan biaya yang mahal demi
    menghemat yang murah.
    """
    h, w = frame.shape[:2]
    skala = LEBAR_DETEKSI / w if w > LEBAR_DETEKSI else 1.0
    kecil = cv2.resize(frame, None, fx=skala, fy=skala) if skala != 1.0 else frame

    det = _ambil_detektor(kecil.shape[1], kecil.shape[0])
    if det is None:
        return None

    _, wajah = det.detect(kecil)
    if wajah is None or len(wajah) == 0:
        return None

    # Kolom 0-3 adalah kotak wajah (x, y, w, h) dalam piksel frame kecil.
    kotak = wajah[:, :4]
    luas = kotak[:, 2] * kotak[:, 3]
    i = int(np.argmax(luas))
    x, y, bw, bh = kotak[i]

    luas_relatif = float(luas[i]) / (kecil.shape[0] * kecil.shape[1])
    if luas_relatif < MIN_LUAS_WAJAH:
        return None

    # Landmark YuNet: kolom 4-13 berisi mata kanan, mata kiri, hidung, lalu dua
    # sudut mulut. Tiga yang pertama cukup untuk tahu ke mana wajahnya menghadap.
    baris = wajah[i]
    arah = arah_pandang(
        float(baris[4]), float(baris[6]), float(baris[8])
    )

    sidik: list[float] | None = None
    rec = _ambil_pengenal()
    if rec is not None:
        try:
            # alignCrop butuh baris utuh (kotak + 5 titik landmark), bukan kotaknya
            # saja — landmark itulah yang meluruskan wajah miring sebelum dikenali.
            vec = rec.feature(rec.alignCrop(kecil, wajah[i : i + 1])).flatten()
            sidik = [round(float(v), 4) for v in vec]
        except cv2.error as exc:  # noqa: PERF203 - wajah di tepi bisa gagal di-align
            log.debug("gagal menghitung sidik wajah: %s", exc)

    return (
        float((x + bw / 2) / kecil.shape[1]),
        float((y + bh / 2) / kecil.shape[0]),
        sidik,
        arah,
    )


def mirip(a: list[float] | None, b: list[float] | None) -> float:
    """Kemiripan cosine dua sidik wajah. -1 kalau salah satunya tidak ada."""
    if not a or not b:
        return -1.0
    va, vb = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
    if na == 0.0 or nb == 0.0:
        return -1.0
    return float(np.dot(va, vb) / (na * nb))


def orang_sama(sidik: list[float] | None, rujukan: list[list[float]]) -> bool:
    """Apakah sidik ini milik tokoh yang sama dengan salah satu rujukan.

    Dibandingkan dengan BEBERAPA rujukan lalu diambil yang tertinggi, bukan
    dengan satu rata-rata: wajah orang yang sama bisa terlihat sangat berbeda
    antara menunduk, tertawa, dan menyamping, dan merata-ratakannya menghasilkan
    vektor yang tidak menyerupai satu pun pose aslinya.
    """
    if not rujukan:
        return True
    return max(mirip(sidik, r) for r in rujukan) >= AMBANG_SAMA


@dataclass
class Temuan:
    """Apa yang terlihat di satu adegan."""

    fokus_x: float | None
    fokus_y: float | None
    sidik: list[float] | None
    # Ke mana wajahnya menghadap, -1 (kiri) sampai +1 (kanan). Dipakai untuk
    # menyisakan ruang pandang — lihat kaidah.py.
    arah: float
    # Simpangan baku kecerahan, diambil median antar sampel. Mendekati nol
    # berarti frame rata tanpa isi — hitam, putih, atau kartu warna polos.
    detail: float


def periksa_adegan(
    path: str | Path,
    *,
    mulai: float = 0.0,
    panjang: float | None = None,
    crop: str = "",
    sampel: int = 3,
) -> Temuan | None:
    """Periksa satu adegan: ada wajah siapa di mana, dan apakah gambarnya berisi.

    Ketiganya dihitung dari frame yang SAMA. Memisahkannya jadi tiga fungsi akan
    membuka dan menggeser berkas video tiga kali, dan pembacaan berkas itulah
    biaya yang mahal di sini — bukan modelnya.

    Titik fokus relatif terhadap ISI gambar setelah bilah hitam dibuang, bukan
    terhadap berkas mentah — itu ruang koordinat yang sama dengan yang dilihat
    filter crop rasio di renderer, jadi angkanya bisa dipakai langsung.

    `fokus_x`/`sidik` boleh None sementara `detail` tetap terisi: adegan
    pemandangan dan detail objek memang tidak punya wajah, dan itu wajar. None
    untuk seluruh Temuan hanya berarti berkasnya tidak terbaca.
    """
    if not tersedia():
        return None

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        log.debug("tidak bisa membuka %s untuk pemeriksaan adegan", path)
        return None

    rect = _urai_crop(crop)
    temuan: list[tuple[float, float, list[float] | None, float]] = []
    detail: list[float] = []

    try:
        # Ujung adegan dihindari: di sana sering ada sisa transisi dari adegan
        # sebelumnya, dan wajah yang terdeteksi di situ milik shot yang salah.
        for i in range(sampel):
            bagian = (i + 1) / (sampel + 1)
            t = mulai + (panjang or 0.0) * bagian
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            if rect is not None:
                w, h, x, y = rect
                frame = frame[y : y + h, x : x + w]
                if frame.size == 0:
                    continue
            detail.append(float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).std()))
            hasil = _wajah_terbesar(frame)
            if hasil is not None:
                temuan.append(hasil)
    finally:
        cap.release()

    if not detail:
        return None

    # Median antar sampel, bukan minimum: adegan yang memuat satu fade singkat
    # punya satu frame kosong tapi tetap adegan yang sah, dan minimum akan
    # membuangnya. Yang harus dibuang adalah adegan yang kosong SEPANJANG durasinya.
    detail_med = float(np.median(detail))

    if not temuan:
        return Temuan(None, None, None, 0.0, detail_med)

    # Median, bukan rata-rata: satu deteksi meleset di latar belakang tidak
    # boleh menarik bingkai menjauh dari subjek yang benar di dua sampel lain.
    fx = float(np.median([t[0] for t in temuan]))
    fy = float(np.median([t[1] for t in temuan]))

    # Sidik diambil dari SATU sampel, bukan digabung. Rata-rata beberapa pose
    # menghasilkan vektor yang tidak menyerupai satu pun pose aslinya; satu
    # sampel yang utuh membandingkan jauh lebih bersih.
    sidik = next((t[2] for t in temuan if t[2] is not None), None)
    arah = float(np.median([t[3] for t in temuan]))
    return Temuan(fx, fy, sidik, arah, detail_med)


def fokus_adegan(
    path: str | Path,
    *,
    mulai: float = 0.0,
    panjang: float | None = None,
    crop: str = "",
    sampel: int = 3,
) -> tuple[float, float] | None:
    """Titik wajah saja, untuk pemanggil yang tidak butuh identitasnya."""
    hasil = periksa_adegan(
        path, mulai=mulai, panjang=panjang, crop=crop, sampel=sampel
    )
    if hasil is None or hasil.fokus_x is None or hasil.fokus_y is None:
        return None
    return hasil.fokus_x, hasil.fokus_y


# Berapa kali per detik posisi wajah diperiksa saat melacak. Wajah manusia tidak
# berpindah jauh dalam 1/5 detik, dan menaikkan angka ini hanya menambah waktu
# tanpa mengubah jalur yang dihasilkan.
FPS_LACAK = 5

# Panjang jendela rata-rata bergerak untuk menghaluskan jalur, dalam sampel.
# Deteksi wajah bergetar satu-dua piksel antar frame; tanpa penghalusan,
# getaran itu jadi guncangan kamera yang terlihat jelas di hasil.
HALUS = 5

# Panjang jendela median untuk membuang pencilan, dalam sampel.
#
# Lima memberi toleransi dua sampel buruk berturut-turut. Lebih panjang mulai
# memotong gerakan cepat yang memang nyata; lebih pendek tidak cukup untuk
# kesalahan deteksi yang kebetulan terjadi dua frame beruntun.
JENDELA_MEDIAN = 5

# Kalau seluruh pergerakan wajah lebih kecil dari ini (pecahan lebar gambar),
# bingkainya DIAM.
#
# Ini kaidah editing, bukan optimasi: kamera yang bergerak sedikit terlihat
# seperti kesalahan, sedangkan kamera yang diam terlihat disengaja. Editor
# menggerakkan bingkai kalau ada alasan, dan tidak kalau tidak ada.
AMBANG_GERAK = 0.06


def lacak(
    path: str | Path,
    *,
    mulai: float,
    panjang: float,
    crop: str = "",
) -> list[tuple[float, float, float]] | None:
    """Jalur wajah selama satu slot: daftar (detik_relatif, fx, fy).

    Dibaca BERURUTAN dari satu titik seek, bukan seek berulang per sampel.
    Menggeser berkas video jauh lebih mahal daripada mendekode frame berikutnya,
    dan untuk belasan sampel dalam dua detik bedanya puluhan kali lipat.

    Kembalikan None kalau wajahnya tidak pernah terlihat — pemanggil memakai
    titik fokus statis seperti biasa.

    Kembalikan satu titik saja kalau wajahnya nyaris tidak bergerak. Itu bukan
    kegagalan melacak; itu keputusan untuk tidak menggerakkan bingkai tanpa
    alasan (lihat AMBANG_GERAK).
    """
    if not tersedia() or panjang <= 0:
        return None

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None

    rect = _urai_crop(crop)
    fps_src = cap.get(cv2.CAP_PROP_FPS) or 30.0
    langkah = max(1, int(round(fps_src / FPS_LACAK)))
    total_frame = max(1, int(round(panjang * fps_src)))

    titik: list[tuple[float, float, float]] = []
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, mulai * 1000.0)
        for n in range(total_frame):
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            if n % langkah:
                continue
            if rect is not None:
                w, h, x, y = rect
                frame = frame[y : y + h, x : x + w]
                if frame.size == 0:
                    continue
            hasil = _wajah_terbesar(frame)
            if hasil is not None:
                titik.append((n / fps_src, hasil[0], hasil[1]))
    finally:
        cap.release()

    if not titik:
        return None

    # Lubang di tengah jalur (wajah tertutup sesaat, atau menoleh penuh) tidak
    # diisi tebakan — titik yang ada saja yang dipakai, dan renderer melakukan
    # interpolasi lurus di antaranya. Menebak posisi wajah yang tidak terlihat
    # berisiko menggerakkan bingkai ke tempat yang salah.
    xs = _tapis([p[1] for p in titik])
    ys = _tapis([p[2] for p in titik])
    jalur = [(t, x, y) for (t, _, _), x, y in zip(titik, xs, ys)]

    if max(xs) - min(xs) < AMBANG_GERAK and max(ys) - min(ys) < AMBANG_GERAK:
        tengah = len(jalur) // 2
        return [(0.0, jalur[tengah][1], jalur[tengah][2])]

    return jalur


def _tapis(nilai: list[float]) -> list[float]:
    """Buang pencilan lebih dulu dengan median, baru haluskan dengan rata-rata.

    ## Kenapa rata-rata saja tidak cukup

    Detektor wajah sesekali mengunci wajah LAIN selama satu frame, atau
    menghasilkan kecocokan palsu. Itu bukan getaran kecil — ia lompatan besar.
    Terukur pada satu slot nyata, posisi vertikal wajah::

        t=3,4   0,294
        t=3,6   0,592     <- satu sampel, melompat 0,3 dalam 0,2 detik
        t=3,8   0,292

    Rata-rata bergerak tidak membuang sampel itu; ia MENGOLESKANNYA ke seluruh
    jendela. Satu frame buruk menarik jalur dari 0,30 ke 0,39 dan bertahan satu
    detik penuh — di hasil jadi, itu terlihat sebagai kamera yang tiba-tiba
    tersentak lalu kembali.

    Median kebal terhadap satu pencilan: ia memilih nilai tengah, dan nilai
    tengah dari empat sampel baik plus satu sampel buruk tetap sampel baik.

    Terukur pada data yang sama, simpangan maksimum dari garis dasar
    sebenarnya::

        rata-rata saja      0,093   (9% lebar bingkai, terlihat)
        median lalu rata2   0,011   (1%, tidak terlihat)

    Rata-ratanya tetap dipakai SETELAH median, karena median saja meninggalkan
    tangga-tangga kecil di antara nilai yang berdekatan.
    """
    n = len(nilai)
    if n < 3:
        return list(nilai)
    r = JENDELA_MEDIAN // 2
    tengah = [
        float(np.median(nilai[max(0, i - r) : min(n, i + r + 1)])) for i in range(n)
    ]
    return _haluskan(tengah)


def _haluskan(nilai: list[float]) -> list[float]:
    """Rata-rata bergerak, dengan tepi yang tidak menyusut."""
    if len(nilai) < 3:
        return list(nilai)
    n = min(HALUS, len(nilai) if len(nilai) % 2 else len(nilai) - 1)
    sisi = n // 2
    keluar: list[float] = []
    for i in range(len(nilai)):
        a = max(0, i - sisi)
        b = min(len(nilai), i + sisi + 1)
        keluar.append(sum(nilai[a:b]) / (b - a))
    return keluar


def rujukan_tokoh(
    path: str | Path, durasi: float, *, crop: str = "", jumlah: int = 6
) -> list[list[float]]:
    """Sidik tokoh utama, diambil dari beberapa titik di rekaman pembicara.

    Rekaman bicara adalah rujukan yang paling bisa dipercaya untuk "siapa video
    ini": orangnya ada di sana sepanjang durasi, menghadap kamera, dan memang
    dialah yang suaranya dipakai. Diukur pada bahan pengguna, enam sampel dari
    rekaman 27 menit saling mirip di 0.854 — cukup stabil untuk dijadikan patokan.
    """
    if not bisa_kenal() or durasi <= 0:
        return []

    hasil: list[list[float]] = []
    for i in range(jumlah):
        t = durasi * (i + 1) / (jumlah + 1)
        temuan = periksa_adegan(path, mulai=t, panjang=0.0, crop=crop, sampel=1)
        if temuan and temuan.sidik is not None:
            hasil.append(temuan.sidik)
    return hasil
