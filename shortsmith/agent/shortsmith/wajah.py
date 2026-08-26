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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .kaidah import AMBANG_ARAH, arah_pandang

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


def _kandidat_wajah(
    frame: np.ndarray, bahan: list | None = None
) -> list[tuple[float, float, float, float]]:
    """SEMUA wajah di satu frame: (fx, fy, luas_relatif, arah), terbesar lebih dulu.

    Dipakai `lacak`, yang tidak boleh puas dengan wajah terbesar saja. Di
    rekaman dua orang, kedua wajah berukuran hampir sama dan yang "terbesar"
    berganti karena selisih beberapa piksel — lihat `_runut` untuk ukurannya.
    """
    h, w = frame.shape[:2]
    skala = LEBAR_DETEKSI / w if w > LEBAR_DETEKSI else 1.0
    kecil = cv2.resize(frame, None, fx=skala, fy=skala) if skala != 1.0 else frame

    det = _ambil_detektor(kecil.shape[1], kecil.shape[0])
    if det is None:
        return []
    _, wajah = det.detect(kecil)
    if wajah is None or len(wajah) == 0:
        if bahan is not None:
            bahan.append((kecil, []))
        return []

    ph, pw = kecil.shape[0], kecil.shape[1]
    hasil: list[tuple[float, float, float, float]] = []
    simpan: list = []
    for baris in wajah:
        x, y, bw, bh = baris[:4]
        rel = float(bw * bh) / (ph * pw)
        if rel < MIN_LUAS_WAJAH:
            continue
        # Arah hadap ikut diambil PER WAJAH, bukan sekali untuk seluruh
        # potongan. Di rekaman dua orang yang berhadapan, keduanya menghadap ke
        # sisi yang berlawanan -- satu angka untuk keduanya pasti salah di salah
        # satu sisi. Kolom 4-9 berisi mata kanan, mata kiri, lalu hidung.
        arah = arah_pandang(float(baris[4]), float(baris[6]), float(baris[8]))
        hasil.append(
            (float((x + bw / 2) / pw), float((y + bh / 2) / ph), rel, arah)
        )
        simpan.append(baris)
    urut = sorted(range(len(hasil)), key=lambda i: hasil[i][2], reverse=True)
    if bahan is not None:
        # Frame kecil dan baris deteksinya disimpan supaya sidik wajah bisa
        # dihitung NANTI, hanya untuk frame yang benar-benar membingungkan
        # penjejak. Mendekode ulang video untuk itu jauh lebih mahal.
        bahan.append((kecil, [simpan[i] for i in urut]))
    return [hasil[i] for i in urut]


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

# Panjang jendela rata-rata bergerak untuk menghaluskan jalur, dalam sampel,
# dan berapa kali jendela itu dilewatkan.
#
# Deteksi wajah bergetar satu-dua piksel antar frame; tanpa penghalusan, getaran
# itu jadi guncangan kamera yang terlihat jelas di hasil.
#
# ## Kenapa DUA lintasan, bukan satu jendela lebar
#
# Satu rata-rata bergerak menghasilkan jalur yang patah di tiap sampel: renderer
# menarik garis lurus antar titik, jadi kecepatan bingkai berubah mendadak lima
# kali per detik. Itu yang terbaca sebagai gerak kamera yang tersendat, bukan
# amplitudo getarannya.
#
# Melewatkan jendela dua kali menghasilkan kernel segitiga, yang responsnya
# tidak punya sudut — dan itu jauh lebih menentukan daripada sekadar melebarkan
# jendelanya sekali.
#
# Diukur pada 9 potongan job nyata, percepatan bingkai di dalam bagian yang
# menerus (perpindahan tegas dikeluarkan, karena percepatannya memang tak
# terhingga dan menenggelamkan seluruh perbandingan)::
#
#     filter                percepatan rms   simpangan maks   gerak tersisa
#     med5 + rata5 (lama)         0,00087        16 px            48%
#     med5 + rata7 x2             0,00031        20 px            36%
#     med5 + rata9 x2             0,00024        22 px            30%
#     med5 + rata11 x2            0,00016        23 px            25%
#
# Dipilih rata9 dua kali: percepatan turun 72%, sementara simpangan bingkai
# terhadap wajah cuma naik dari 16 ke 22 piksel pada 1080 — 2% lebar bingkai,
# tidak terlihat. Melebar lagi ke 11 memberi sedikit tambahan tapi gerak yang
# tersisa mulai tergerus, dan kehalusan yang didapat dengan membekukan bingkai
# bukan kehalusan.
HALUS = 9
LINTASAN_HALUS = 2

# Panjang jendela median untuk membuang pencilan, dalam sampel.
#
# Lima memberi toleransi dua sampel buruk berturut-turut. Lebih panjang mulai
# memotong gerakan cepat yang memang nyata; lebih pendek tidak cukup untuk
# kesalahan deteksi yang kebetulan terjadi dua frame beruntun.
JENDELA_MEDIAN = 5

# Sejauh ini (pecahan lebar gambar) wajah yang dilacak masih dianggap bergerak.
# Lebih jauh dari itu, ia LONCAT — dan bingkainya harus ikut loncat, bukan
# menyapu ke sana.
#
# Dua sebab yang menghasilkan loncatan, dan keduanya minta perlakuan yang sama:
# orangnya berganti (detektor mengunci wajah lain), atau kameranya berpindah
# shot (orangnya sama, tempatnya di frame berbeda). Karena itu namanya bukan
# "orang lain" — yang diukur perpindahan tempatnya, bukan identitasnya.
#
# Diukur pada seluruh 8 potongan job nyata, 445 selisih antar sampel::
#
#     0,00-0,02   401   <- wajah bergerak biasa
#     0,02-0,05     3
#     0,05-0,15     0   <- KOSONG
#     0,15-0,50    14   <- loncatan
#     0,50-0,70    27   <- loncatan
#
# Celahnya kosong sama sekali, jadi ambangnya ditaruh di TENGAH celah, bukan di
# tepinya. Di tepi (0,15) satu loncatan yang kebetulan sedikit lebih kecil akan
# terbaca sebagai gerakan dan kembali disapu.
AMBANG_LONCAT = 0.10

# Berapa sampel berturut-turut posisi baru harus bertahan sebelum bingkainya
# benar-benar pindah. Pada 5 sampel/detik, ini satu detik penuh.
#
# Tanpa penahanan ini, "pindah seketika" akan dipicu oleh kedipan detektor.
# Diukur pada satu potongan: detektor berganti wajah 22 kali dalam 20 detik,
# tapi 13 di antaranya cuma bertahan 1-2 sampel — itu bukan pergantian apa pun,
# itu dua wajah berukuran hampir sama yang saling menang-kalah.
#
# Menunggu TIDAK menunda perpindahannya. Sampel selama masa tunggu ditulis
# ulang ke posisi baru setelah disahkan, jadi potongnya tetap jatuh di tempat
# loncatannya benar-benar terjadi — lihat `_runut`.
TAHAN_PINDAH = 5

# Berapa sampel yang dituntut untuk perpindahan yang datang TEPAT SETELAH
# perpindahan lain. Pada 5 sampel/detik, dua detik penuh.
#
# Sesaat setelah bingkai berpindah, penjejak sedang paling tidak yakin: shot-nya
# baru berganti, wajah yang tadi dipegang baru saja hilang, dan wajah baru belum
# terbukti bertahan. Membolehkan perpindahan kedua secepat yang pertama
# menghasilkan bingkai yang MEMANTUL.
#
# Terjadi sungguhan dan terlihat. Pada satu potongan 27 detik::
#
#     t= 5,61  pergantian shot   (beda gambar 60,7)
#     t=13,41  pergantian shot   (beda gambar 60,8)
#     t=14,61  gambar TIDAK berubah (beda 1,3) -- bingkai memantul balik
#     t=26,83  pergantian shot   (beda gambar 69,5)
#
# Yang di 14,61 datang 1,2 detik setelah yang di 13,41, di dalam shot yang sama.
# Dengan dua detik, ia gugur; ketiga pergantian shot yang sungguhan tetap lolos.
#
# Menuntut lebih lama TIDAK membuat bingkai tertinggal: sampel masa tunggu
# ditulis ulang secara surut, jadi perpindahan yang akhirnya disahkan tetap
# jatuh di tempat ia benar-benar terjadi.
TAHAN_SETELAH_PINDAH = 10

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
    rujukan: list[list[float]] | None = None,
) -> list[tuple[float, float, float, float]] | None:
    """Jalur wajah selama satu slot: daftar (detik_relatif, fx, fy, arah).

    `rujukan` adalah sidik wajah subjek video ini, kalau sudah diketahui.
    Dipakai HANYA saat penjejak kehilangan orang yang sedang diikuti — lihat
    `_runut`. Tanpa itu, subjek yang bergerak cepat atau sempat tertutup
    terbaca sebagai orang lain dan bingkainya menunggu satu detik sebelum
    menyusul.

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

    mentah: list[tuple[float, list[tuple[float, float, float, float]]]] = []
    bahan: list = [] if rujukan else None
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
            kandidat = _kandidat_wajah(frame, bahan)
            if kandidat:
                mentah.append((n / fps_src, kandidat))
            elif bahan is not None:
                # Frame tanpa wajah tidak masuk `mentah`, jadi simpanannya juga
                # harus dibuang -- kalau tidak, nomor sampel dan nomor frame
                # bergeser dan sidik yang diambil milik frame yang salah.
                bahan.pop()
    finally:
        cap.release()

    titik = _runut(mentah, rujukan, _pembuat_sidik(bahan) if bahan else None)
    if not titik:
        return None

    # Lubang di tengah jalur (wajah tertutup sesaat, atau menoleh penuh) tidak
    # diisi tebakan — titik yang ada saja yang dipakai, dan renderer melakukan
    # interpolasi lurus di antaranya. Menebak posisi wajah yang tidak terlihat
    # berisiko menggerakkan bingkai ke tempat yang salah.
    #
    # Dihaluskan PER BAGIAN, dipisah di tempat orangnya berganti. Menghaluskan
    # menembus batas itu akan mengubah perpindahan tegas jadi sapuan pelan
    # selama jendelanya — persis hal yang `_runut` dibuat untuk hilangkan.
    batas = _batas_pindah(titik)
    potong = [0, *batas, len(titik)]
    xs: list[float] = []
    ys: list[float] = []
    for a, b in zip(potong, potong[1:]):
        xs += _tapis([p[1] for p in titik[a:b]])
        ys += _tapis([p[2] for p in titik[a:b]])
    ars = _tapis_arah([p[3] for p in titik], batas)
    jalur = [
        (t, x, y, a)
        for (t, _, _, _), x, y, a in zip(titik, xs, ys, ars)
    ]

    # Perpindahan harus SEKETIKA di hasil akhir, bukan miring sepanjang jarak
    # antar sampel. Titik penahan disisipkan tepat sebelum tiap batas, membawa
    # nilai lama: renderer meneruskan garis lurus di antara dua titik, jadi
    # dengan penahan ini kemiringannya terjadi dalam 1/1000 detik — satu potong
    # keras, bukan gerakan.
    if batas:
        rapat: list[tuple[float, float, float, float]] = []
        tandai = set(batas)
        for i, p in enumerate(jalur):
            if i in tandai:
                lalu = jalur[i - 1]
                rapat.append((max(lalu[0], p[0] - 0.001), lalu[1], lalu[2], lalu[3]))
            rapat.append(p)
        jalur = rapat

    # Bingkai boleh DIAM hanya kalau ruang pandangnya juga tidak berpindah.
    # Kalau orangnya menoleh dari kiri ke kanan tanpa bergeser, posisinya
    # memang tetap tapi sisi ruang kosongnya harus bertukar -- dan jalur satu
    # titik tidak bisa menyatakan itu.
    satu_arah = len(set(_kelas_arah(a) for a in ars)) <= 1
    if (
        satu_arah
        and max(xs) - min(xs) < AMBANG_GERAK
        and max(ys) - min(ys) < AMBANG_GERAK
    ):
        tengah = len(jalur) // 2
        return [(0.0, jalur[tengah][1], jalur[tengah][2], jalur[tengah][3])]

    return jalur


def _runut(
    mentah: list[tuple[float, list[tuple[float, float, float, float]]]],
    rujukan: list[list[float]] | None = None,
    sidik_ke: Callable[[int, int], list[float] | None] | None = None,
) -> list[tuple[float, float, float, float]]:
    """Pilih SATU orang per frame, dan tetap pada orang itu sampai ia benar-benar
    berganti.

    ## Masalah yang diukur

    Sebelum ini tiap frame diambil wajah TERBESAR-nya, tanpa ingatan apa pun
    tentang frame sebelumnya. Pada rekaman satu orang itu benar. Pada rekaman
    dua orang ia rusak: kedua wajah berukuran hampir sama, dan yang "terbesar"
    berganti karena selisih beberapa piksel.

    Terukur pada satu potongan podcast, 101 sampel dalam 20 detik::

        selisih posisi antar sampel, median   0,0036
        perpindahan antar orang               0,574 .. 0,606
        pergantian wajah                      22 kali
        di antaranya bertahan 1-2 sampel      13 kali

    Dua puluh dua kali dalam dua puluh detik, dan lebih dari separuhnya cuma
    kedipan satu-dua frame. Penghalusan di `_tapis` tidak membuang itu; ia
    MENGOLESKANNYA, sehingga bingkai menyapu pelan dari satu orang ke orang lain
    selama sekitar satu detik, berkali-kali. Itu yang terlihat di hasil.

    ## Yang dilakukan di sini

    Wajah yang sedang dipegang dipertahankan selama ia masih terlihat: dari
    semua wajah di frame, dipilih yang PALING DEKAT dengan posisi sebelumnya,
    bukan yang terbesar. Kedipan hilang di sumbernya.

    Perpindahan tetap boleh terjadi — orang memang berganti bicara — tapi hanya
    kalau orang yang baru bertahan `TAHAN_PINDAH` sampel berturut-turut. Sampel
    di masa tunggu itu ikut ditulis ulang ke posisi lama, jadi tidak ada satu
    frame pun yang menggantung di antara dua orang.

    ## Yang TIDAK diklaim

    Ini tidak tahu siapa yang sedang bicara. Tidak ada informasi suara di sini,
    dan ukuran wajah bukan penandanya. Yang dijamin cuma: bingkainya berhenti
    bergetar antara dua orang, dan kalau ia berpindah, perpindahannya tegas.
    """
    if not mentah:
        return []

    hasil: list[tuple[float, float, float, float]] = []
    pegang: tuple[float, float, float] | None = None
    calon: tuple[float, float, float] | None = None
    hitung = 0
    pindah = 0
    # Sampel ke berapa bingkai terakhir berpindah. Dipakai menuntut masa tenang
    # sesudahnya -- lihat TAHAN_SETELAH_PINDAH.
    pindah_di = -10**9

    for nomor, (t, kandidat) in enumerate(mentah):
        if pegang is None:
            # Titik awal ikut memakai memori. Tanpa itu, potongan yang dibuka
            # dengan dua wajah di layar bisa mengunci orang yang salah sejak
            # frame pertama, dan seluruh sisanya setia pada pilihan yang keliru.
            awal = kandidat[0]
            if rujukan and sidik_ke is not None and len(kandidat) > 1:
                for idx, k in enumerate(kandidat):
                    sd = sidik_ke(nomor, idx)
                    if sd is not None and orang_sama(sd, rujukan):
                        awal = k
                        break
            pegang = (awal[0], awal[1], awal[3])
            hasil.append((t, *pegang))
            continue

        # Yang paling dekat dengan posisi yang sedang dipegang — bukan terbesar.
        dekat = min(
            kandidat,
            key=lambda k: (k[0] - pegang[0]) ** 2 + (k[1] - pegang[1]) ** 2,
        )
        jarak = ((dekat[0] - pegang[0]) ** 2 + (dekat[1] - pegang[1]) ** 2) ** 0.5

        if jarak <= AMBANG_LONCAT:
            # Orang yang sama, sekadar bergerak. Hitungan calon direset: siapa
            # pun yang tadi mengantre sudah tidak berturut-turut lagi.
            # Arah IKUT diperbarui tiap sampel: orangnya sama, tapi ia memang
            # menoleh, dan ruang pandangnya harus mengikuti.
            pegang = (dekat[0], dekat[1], dekat[3])
            calon, hitung = None, 0
            hasil.append((t, *pegang))
            continue

        # Orang yang dipegang tidak terlihat lagi di frame ini.
        #
        # DI SINILAH memori subjek dipakai, dan cuma di sini. Kalau wajah yang
        # muncul ternyata subjek yang sama -- ia bergerak cepat, atau sempat
        # tertutup lalu muncul di tempat lain -- bingkainya ikut SEKARANG, tanpa
        # menunggu satu detik. Yang bukan subjek tetap harus mengantre.
        #
        # Sidik wajah hanya dihitung di titik ini, bukan tiap frame: terukur
        # 5,93 ms per wajah lawan 6,27 ms untuk seluruh deteksi frame, jadi
        # menghitungnya untuk semua kandidat di semua frame akan menambah 189%
        # waktu pelacakan. Keadaan "bingung" ini terjadi di sekitar 15% sampel.
        if rujukan and sidik_ke is not None:
            cocok = None
            for idx, k in enumerate(kandidat):
                sd = sidik_ke(nomor, idx)
                if sd is not None and orang_sama(sd, rujukan):
                    cocok = k
                    break
            # Masa tenang berlaku di sini juga. Memori membuat penjejak yakin
            # SIAPA yang muncul, bukan yakin bahwa memindahkan bingkai sekarang
            # adalah keputusan yang enak dilihat.
            if cocok is not None and nomor - pindah_di >= TAHAN_SETELAH_PINDAH:
                pegang = (cocok[0], cocok[1], cocok[3])
                calon, hitung = None, 0
                pindah += 1
                pindah_di = nomor
                hasil.append((t, *pegang))
                continue

        # Wajah terbesar jadi calon, tapi belum menang.
        baru = (kandidat[0][0], kandidat[0][1], kandidat[0][3])
        if calon is not None and (
            (baru[0] - calon[0]) ** 2 + (baru[1] - calon[1]) ** 2
        ) ** 0.5 <= AMBANG_LONCAT:
            hitung += 1
        else:
            calon, hitung = baru, 1

        perlu = (
            TAHAN_SETELAH_PINDAH
            if nomor - pindah_di < TAHAN_SETELAH_PINDAH
            else TAHAN_PINDAH
        )
        if hitung >= perlu:
            # Perpindahan disahkan. Sampel selama masa tunggu ditulis ulang ke
            # posisi BARU, bukan dibiarkan di posisi lama: kalau tidak, akan ada
            # satu detik di mana bingkai memandangi orang yang sudah pergi.
            for i in range(max(0, len(hasil) - hitung + 1), len(hasil)):
                hasil[i] = (hasil[i][0], *calon)
            pegang = calon
            calon, hitung = None, 0
            pindah += 1
            pindah_di = nomor
            hasil.append((t, *pegang))
        else:
            # Masih menunggu. Bingkainya TIDAK bergerak sedikit pun.
            hasil.append((t, *pegang))

    if pindah:
        log.info(
            "jalur wajah: %d perpindahan tegas (dari %d sampel) — bingkai dipotong, bukan digeser", pindah, len(mentah)
        )
    return hasil


def _pembuat_sidik(bahan: list) -> Callable[[int, int], list[float] | None]:
    """Penanya sidik wajah yang MALAS, dengan hasil yang diingat.

    Sidik hanya dihitung saat benar-benar ditanyakan. Terukur 5,93 ms per wajah
    lawan 6,27 ms untuk seluruh deteksi satu frame — menghitungnya untuk semua
    kandidat di semua frame menambah 189% waktu pelacakan, sementara penjejak
    hanya membutuhkannya di sekitar 15% sampel.

    Jawabannya diingat karena satu frame bisa ditanya dua kali: sekali untuk
    memilih kandidat, sekali lagi kalau kandidatnya berganti di putaran
    berikutnya.
    """
    ingat: dict[tuple[int, int], list[float] | None] = {}

    def tanya(nomor: int, indeks: int) -> list[float] | None:
        kunci = (nomor, indeks)
        if kunci in ingat:
            return ingat[kunci]

        hasil: list[float] | None = None
        rec = _ambil_pengenal()
        if rec is not None and 0 <= nomor < len(bahan):
            kecil, baris = bahan[nomor]
            if 0 <= indeks < len(baris):
                try:
                    b = np.asarray(baris[indeks], dtype=np.float32).reshape(1, -1)
                    vec = rec.feature(rec.alignCrop(kecil, b)).flatten()
                    hasil = [float(v) for v in vec]
                except cv2.error as exc:  # noqa: PERF203 - wajah di tepi bisa gagal
                    log.debug("gagal menghitung sidik saat melacak: %s", exc)
        ingat[kunci] = hasil
        return hasil

    return tanya


def _kelas_arah(arah: float) -> int:
    """Ruang pandang yang dituju arah ini: -1 kiri, 0 tengah, +1 kanan.

    Yang dipakai KELASNYA, bukan angkanya. `target_mendatar` hanya mengenal tiga
    posisi, jadi arah 0,42 dan 0,83 menghasilkan bingkai yang persis sama, dan
    memperlakukan keduanya sebagai berbeda cuma menambah titik tanpa mengubah
    satu piksel pun.
    """
    if arah > AMBANG_ARAH:
        return 1
    if arah < -AMBANG_ARAH:
        return -1
    return 0


def _tapis_arah(arah: list[float], batas: list[int]) -> list[float]:
    """Redam arah hadap supaya ruang pandang tidak berkedip.

    ## Kenapa perlu diredam terpisah dari posisi

    Posisi wajah bergerak halus; arah hadap tidak. Ia diturunkan dari tiga
    landmark dan bisa melintasi ambang 0,15 bolak-balik hanya karena kepala
    bergoyang sedikit. Tiap lintasan menukar ruang pandang sejauh 0,20 lebar
    keluaran -- 216 piksel pada 1080 -- jadi kedipan yang tidak terlihat di
    angkanya menjadi lompatan bingkai yang sangat terlihat.

    Median dulu, seperti posisi, lalu satu syarat tambahan: kelasnya baru
    berganti kalau kelas baru bertahan `TAHAN_PINDAH` sampel. Yang tidak
    bertahan dikembalikan ke kelas lama.

    Batas perpindahan orang dihormati: di sana kelasnya BOLEH berganti seketika
    tanpa menunggu, karena yang menghadap memang orang yang berbeda.
    """
    if not arah:
        return []

    n = len(arah)
    r = JENDELA_MEDIAN // 2
    halus = [
        float(np.median(arah[max(0, i - r) : min(n, i + r + 1)])) for i in range(n)
    ]

    tandai = set(batas)
    keluar = list(halus)
    kelas = _kelas_arah(halus[0])
    i = 1
    while i < n:
        if i in tandai:
            # Orangnya berganti: arah orang baru berlaku langsung.
            kelas = _kelas_arah(halus[i])
            i += 1
            continue
        k = _kelas_arah(halus[i])
        if k == kelas:
            i += 1
            continue
        # Kelas baru: bertahan cukup lama, atau tidak sama sekali. Batas
        # perpindahan orang mengakhiri hitungan -- di seberangnya orangnya lain.
        j = i
        while (
            j < n
            and j not in tandai
            and _kelas_arah(halus[j]) == k
        ):
            j += 1
        if j - i >= TAHAN_PINDAH:
            kelas = k
            i = j
        else:
            for m in range(i, j):
                keluar[m] = halus[i - 1]
            i = j
    return keluar


def _batas_pindah(titik: list[tuple[float, float, float, float]]) -> list[int]:
    """Indeks tempat jalur berpindah orang. Dipakai untuk tidak menghaluskan
    melintasi perpindahan.

    Menghaluskan melintasi batas persis membatalkan gunanya `_runut`: rata-rata
    bergerak akan mengubah satu perpindahan tegas jadi sapuan selama jendelanya.
    """
    return [
        i
        for i in range(1, len(titik))
        if (
            (titik[i][1] - titik[i - 1][1]) ** 2 + (titik[i][2] - titik[i - 1][2]) ** 2
        )
        ** 0.5
        > AMBANG_LONCAT
    ]


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
    tangga-tangga kecil di antara nilai yang berdekatan — dan dilewatkan
    beberapa kali, lihat LINTASAN_HALUS.
    """
    n = len(nilai)
    if n < 3:
        return list(nilai)
    r = JENDELA_MEDIAN // 2
    hasil = [
        float(np.median(nilai[max(0, i - r) : min(n, i + r + 1)])) for i in range(n)
    ]
    for _ in range(LINTASAN_HALUS):
        hasil = _haluskan(hasil)
    return hasil


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
