"""Memori tokoh: siapa saja yang boleh muncul di video, diingat antar project.

## Kenapa perlu diingat, bukan ditemukan ulang

Sebelum ini, tokoh utama diturunkan dari rekaman suara pada SETIAP render, dan
tokoh pendukung ditemukan ulang dengan mengelompokkan wajah di bahan yang ada
saat itu. Dua-duanya bekerja, tapi keduanya rapuh dengan cara yang sama: hasilnya
bergantung pada bahan yang kebetulan diunggah untuk project itu.

Akibat nyatanya:

- Rekaman suara yang menampilkan dua orang di kamera akan membuat sistem memilih
  wajah yang paling besar di frame — belum tentu yang dimaksud.
- Project yang bahannya sedikit bisa memilih tokoh pendukung yang berbeda dari
  project sebelumnya, sehingga dua video dari kanal yang sama menampilkan orang
  pendukung yang tidak konsisten.

Tokoh adalah properti KANAL, bukan properti satu project. Karena itu disimpan.

## Cara kerjanya

Saat pertama kali dikenali, tokoh langsung dicatat di berkas ini. Render-render
berikutnya memakai catatan itu dan tidak menebak lagi. Tidak ada langkah setup
yang harus dijalankan pengguna — memori terisi sendiri dari pekerjaan pertama.

Beberapa vektor disimpan per tokoh, bukan satu rata-rata. Wajah orang yang sama
terlihat sangat berbeda antara menunduk, tertawa, dan menyamping; merata-ratakan
semuanya menghasilkan vektor yang tidak menyerupai satu pun pose aslinya.

Untuk melupakan dan mengenali ulang, hapus berkasnya — isinya JSON biasa dan
aman dibaca manusia.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import SETTINGS

log = logging.getLogger(__name__)

# Berapa banyak pose yang disimpan per tokoh. Cukup untuk menangkap variasi
# wajah yang sama tanpa membuat berkasnya tidak bisa dibaca manusia.
MAKS_POSE = 8

BERKAS = Path("tokoh.json")


@dataclass
class Tokoh:
    peran: str          # "utama" atau "pendukung"
    catatan: str        # label adegan pertama tempat ia dikenali — untuk manusia
    sidik: list[list[float]] = field(default_factory=list)
    dicatat: str = ""

    def to_json(self) -> dict:
        return {
            "peran": self.peran,
            "catatan": self.catatan,
            "dicatat": self.dicatat,
            "sidik": self.sidik,
        }


def _berkas() -> Path:
    return (SETTINGS.work_dir.parent / BERKAS).resolve()


def muat() -> dict[str, Tokoh]:
    p = _berkas()
    if not p.exists():
        return {}
    try:
        mentah = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("memori tokoh tidak terbaca (%s) — dikenali ulang", exc)
        return {}

    hasil: dict[str, Tokoh] = {}
    for peran, d in mentah.items():
        sidik = d.get("sidik") or []
        if sidik:
            hasil[peran] = Tokoh(
                peran=peran,
                catatan=d.get("catatan", ""),
                sidik=sidik,
                dicatat=d.get("dicatat", ""),
            )
    return hasil


def catat(peran: str, sidik: list[list[float]], catatan: str = "") -> None:
    """Simpan tokoh. Menimpa catatan lama untuk peran yang sama."""
    if not sidik:
        return
    p = _berkas()
    semua = {k: v.to_json() for k, v in muat().items()}
    semua[peran] = Tokoh(
        peran=peran,
        catatan=catatan,
        sidik=[list(map(float, s)) for s in sidik[:MAKS_POSE]],
        dicatat=datetime.now().strftime("%Y-%m-%d %H:%M"),
    ).to_json()

    try:
        p.write_text(json.dumps(semua, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        # Gagal menulis memori tidak boleh menjatuhkan render — paling buruk
        # tokohnya dikenali ulang di render berikutnya.
        log.warning("tidak bisa menyimpan memori tokoh: %s", exc)
        return

    log.info("tokoh %s diingat: %s (%d pose) -> %s", peran, catatan or "tanpa label", len(sidik), p.name)
