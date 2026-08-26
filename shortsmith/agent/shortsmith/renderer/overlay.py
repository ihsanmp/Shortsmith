"""Renderer overlay — audio dari satu rekaman, gambar dari klip lain.

Tiga tahap, masing-masing hanya mengerjakan satu hal:

  1. **Jalur suara.** Potongan pidato diekstrak sebagai audio saja lalu
     disambung. Gambar dari rekaman suara dibuang di sini, dan tidak pernah
     ikut sampai akhir.
  2. **Jalur gambar.** Tiap slot B-roll diekstrak tanpa audio, dinormalkan ke
     rasio dan fps target, lalu disambung.
  3. **Penyatuan.** Kedua jalur digabung dalam satu encode, caption dibakar
     di atasnya.

Kenapa dua jalur digabung di ujung, bukan ditumpuk slot demi slot: menumpuk
berarti satu filter graph raksasa dengan puluhan input, yang lambat dieksekusi
dan nyaris mustahil dibaca saat ada yang salah. Dua concat sederhana lalu satu
mux memberi hasil yang sama dengan bagian yang bisa diperiksa sendiri-sendiri.

Sama seperti renderer ffmpeg, semua perintah dijalankan dengan cwd = work_dir
supaya nama file di filter graph bisa relatif — itu menghindari seluruh masalah
escaping drive letter Windows di dalam filter.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import SETTINGS
from ..kaidah import target_mendatar, target_tegak
from ..models import OverlayEDL, PlannedCut, VideoSlot
from ..probe import run
from .base import Renderer, RenderError
from .ffmpeg import _fade_audio, _punya_audio

log = logging.getLogger(__name__)


# Berapa titik jalur yang boleh masuk ke satu ekspresi.
#
# BUKAN angka pilihan sendiri — ini batas parser ffmpeg. Tiap titik menambah
# satu tingkat if() bersarang, dan penguraiannya memakai tumpukan berukuran
# tetap. Diukur langsung dengan pembungkus crop yang sama persis dengan yang
# dipakai di sini: 93 titik masih jalan, 94 gagal dengan
#
#     [Eval] Missing ')' or too many args in 'if(lt(t,...'
#     ffmpeg keluar dengan kode 4294967274   (-22, EINVAL)
#
# Pada 5 titik/detik itu potongan 18,6 detik. Format overlay tidak pernah
# menyentuhnya karena slotnya 1-4 detik, tapi format satu jalur memotong per
# kalimat utuh — dan satu kalimat podcast bisa jauh lebih panjang dari itu.
#
# Dipatok 60, bukan 93. Sisanya ruang aman: pembungkusnya berbeda sedikit
# antar renderer, dan build ffmpeg lain bisa punya tumpukan yang lebih kecil.
# Ongkos ketelitiannya nyaris nol — lihat _pangkas.
MAKS_TITIK = 60


def _sederhanakan(titik: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    """Ramer-Douglas-Peucker: buang titik yang bisa ditebak dari tetangganya.

    Cocok justru karena ekspresi yang dibangun memang lurus antar titik. Titik
    yang jatuh di garis antara tetangganya tidak membawa informasi apa pun —
    membuangnya menghasilkan ekspresi yang secara harfiah sama bentuknya.

    Yang TIDAK dibuang adalah titik tempat jalurnya berbelok, dan itulah bedanya
    dengan mengambil tiap titik ke-N: penipisan merata akan memotong justru
    lompatan tajam yang paling terlihat di hasil.
    """
    if len(titik) < 3:
        return list(titik)

    (t0, v0), (t1, v1) = titik[0], titik[-1]
    span = t1 - t0
    jauh, di = -1.0, 0
    for i in range(1, len(titik) - 1):
        t, v = titik[i]
        # Simpangan diukur TEGAK (selisih nilai), bukan tegak lurus garis.
        # Sumbunya beda satuan — detik lawan pecahan lebar frame — jadi jarak
        # tegak lurus mencampur dua hal yang tidak sebanding. Yang terlihat di
        # hasil adalah selisih posisi bingkai, dan itu yang diukur.
        tebak = v0 if span <= 0 else v0 + (v1 - v0) * (t - t0) / span
        d = abs(v - tebak)
        if d > jauh:
            jauh, di = d, i

    if jauh <= eps:
        return [titik[0], titik[-1]]
    return _sederhanakan(titik[: di + 1], eps)[:-1] + _sederhanakan(titik[di:], eps)


# Dua titik yang lebih rapat dari ini adalah POTONGAN yang disengaja, bukan dua
# sampel berurutan.
#
# Penanda strukturnya, bukan ambang nilai: sampel jalur berjarak 0,2 detik, dan
# satu-satunya yang menghasilkan jarak di bawah satu milidetik adalah titik
# penahan yang sengaja disisipkan tepat sebelum perpindahan. Memakai penanda ini
# berarti renderer tidak perlu tahu ambang "orang lain" milik pelacak.
JEDA_TANGGA = 0.002


def _potong_tangga(titik: list[tuple[float, float]]) -> list[int]:
    """Indeks awal tiap bagian, dipisah di tempat nilainya melompat tegas."""
    return [
        i
        for i in range(1, len(titik))
        if titik[i][0] - titik[i - 1][0] <= JEDA_TANGGA and titik[i][1] != titik[i - 1][1]
    ]


def _pangkas(titik: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Turunkan jumlah titik sampai muat di parser ffmpeg.

    Ambangnya dinaikkan bertahap sampai muat, bukan dipatok sekali. Jalur yang
    tenang lolos dengan ambang kecil dan nyaris tidak berubah; jalur yang
    benar-benar ramai membayar lebih banyak — dan memang jalur seperti itu yang
    tidak mungkin diwakili 60 titik tanpa kehilangan sesuatu.

    Diukur pada jalur sungguhan dari job yang gagal (74 titik, 14,6 detik,
    wajah melompat antara 0,20 dan 0,81 lebar frame)::

        74 -> 24 titik
        simpangan terbesar   0,0019 lebar frame  = 2,1 piksel pada 1080
        simpangan rata-rata  0,0004 lebar frame

    ## Perpindahan tegas TIDAK boleh ikut dipangkas

    Versi pertama memangkas seluruh jalur sebagai satu deret. Pada jalur yang
    perpindahannya banyak, itu MEMBATALKAN perpindahannya: diuji pada jalur
    buatan dengan 80 perpindahan, 79 potongan tegas tersisa 14 dan 29 sisanya
    berubah jadi sapuan pelan — persis cacat yang seluruh rantai ini dibuat
    untuk hilangkan.

    Karena itu jalurnya dipecah lebih dulu di tiap perpindahan, dan tiap bagian
    dipangkas sendiri. Ujung bagian selalu dipertahankan Douglas-Peucker, jadi
    pasangan titik yang membentuk potongan tegas tidak mungkin hilang.

    Kalau perpindahannya sendiri sudah melebihi jatah, sebagian memang harus
    dibuang — tapi yang dibuang adalah perpindahan dengan lompatan TERKECIL, dan
    bagiannya dilipat ke bagian sebelumnya sambil mempertahankan potongannya.
    Bingkai bertahan lebih lama di satu orang; ia tidak pernah menyapu.
    """
    if len(titik) <= MAKS_TITIK:
        return titik

    potong = _potong_tangga(titik)
    if potong:
        return _pangkas_bertangga(titik, potong)

    hasil = _rapatkan(titik, MAKS_TITIK)
    log.info("jalur wajah dipadatkan: %d -> %d titik", len(titik), len(hasil))
    return hasil


def _rapatkan(titik: list[tuple[float, float]], jatah: int) -> list[tuple[float, float]]:
    """Pangkas satu deret menerus sampai muat `jatah` titik."""
    if len(titik) <= jatah:
        return list(titik)
    if jatah <= 2:
        return [titik[0], titik[-1]]

    eps = 0.002
    hasil = _sederhanakan(titik, eps)
    while len(hasil) > jatah and eps < 0.5:
        eps *= 1.5
        hasil = _sederhanakan(titik, eps)

    if len(hasil) > jatah:
        # Jaring terakhir untuk deret yang mustahil disederhanakan. Ujungnya
        # dipertahankan supaya nilai tahan di awal dan akhir tetap benar.
        langkah = len(hasil) / (jatah - 1)
        pilih = {int(i * langkah) for i in range(jatah - 1)} | {len(hasil) - 1}
        hasil = [p for i, p in enumerate(hasil) if i in pilih]
    return hasil


def _pangkas_bertangga(
    titik: list[tuple[float, float]], potong: list[int]
) -> list[tuple[float, float]]:
    """Pangkas jalur yang memuat perpindahan tegas, tanpa merusak perpindahannya."""
    batas = [0, *potong, len(titik)]
    bagian = [titik[a:b] for a, b in zip(batas, batas[1:])]

    # Tiap bagian butuh minimal dua titik. Kalau bagiannya terlalu banyak,
    # perpindahan dengan lompatan terkecil dibuang lebih dulu -- itu yang paling
    # tidak terlihat -- dengan melipat bagiannya ke bagian sebelumnya.
    dibuang = 0
    while len(bagian) * 2 > MAKS_TITIK and len(bagian) > 1:
        lompat = [
            abs(bagian[i][0][1] - bagian[i - 1][-1][1]) for i in range(1, len(bagian))
        ]
        i = lompat.index(min(lompat)) + 1
        # Isi bagian ini dibuang; bingkainya bertahan di nilai bagian sebelumnya
        # sampai perpindahan berikutnya. Potongan berikutnya tetap tegas karena
        # ujung bagian sebelumnya digeser ke tepat sebelum bagian sesudahnya.
        if i + 1 < len(bagian):
            akhir = bagian[i - 1][-1]
            bagian[i - 1] = bagian[i - 1][:-1] + [
                (max(akhir[0], bagian[i + 1][0][0] - 0.001), akhir[1])
            ]
        bagian.pop(i)
        dibuang += 1

    # Sisa jatah dibagi menurut panjang tiap bagian: bagian yang memuat lebih
    # banyak gerakan memang butuh lebih banyak titik untuk mewakilinya.
    sisa = max(0, MAKS_TITIK - 2 * len(bagian))
    total = sum(len(b) for b in bagian) or 1
    hasil: list[tuple[float, float]] = []
    for b in bagian:
        jatah = 2 + int(sisa * len(b) / total)
        hasil += _rapatkan(b, jatah)

    log.info(
        "jalur wajah dipadatkan: %d -> %d titik (%d perpindahan dipertahankan%s)",
        len(titik), len(hasil), len(bagian) - 1,
        f", {dibuang} dibuang" if dibuang else "",
    )
    return hasil


def _tangga(titik: list[tuple[float, float]]) -> str:
    """Ekspresi ffmpeg untuk nilai yang berubah terhadap waktu, lurus antar titik.

    ffmpeg tidak punya array di bahasa ekspresinya, jadi jalur disusun sebagai
    if() bersarang. Panjang tapi lurus: sebelum titik pertama nilainya ditahan,
    di antara dua titik diinterpolasi lurus, setelah titik terakhir ditahan lagi.

    Menahan nilai di kedua ujung penting — tanpa itu, bingkai melompat di frame
    pertama dan terakhir slot, tepat di tempat potongan paling terlihat.

    Jumlah titiknya dibatasi di sini, bukan di tempat jalurnya dibuat: yang
    memaksakan batas itu adalah parser ffmpeg, dan modul inilah satu-satunya
    yang tahu soal ffmpeg. Pemanggil boleh mengirim jalur sepanjang apa pun.
    """
    if len(titik) == 1:
        return f"{titik[0][1]:.4f}"

    titik = _pangkas(titik)

    kemiringan = _kemiringan(titik)

    ekspresi = f"{titik[-1][1]:.4f}"
    for i in range(len(titik) - 2, -1, -1):
        (t0, v0), (t1, v1) = titik[i], titik[i + 1]
        span = max(1e-6, t1 - t0)
        # Kubik Hermite, dijabarkan jadi polinom dalam u supaya ffmpeg cukup
        # mengalikan tiga kali. Bentuk Horner: ((a*u+b)*u+c)*u+d
        m0 = kemiringan[i] * span
        m1 = kemiringan[i + 1] * span
        a = 2 * v0 - 2 * v1 + m0 + m1
        b = -3 * v0 + 3 * v1 - 2 * m0 - m1
        u = f"(t-{t0:.4f})/{span:.4f}"
        lengkung = f"((({a:.5f}*{u}+{b:.5f})*{u}+{m0:.5f})*{u}+{v0:.5f})"
        ekspresi = f"if(lt(t,{t1:.4f}),{lengkung},{ekspresi})"
    return f"if(lt(t,{titik[0][0]:.4f}),{titik[0][1]:.4f},{ekspresi})"


def _langkah(titik: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Padatkan nilai yang cuma punya beberapa tingkat jadi tangga sungguhan.

    Ruang pandang hanya mengenal tiga posisi (kiri, tengah, kanan). Tanpa
    pemadatan ini, seratus sampel yang nilainya sama menghasilkan seratus
    tingkat `if()` bersarang untuk sesuatu yang berganti dua kali -- boros, dan
    ikut memakan jatah kedalaman parser ffmpeg yang sama dengan jalur posisi.

    Yang disimpan cuma titik tempat nilainya BERGANTI, ditambah satu titik
    penahan tepat sebelumnya yang membawa nilai lama. Penahan itulah yang
    membuat pergantiannya jadi potongan keras: renderer meneruskan garis lurus
    antar titik, dan garis lurus sepanjang satu milidetik tidak terlihat sebagai
    gerakan.
    """
    if len(titik) < 2:
        return list(titik)

    hasil = [titik[0]]
    for (t0, v0), (t1, v1) in zip(titik, titik[1:]):
        if v1 == v0:
            continue
        hasil.append((max(t0, t1 - 0.001), v0))
        hasil.append((t1, v1))
    # Ujung akhir dipertahankan supaya nilainya tertahan sampai habis.
    if hasil[-1][0] < titik[-1][0]:
        hasil.append((titik[-1][0], hasil[-1][1]))
    return hasil


def _kemiringan(titik: list[tuple[float, float]]) -> list[float]:
    """Kemiringan di tiap titik, untuk kubik Hermite yang TIDAK melampaui data.

    ## Kenapa jalur lurus antar titik tidak cukup

    Renderer menarik garis lurus dari satu titik ke titik berikutnya. Posisinya
    menyambung, tapi KECEPATANNYA tidak: di tiap titik ia berubah mendadak.
    Diukur pada 9 potongan job nyata, dengan ekspresinya dicicip 30 kali per
    detik seperti yang benar-benar dirender::

        perubahan kecepatan mendadak   6,9 kali per detik

    Itu yang terlihat sebagai gerak kamera yang tersendat, dan menghaluskan
    NILAI titiknya tidak menyentuhnya sama sekali — sehalus apa pun titiknya,
    garis lurus di antaranya tetap punya sudut di tiap sambungan.

    ## Kenapa kemiringannya dibatasi (Fritsch-Carlson)

    Kubik dengan kemiringan Catmull-Rom biasa bisa MELAMPAUI kedua titiknya.
    Untuk bingkai kamera itu berarti menyapu melewati wajah lalu kembali —
    persis "goyangan" yang seluruh rantai ini dibuat untuk hilangkan, dan lebih
    buruk daripada patahan yang ia ganti.

    Pembatasan Fritsch-Carlson menjamin kurvanya monoton di tiap ruas: kalau
    datanya naik, kurvanya naik terus. Tidak ada lompatan melewati sasaran.
    """
    n = len(titik)
    if n < 2:
        return [0.0] * n

    # Kemiringan garis lurus tiap ruas.
    ruas: list[float] = []
    for (t0, v0), (t1, v1) in zip(titik, titik[1:]):
        ruas.append((v1 - v0) / max(1e-9, t1 - t0))

    m = [0.0] * n
    m[0], m[-1] = ruas[0], ruas[-1]
    for i in range(1, n - 1):
        kiri, kanan = ruas[i - 1], ruas[i]
        # Titik balik: kemiringan NOL, bukan rata-rata. Rata-rata di puncak
        # membuat kurvanya menonjol melewati puncaknya sendiri.
        if kiri * kanan <= 0:
            m[i] = 0.0
        else:
            m[i] = (kiri + kanan) / 2

    # Batasi supaya tiap ruas tetap monoton.
    for i, d in enumerate(ruas):
        if d == 0:
            m[i] = m[i + 1] = 0.0
            continue
        a, b = m[i] / d, m[i + 1] / d
        sisi = a * a + b * b
        if sisi > 9:
            skala = 3.0 / (sisi ** 0.5)
            m[i] = skala * a * d
            m[i + 1] = skala * b * d
    return m


def posisi_crop(
    fokus_x: float | None,
    fokus_y: float | None,
    arah: float = 0.0,
    jalur: list[list[float]] | None = None,
) -> str:
    """Ekspresi x:y untuk filter crop ffmpeg, mengikuti kaidah bingkai.

    Tanpa x:y, ffmpeg memusatkan crop di tengah frame. Itu asumsi yang sering
    salah: shot 16:9 biasanya membingkai subjeknya di sepertiga kiri atau kanan,
    jadi "tengah" jatuh di antara — pada satu shot bahan pengguna, tepat di setir
    mobil sementara wajahnya terpotong di tepi.

    Wajahnya TIDAK ditaruh persis di tengah bingkai baru. Ke mana ia ditaruh
    ditentukan kaidah.py: ruang pandang di depan arah hadapnya, dan mata di
    sekitar sepertiga atas. Menaruh wajah tepat di tengah adalah kesalahan yang
    lebih halus daripada crop tengah, tapi tetap kesalahan.

    `clip` menjaga jendelanya tetap di dalam gambar, jadi wajah yang berada
    sangat di tepi menghasilkan bingkai mepet tepi, bukan bilah hitam.
    """
    tx = target_mendatar(arah)
    ty = target_tegak()

    # Jalur menang atas titik statis: kalau wajahnya bergerak selama slot,
    # bingkai harus ikut, bukan berdiri di satu tempat sambil kehilangan orangnya.
    if jalur and len(jalur) > 1:
        ex = _tangga([(p[0], p[1]) for p in jalur])
        ey = _tangga([(p[0], p[2]) for p in jalur])

        # Ruang pandang MENGIKUTI WAKTU, bukan satu nilai untuk seluruh potongan.
        #
        # Sebelum ini `arah` adalah satu angka per potongan, diambil sebagai
        # median seluruh sampel. Di rekaman dua orang yang berhadapan, keduanya
        # menghadap ke sisi yang berlawanan -- jadi satu angka pasti salah di
        # salah satu sisi. Terukur pada satu job sembilan potongan::
        #
        #     perpindahan bingkai                              15
        #     yang arah hadapnya berlawanan di kedua sisi       9
        #     yang ruang pandangnya salah untuk orang baru      5
        #
        # Yang terlihat: bingkai melompat ke orang kedua, tapi ruang kosongnya
        # tetap di sisi lama, sehingga wajahnya terdorong ke tepi yang justru ia
        # hadapi. Selisihnya 0,20 lebar keluaran -- 216 piksel pada 1080.
        #
        # Jalur lama (tiga angka per titik, tanpa arah) tetap jalan: kalau
        # arahnya tidak ada, dipakai nilai potongan seperti dulu.
        if all(len(p) > 3 for p in jalur):
            etx = _tangga(_langkah([(p[0], target_mendatar(p[3])) for p in jalur]))
        else:
            etx = f"{tx:.4f}"
        return (
            f":'clip(({ex})*iw-({etx})*ow,0,iw-ow)'"
            f":'clip(({ey})*ih-{ty:.4f}*oh,0,ih-oh)'"
        )

    if jalur:
        fokus_x, fokus_y = jalur[0][1], jalur[0][2]
        # Arah dari jalurnya sendiri, bukan dari nilai potongan. Jalur satu titik
        # muncul saat bingkainya memang diam, dan `lacak` hanya mengembalikan
        # bentuk itu kalau ruang pandangnya juga tidak berpindah — jadi angka di
        # jalur adalah yang paling tepat untuk seluruh potongan.
        if len(jalur[0]) > 3:
            tx = target_mendatar(jalur[0][3])
    if fokus_x is None and fokus_y is None:
        return ""
    fx = 0.5 if fokus_x is None else fokus_x
    fy = 0.5 if fokus_y is None else fokus_y
    return (
        f":'clip({fx:.4f}*iw-{tx:.4f}*ow,0,iw-ow)'"
        f":'clip({fy:.4f}*ih-{ty:.4f}*oh,0,ih-oh)'"
    )


def _vf_slot(slot: VideoSlot, width: int, height: int, fps: int) -> str:
    """Crop ke rasio target diarahkan ke wajah (dengan punch-in opsional), lalu scale."""
    z = max(1.0, float(slot.zoom))
    ratio_w = width / height

    crop_w = f"min(iw,ih*{ratio_w:.6f})/{z:.4f}"
    crop_h = f"min(ih,iw/{ratio_w:.6f})/{z:.4f}"

    # Bilah hitam bawaan berkas dibuang LEBIH DULU. Kalau tidak, crop rasio di
    # bawah akan memotong dari gambar yang sudah berbingkai hitam, dan bilahnya
    # ikut sampai ke hasil akhir meski rasionya sudah 9:16.
    buang_bilah = f"crop={slot.crop}," if slot.crop else ""

    # Lihat _vf_chain di ffmpeg.py — alasan penempatannya sama persis.
    ratakan = f"{slot.warna}," if slot.warna else ""

    return (
        f"{buang_bilah}"
        f"crop='{crop_w}':'{crop_h}'{posisi_crop(slot.fokus_x, slot.fokus_y, slot.arah, slot.jalur)},"
        f"scale={width}:{height}:flags=lanczos,"
        f"setsar=1,"
        f"{ratakan}"
        f"fps={fps},"
        f"format=yuv420p"
    )



def _tulis_concat(work_dir: Path, nama: str, berkas: list[str]) -> str:
    (work_dir / nama).write_text(
        "\n".join(f"file '{b}'" for b in berkas) + "\n", encoding="utf-8"
    )
    return nama


class OverlayRenderer(Renderer):
    name = "overlay"

    def preflight(self) -> list[str]:
        from ..probe import preflight as probe_preflight

        return probe_preflight()

    # ------------------------------------------------------------------
    # Tahap 1 — jalur suara
    # ------------------------------------------------------------------

    def _potong_audio(self, cut: PlannedCut, i: int, src: str, work_dir: Path) -> str:
        nama = f"aud_{i:03d}.wav"
        cmd = [
            SETTINGS.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{cut.in_:.3f}",
            "-i", src,
            "-t", f"{cut.durasi:.3f}",
            "-vn",
            # Penguatan DULU, fade belakangan. Urutan sebaliknya akan
            # mengeraskan kembali bagian yang baru saja diredupkan, sehingga
            # fade-nya tidak lagi mencapai nol di ujung potongan.
            "-af", (f"volume={cut.gain_db:+.2f}dB," if cut.gain_db else "")
                   + _fade_audio(cut.durasi),
            "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
            nama,
        ]
        run(cmd, cwd=work_dir)
        if not (work_dir / nama).exists():
            raise RenderError(f"Potongan suara {i} gagal dibuat.")
        return nama

    # ------------------------------------------------------------------
    # Tahap 2 — jalur gambar
    # ------------------------------------------------------------------

    def _potong_video(
        self, slot: VideoSlot, i: int, edl: OverlayEDL, work_dir: Path
    ) -> str:
        nama = f"vid_{i:03d}.mov"

        # Jumlah frame ditetapkan eksplisit, BUKAN lewat `-t`.
        #
        # Dengan `-t`, panjang keluaran bergantung pada di mana fast-seek `-ss`
        # mendarat, sehingga tiap segmen bisa meleset sepertiga frame. Kecil,
        # tapi menumpuk: diukur pada satu render, 40 segmen membuat jalur gambar
        # 0,47 detik lebih pendek dari jalur suara. Caption dibakar ke gambar
        # sementara posisinya dihitung dari garis waktu suara, jadi selisih itu
        # muncul sebagai subtitle yang makin tertinggal.
        #
        # `-frames:v` menghasilkan tepat N frame, setiap kali.
        jumlah_frame = max(1, round(slot.durasi * edl.fps))

        cmd = [
            SETTINGS.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{slot.in_:.3f}",
            "-i", slot.src,
            "-frames:v", str(jumlah_frame),
            "-an",  # audio klip dibuang total — suaranya datang dari jalur lain
            "-map", "0:v:0",
            "-vf", _vf_slot(slot, edl.resolution.width, edl.resolution.height, edl.fps),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
            nama,
        ]
        run(cmd, cwd=work_dir)
        if not (work_dir / nama).exists():
            raise RenderError(f"Slot gambar {i} gagal dibuat.")
        return nama

    # ------------------------------------------------------------------
    # Tahap 3 — satukan
    # ------------------------------------------------------------------

    def _satukan(
        self,
        daftar_video: str,
        daftar_audio: str,
        edl: OverlayEDL,
        work_dir: Path,
        output: Path,
        ass_file: str | None,
    ) -> None:
        graph = [f"[0:v]{'ass=' + ass_file if ass_file else 'null'}[v]"]

        cmd = [
            SETTINGS.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", daftar_video,
            "-f", "concat", "-safe", "0", "-i", daftar_audio,
        ]

        # Musik latar. Sampai perbaikan ini, jalur overlay MENGABAIKANNYA
        # sepenuhnya: `OverlayEDL` punya field `music`, tapi tidak ada satu pun
        # kode di sini yang membacanya -- jadi lagu yang dipilih pengguna hilang
        # tanpa satu baris pun peringatan. Yang terlihat di log cuma "lagu:
        # <nama berkas>", dan itu ditulis daemon sebelum berkasnya diserahkan.
        pakai_musik = edl.music is not None
        if pakai_musik:
            # -stream_loop -1: lagu yang lebih pendek dari videonya diulang,
            # bukan berhenti di tengah dan meninggalkan sisanya sunyi.
            # -ss SEBELUM -i: mencari di dalam berkas masukan, bukan memotong
            # keluaran. Ditaruh setelah -stream_loop supaya tiap pengulangan
            # kembali ke titik yang sama, bukan ke detik nol — kalau tidak,
            # pengulangan kedua membawa kembali intro yang sengaja dihindari.
            cmd += ["-stream_loop", "-1"]
            if edl.music.mulai > 0:
                cmd += ["-ss", f"{edl.music.mulai:.3f}"]
            cmd += ["-i", edl.music.src]
            total = edl.total_duration
            mulai_fade = max(0.0, total - edl.music.fade_out)
            graph.append(
                f"[2:a]volume={edl.music.gain_db}dB,"
                f"afade=t=out:st={mulai_fade:.2f}:d={edl.music.fade_out:.2f}[m]"
            )
            # normalize=0 penting: tanpa itu amix menurunkan volume suara utama
            # untuk memberi ruang pada musik, dan ucapannya ikut mengecil.
            graph.append("[1:a][m]amix=inputs=2:duration=first:normalize=0[a]")

        cmd += [
            "-filter_complex", ";".join(graph),
            "-map", "[v]", "-map", "[a]" if pakai_musik else "1:a:0",
            # Jalur gambar disusun agar sama panjang dengan jalur suara, tapi
            # pembulatan frame bisa menyisakan selisih puluhan milidetik.
            # -shortest memotongnya di titik terpendek, jadi tidak pernah ada
            # ekor hitam atau suara menggantung tanpa gambar.
            "-shortest",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
            "-g", str(edl.fps * 2),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart",
            str(output.resolve()),
        ]

        log.info("encode akhir -> %s", output)
        run(cmd, cwd=work_dir)

    # ------------------------------------------------------------------

    def build(self, edl: OverlayEDL, work_dir: Path, output: Path) -> Path:
        work_dir.mkdir(parents=True, exist_ok=True)
        output.parent.mkdir(parents=True, exist_ok=True)

        if not _punya_audio(edl.audio.src):
            raise RenderError(
                f"Sumber suara '{Path(edl.audio.src).name}' tidak punya track audio. "
                "Format overlay tidak punya apa pun untuk dibunyikan."
            )

        log.info(
            "render overlay: %.1fs suara (%d potongan) + %d slot gambar, %dx%d @ %dfps",
            edl.total_duration, len(edl.audio.cuts), len(edl.video),
            edl.resolution.width, edl.resolution.height, edl.fps,
        )

        potongan_audio: list[str] = []
        for i, cut in enumerate(edl.audio.cuts):
            log.info(
                "  suara %d/%d: %.2f-%.2f (%.2fs, %s)",
                i + 1, len(edl.audio.cuts), cut.in_, cut.out, cut.durasi, cut.role.value,
            )
            potongan_audio.append(self._potong_audio(cut, i, edl.audio.src, work_dir))

        potongan_video: list[str] = []
        for i, slot in enumerate(edl.video):
            log.info(
                "  gambar %d/%d: t=%.2f (%.2fs) <- %s @ %.2f",
                i + 1, len(edl.video), slot.t, slot.durasi,
                Path(slot.src).name, slot.in_,
            )
            potongan_video.append(self._potong_video(slot, i, edl, work_dir))

        daftar_video = _tulis_concat(work_dir, "concat_video.txt", potongan_video)
        daftar_audio = _tulis_concat(work_dir, "concat_audio.txt", potongan_audio)

        ass_file: str | None = None
        if edl.captions and edl.caption_style.ada:
            from ..captions import write_ass

            ass_file = "captions.ass"
            write_ass(
                edl.captions,
                edl.caption_style,
                work_dir / ass_file,
                width=edl.resolution.width,
                height=edl.resolution.height,
            )

        self._satukan(daftar_video, daftar_audio, edl, work_dir, output, ass_file)

        if not output.exists() or output.stat().st_size == 0:
            raise RenderError(f"Render selesai tapi {output} kosong.")

        log.info("selesai: %s (%.1f MB)", output, output.stat().st_size / 1e6)
        return output
