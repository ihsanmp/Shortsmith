"""Menemukan beberapa topik berbeda di dalam satu rekaman panjang.

## Kenapa ini ada

Rekaman podcast satu jam memuat banyak bagian yang layak berdiri sendiri.
Kalau pengguna menuliskan topiknya, ia sudah memilih; kalau tidak, memilihkan
SATU untuknya berarti membuang lima puluh menit sisanya tanpa ia pernah tahu
apa yang ada di sana.

Jadi saat topik dikosongkan, rekaman itu dipecah jadi beberapa klip -- masing
masing dari bagian yang berbeda.

## Kenapa hanya untuk short dan podcast

Keduanya digerakkan oleh apa yang DIKATAKAN, jadi "topik" memang satuan yang
ada di dalamnya dan bisa dipisah. Cinematic dan AMV digerakkan oleh gaya
gambar dan musik; keduanya tidak punya topik untuk dipisah, dan memaksanya
akan memotong satu rangkaian visual jadi beberapa potongan yang lebih lemah
daripada aslinya.

## Kenapa penemuan topik terpisah dari pemilihan potongan

`decide` sudah pandai menyusun potongan UNTUK sebuah topik, dan pekerjaan itu
tidak perlu diubah. Yang belum ada adalah langkah sebelumnya: memutuskan topik
apa saja yang ada. Memisahkannya berarti tiap klip tetap melewati validator
yang sama persis seperti klip tunggal -- tidak ada jalur kedua yang aturannya
diam-diam berbeda.

Hasilnya juga cuma teks. Tiap topik menjadi `brief` untuk satu panggilan
`decide` biasa, jadi tidak ada bentuk data baru yang harus dimengerti sisa
pipeline.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess

from .identitas import model_untuk
from .models import ConceptProfile, ProjectMap

log = logging.getLogger(__name__)

BATAS_DETIK = 240

# Batas atas berapa klip yang dibuat dari satu rekaman.
#
# Bukan batas teknis. Tiap klip menjalankan satu panggilan model editorial yang
# mahal ditambah satu render penuh, dan nilai klip kelima dari rekaman yang
# sama jauh di bawah klip pertama -- bagian terbaiknya sudah terpakai.
MAKS_KLIP = 5
MIN_KLIP = 2

# Berapa menit rekaman yang dianggap layak menghasilkan satu klip tambahan.
#
# Sepuluh menit bukan angka ajaib; ia sekadar menyatakan bahwa rekaman yang
# lebih panjang memuat lebih banyak bagian yang berdiri sendiri. Rekaman 61
# menit menghasilkan 5 klip (dibatasi MAKS_KLIP), rekaman 20 menit menghasilkan
# 2.
MENIT_PER_KLIP = 10.0

# Jenis yang boleh dipecah. Lihat docstring modul untuk alasan cinematic dan
# AMV tidak termasuk.
JENIS_BOLEH = {"short", "podcast"}


class TopikError(RuntimeError):
    pass


def jumlah_klip(durasi_detik: float) -> int:
    """Berapa klip yang pantas dari rekaman sepanjang ini."""
    n = int(durasi_detik / 60.0 / MENIT_PER_KLIP)
    return max(MIN_KLIP, min(MAKS_KLIP, n))


def boleh_dipecah(jenis: str, brief: str) -> bool:
    """Apakah job ini menghasilkan beberapa klip, bukan satu.

    Brief yang diisi SELALU menang. Pengguna yang menuliskan topiknya sudah
    memilih, dan memberinya empat video yang tiga di antaranya membahas hal lain
    adalah mengabaikan permintaannya.
    """
    return jenis in JENIS_BOLEH and not brief.strip()


def _ringkas_ucapan(vmap: ProjectMap, maks: int = 700) -> str:
    """Transkrip yang dipadatkan jadi baris bertimestamp, untuk dibaca model.

    Diambil merata sepanjang durasi, bukan dari awal saja: topik yang ada di
    menit ke-50 harus punya kesempatan yang sama dengan yang di menit pertama,
    dan memotong daftar dari depan akan membuat separuh belakang rekaman tidak
    pernah terlihat.
    """
    v = next((x for x in vmap.videos if x.segments), None)
    if v is None:
        return ""
    seg = v.segments
    if len(seg) > maks:
        langkah = len(seg) / maks
        seg = [seg[int(i * langkah)] for i in range(maks)]
    return "\n".join(f"[{s.start:.0f}s] {s.text.strip()}" for s in seg)


def cari_topik(
    vmap: ProjectMap, profile: ConceptProfile, jumlah: int, *, sudah_dipakai: str = ""
) -> list[str]:
    """Daftar topik berbeda yang ada di rekaman, satu kalimat masing-masing.

    Mengembalikan daftar kosong kalau gagal. Pemanggil memperlakukan itu sebagai
    "buat satu klip seperti biasa" -- kegagalan menemukan topik tidak boleh
    menggagalkan job yang sebenarnya masih bisa menghasilkan satu video.
    """
    claude = shutil.which("claude")
    if not claude:
        log.warning("perintah `claude` tidak ada — pembagian topik dilewati")
        return []

    ucapan = _ringkas_ucapan(vmap)
    if not ucapan:
        return []

    durasi = max((v.media.durasi for v in vmap.videos), default=0.0)

    # Bagian yang sudah dipakai klip pertama disebutkan supaya TIDAK diulang.
    # Tanpa ini model kemungkinan besar memilih bagian terbaik rekaman lagi --
    # bagian yang sama yang baru saja jadi klip.
    hindari = ""
    if sudah_dipakai.strip():
        hindari = (
            "SATU KLIP SUDAH DIBUAT dari rekaman ini, tentang: "
            f"{sudah_dipakai.strip()} "
            "Jangan memilih bagian itu lagi; cari yang benar-benar lain. "
        )

    prompt = (
        "Kamu editor video. Di bawah ini transkrip sebuah rekaman panjang, "
        "dengan penanda waktu dalam detik.\n\n"
        f"Rekaman ini {durasi / 60:.0f} menit. Tugasmu memilih {jumlah} BAGIAN "
        "berbeda yang masing-masing layak jadi video pendek berdiri sendiri.\n\n"
        "Aturan:\n"
        "- Tiap bagian harus membahas hal yang BERBEDA. Dua video tentang hal "
        "yang sama membuat yang kedua tidak ada gunanya.\n"
        "- Pilih bagian yang punya isi, bukan basa-basi pembuka atau penutup.\n"
        "- Sebarkan sepanjang rekaman. Kalau semuanya diambil dari sepuluh "
        "menit pertama, sisa rekamannya terbuang.\n"
        "- Tulis tiap topik sebagai SATU kalimat yang menyebut secara konkret "
        "apa yang dibahas di bagian itu. Kalimat ini akan dipakai sebagai "
        "arahan untuk memilih potongan, jadi 'membahas ekonomi' terlalu "
        "kabur — sebutkan klaim atau ceritanya.\n"
        "- Pakai bahasa yang sama dengan transkripnya.\n\n"
        f"{hindari}\n"
        f"TRANSKRIP:\n{ucapan}\n\n"
        f'Balas HANYA JSON: {{"topik": ["...", "..."]}} berisi persis {jumlah} '
        "kalimat."
    )

    try:
        proc = subprocess.run(
            [claude, "-p", "--output-format", "json", "--model", model_untuk("editor")],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=BATAS_DETIK,
        )
        if proc.returncode != 0:
            raise TopikError(f"`claude -p` gagal (exit {proc.returncode})")
        teks = json.loads(proc.stdout).get("result") or ""
        awal, akhir = teks.find("{"), teks.rfind("}")
        if awal < 0 or akhir < 0:
            raise TopikError(f"keluaran tidak mengandung JSON: {teks[:160]}")
        daftar = json.loads(teks[awal : akhir + 1]).get("topik") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("pembagian topik gagal (%s) — dibuat satu klip saja", exc)
        return []

    bersih = [t.strip() for t in daftar if isinstance(t, str) and t.strip()]
    if not bersih:
        log.warning("pembagian topik tidak menghasilkan apa pun — dibuat satu klip saja")
        return []

    if len(bersih) > jumlah:
        bersih = bersih[:jumlah]
    log.info("%d topik ditemukan dari rekaman %.0f menit:", len(bersih), durasi / 60)
    for i, t in enumerate(bersih, 1):
        log.info("   %d. %s", i, t[:100])
    return bersih
