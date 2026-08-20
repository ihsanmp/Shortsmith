"""Cache berkas yang sudah diunduh, dikunci oleh storage key.

## Kenapa ini ada

Backblaze B2 menagih — dan membatasi — bandwidth unduhan. Tier gratisnya 1 GB
per hari, dan agent ini mengunduh ulang seluruh bahan pada SETIAP job. Job yang
gagal mengulang tiga kali, masing-masing mengunduh ulang semuanya dari nol.

Akibatnya nyata dan sempat menghentikan pekerjaan: B2 menolak dengan

    AccessDenied: Cannot download file, download bandwidth or transaction
    (Class B) cap exceeded.

Padahal berkasnya persis sama. Satu project dengan empat video 220 MB yang
gagal tiga kali menghabiskan 880 MB — hampir seluruh kuota harian — untuk
mengunduh berkas yang identik.

## Kuncinya storage key, bukan nama berkas

Nama berkas bisa sama untuk isi yang berbeda ("output.mp4" di dua project).
Storage key selalu unik per objek karena memuat tanggal dan hash acak, jadi
memakainya sebagai kunci membuat tabrakan mustahil.

Ukuran berkas diperiksa ulang sebelum dipakai: unduhan yang terpotong di tengah
akan meninggalkan berkas pendek, dan memakai berkas semacam itu menghasilkan
kegagalan yang jauh lebih membingungkan daripada mengunduh ulang.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from .config import SETTINGS

log = logging.getLogger(__name__)

# Berkas yang lebih kecil dari ini hampir pasti unduhan yang terpotong, bukan
# video sungguhan.
MIN_BYTE = 1024


def _nama_aman(storage_key: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", storage_key)[-180:]


def folder() -> Path:
    d = SETTINGS.work_dir / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ambil(storage_key: str, tujuan: Path) -> bool:
    """Salin dari cache ke `tujuan` kalau ada. True kalau berhasil."""
    if not storage_key:
        return False
    sumber = folder() / _nama_aman(storage_key)
    if not sumber.exists() or sumber.stat().st_size < MIN_BYTE:
        return False

    tujuan.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(sumber, tujuan)
    log.info(
        "dari cache: %s (%.1f MB, tidak mengunduh ulang)",
        tujuan.name, sumber.stat().st_size / 1e6,
    )
    return True


def simpan(storage_key: str, berkas: Path) -> None:
    """Simpan salinan ke cache. Kegagalan di sini tidak pernah menggagalkan job."""
    if not storage_key or not berkas.exists() or berkas.stat().st_size < MIN_BYTE:
        return
    try:
        shutil.copyfile(berkas, folder() / _nama_aman(storage_key))
    except OSError as exc:  # noqa: BLE001 — cache penuh atau disk bermasalah
        log.warning("gagal menyimpan ke cache (%s) — diabaikan", exc)
