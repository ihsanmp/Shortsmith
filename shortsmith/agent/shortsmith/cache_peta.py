"""Cache hasil analisis per BERKAS, bukan per job.

## Masalahnya

Peta video sudah di-cache, tapi cache-nya tinggal di folder job. Tiap job baru
dapat folder baru, jadi bahan yang sama dianalisis ulang dari nol setiap kali:

    transkrip Whisper (rekaman 27 menit)   ~10 menit
    deteksi adegan + bilah + wajah          ~4 menit
    pelabelan 135 adegan                    ~8 menit

Dua puluh menit untuk bahan yang byte-nya tidak berubah sejak render terakhir.
Itu bukan cuma lambat — pelabelan memakai model, jadi setiap pengulangan juga
membakar token untuk jawaban yang sudah pernah didapat.

## Kuncinya

Path + ukuran + waktu ubah. Bukan hash isi berkas: bahan di sini berukuran
ratusan MB dan membaca seluruhnya untuk menghitung hash menghabiskan sebagian
besar waktu yang mau dihemat. Trio ini salah hanya kalau seseorang mengganti isi
berkas sambil mempertahankan ukuran DAN waktu ubahnya — yang tidak terjadi
secara wajar.

## VERSI wajib dinaikkan saat logika analisis berubah

Cache menyimpan hasil, bukan cara mendapatkannya. Kalau deteksi bilah, deteksi
wajah, atau pelabelan diubah tapi VERSI tidak dinaikkan, bahan lama akan terus
memakai hasil lama dan perubahannya seolah tidak berpengaruh — jenis kebingungan
yang mahal karena tidak terlihat sebagai kesalahan.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from .config import SETTINGS
from .models import VideoMap

log = logging.getLogger(__name__)

# Naikkan setiap kali analyze.py, wajah.py, atau pelabel.py mengubah APA yang
# dihasilkan. Riwayat singkat supaya jelas apa yang memicu kenaikan terakhir:
#
#   1 - versi pertama
#   2 - bilah diukur dari piksel (bukan cropdetect), adegan kosong dibuang,
#       ambang wajah 0.75 -> 0.5, arah pandang, label pelabel
#   3 - adegan dipecah lagi saat bilahnya berubah di tengah (pecah_bilah)
#   4 - batas bilah diukur dari PECAHAN piksel terang, bukan rata-rata baris
#
# Sempat dinaikkan ke 5 untuk pindah ke Whisper `medium`, lalu dikembalikan:
# `medium` diuji dan TIDAK memperbaiki kata yang dikeluhkan (tetap "lakuannya"),
# sementara transkripnya 3x lebih lambat. Karena modelnya kembali `small`,
# transkrip di cache v4 masih sebanding dan tidak perlu dibuat ulang.
VERSI = 4


def _kunci(path: Path, broll: bool) -> str:
    st = path.stat()
    bahan = f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}|{int(broll)}|v{VERSI}"
    return hashlib.sha1(bahan.encode("utf-8")).hexdigest()[:20]


def _folder() -> Path:
    d = SETTINGS.work_dir / "cache" / "peta"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ambil(path: str | Path, *, broll: bool) -> VideoMap | None:
    """Peta yang tersimpan untuk berkas ini, atau None."""
    p = Path(path)
    try:
        berkas = _folder() / f"{_kunci(p, broll)}.json"
    except OSError:
        return None

    if not berkas.exists():
        return None
    try:
        peta = VideoMap.model_validate_json(berkas.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - cache rusak tidak boleh menjatuhkan job
        log.warning("cache peta rusak untuk %s (%s) — dianalisis ulang", p.name, exc)
        berkas.unlink(missing_ok=True)
        return None

    log.info("analisis dari cache bahan: %s (0 token, 0 detik)", p.name)
    return peta


def simpan(path: str | Path, peta: VideoMap, *, broll: bool) -> None:
    p = Path(path)
    try:
        berkas = _folder() / f"{_kunci(p, broll)}.json"
        berkas.write_text(peta.model_dump_json(indent=2), encoding="utf-8")
    except OSError as exc:
        # Gagal menulis cache tidak pernah boleh menggagalkan job — paling buruk
        # analisis berikutnya mengulang pekerjaan ini.
        log.warning("tidak bisa menyimpan cache peta untuk %s: %s", p.name, exc)
