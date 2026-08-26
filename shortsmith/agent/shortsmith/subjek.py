"""Memori subjek: siapa yang diikuti bingkai selama satu job, lalu dilupakan.

## Kenapa ada

Penjejak wajah memilih kandidat yang paling DEKAT dengan posisi sebelumnya. Itu
benar selama orangnya bergerak wajar. Tapi kalau ia bergerak cepat, sempat
tertutup, atau kameranya berpindah shot, wajahnya muncul jauh dari posisi lama —
dan penjejak membacanya sebagai orang lain. Ia lalu menunggu satu detik penuh
sebelum berani ikut, dan selama satu detik itu bingkai memandangi tempat kosong.

Agent sudah membaca seluruh rekaman saat analisis. Siapa subjeknya bukan
tebakan — ia bisa diambil sekali dari rekaman suara, lalu dipakai untuk menjawab
pertanyaan itu dengan pasti: "yang barusan muncul, apakah dia orang yang sama?"

## Kenapa per JOB, bukan per konsep

`tokoh.py` menyimpan tokoh per konsep, untuk menjaga konsistensi antar video di
kanal yang sama. Yang di sini kebutuhannya berbeda: ia cuma perlu benar selama
job ini berjalan, dan menyimpannya lebih lama tidak menambah apa pun.

Karena itu berkasnya tinggal di folder kerja job, dan `lupakan()` dipanggil
begitu videonya jadi. Memori yang menumpuk adalah memori yang suatu saat dipakai
untuk job yang salah — persis bug yang pernah terjadi dengan tokoh.json, waktu
wajah dari satu video trading dipakai sebagai patokan untuk podcast yang sama
sekali lain.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

BERKAS = "subjek.json"

# Berapa pose subjek yang disimpan. Wajah orang yang sama terlihat sangat
# berbeda antara menunduk, tertawa, dan menyamping; satu vektor saja membuat
# separuh pose aslinya tidak dikenali sebagai dirinya sendiri.
POSE = 6


def _berkas(work: Path) -> Path:
    return work / BERKAS


def ingat(work: Path, sumber: str, durasi: float, crop: str = "") -> list[list[float]]:
    """Sidik subjek untuk job ini. Dibaca dari cache kalau sudah pernah dibuat.

    Kembalikan daftar kosong kalau wajahnya tidak terbaca — itu bukan kegagalan,
    dan pemanggil harus tetap jalan tanpa memori seperti sebelum fitur ini ada.
    """
    p = _berkas(work)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return [[float(x) for x in v] for v in data]
        except (OSError, ValueError, TypeError) as exc:
            log.warning("memori subjek tidak terbaca (%s) — dibuat ulang", exc)

    from .wajah import bisa_kenal, rujukan_tokoh

    if not bisa_kenal():
        return []

    sidik = rujukan_tokoh(sumber, durasi, crop=crop, jumlah=POSE)
    if not sidik:
        log.info("wajah subjek tidak terbaca dari rekaman — pelacakan tanpa memori")
        return []

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(sidik), encoding="utf-8")
    except OSError as exc:
        # Gagal menulis tidak menjatuhkan apa pun: sidiknya sudah ada di memori
        # proses ini, dan job berikutnya akan membuatnya lagi.
        log.warning("memori subjek tidak bisa disimpan: %s", exc)

    log.info("subjek diingat untuk job ini: %d pose", len(sidik))
    return sidik


def lupakan(work: Path) -> None:
    """Hapus memori subjek. Dipanggil begitu videonya jadi.

    Tidak pernah melempar: job sudah selesai dan hasilnya sudah ada, jadi
    kegagalan menghapus satu berkas sementara tidak boleh mengubah apa pun.
    """
    try:
        _berkas(work).unlink(missing_ok=True)
    except OSError as exc:
        log.debug("memori subjek tidak bisa dihapus: %s", exc)
