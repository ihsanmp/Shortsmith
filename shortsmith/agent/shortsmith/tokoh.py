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

## Kenapa dikunci per konsep, dan bukan satu catatan untuk semua

Versi pertama menyimpan satu "utama" dan satu "pendukung" untuk SELURUH mesin.
Itu membaca "properti kanal" seolah-olah cuma ada satu kanal.

Terbukti salah pada pemakaian nyata. Wajah yang dicatat 2026-08-17 dari sebuah
video trading dipakai sebagai rujukan untuk podcast yang sama sekali lain, dan
akibatnya terbaca di log::

    tokoh utama dari memori: Berani Ambil Aksi
    tokoh pendukung dari memori: ... (0 adegan cocok)
    hanya 1 adegan menampilkan tokoh yang sama (dari 150)

Muncul 20 kali. Penyaringannya tidak pernah sekali pun berhasil: rujukannya
orang yang memang tidak ada di bahan mana pun.

Konsep adalah pendekatan terdekat untuk "kanal" yang benar-benar ada di data —
satu konsep diturunkan dari satu video contoh, dan video yang dibuat dari konsep
yang sama memang berasal dari kanal yang sama. Jadi kuncinya konsep.

Itu memperkecil kerusakan, tapi tidak menghapusnya: satu konsep yang sama bisa
dipakai untuk tamu yang berbeda. Karena itu pemanggilnya masih WAJIB memeriksa
apakah yang diingat memang muncul di bahan sekarang — lihat `_saring_tokoh` di
overlay.py. Memori di sini adalah usulan, bukan keputusan.

## Cara kerjanya

Saat pertama kali dikenali, tokoh langsung dicatat di berkas ini. Render-render
berikutnya memakai catatan itu selama masih cocok dengan bahannya.

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

# Dipakai saat pemanggil tidak menyebut konsep. Bukan pengganti diam-diam untuk
# perilaku global yang lama: kunci ini tetap terpisah dari konsep mana pun, jadi
# ia tidak bisa bocor ke project yang punya konsep.
KANAL_BAWAAN = "_tanpa_konsep"


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


def _baca() -> dict[str, dict]:
    """Seluruh isi berkas, sudah dalam bentuk berkunci-konsep.

    Berkas versi lama berbentuk datar (`{"utama": {...}}`) tanpa konsep. Isinya
    TIDAK dipindahkan ke konsep mana pun: tidak ada cara mengetahui konsep mana
    yang dulu mencatatnya, dan menebak berarti mengulang persis bug yang
    pengunciannya dibuat untuk memperbaiki. Ia diabaikan, dan alasannya dicatat
    supaya tidak terbaca sebagai memori yang hilang tanpa sebab.
    """
    p = _berkas()
    if not p.exists():
        return {}
    try:
        mentah = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("memori tokoh tidak terbaca (%s) — dikenali ulang", exc)
        return {}
    if not isinstance(mentah, dict):
        return {}

    if any(isinstance(v, dict) and "sidik" in v for v in mentah.values()):
        log.info(
            "memori tokoh versi lama (tanpa konsep) diabaikan — tokoh dikenali "
            "ulang dan dicatat per konsep"
        )
        return {}
    return {k: v for k, v in mentah.items() if isinstance(v, dict)}


def muat(kanal: str = "") -> dict[str, Tokoh]:
    """Tokoh yang diingat untuk satu konsep. Kosong kalau belum ada."""
    isi = _baca().get(kanal or KANAL_BAWAAN, {})
    hasil: dict[str, Tokoh] = {}
    for peran, d in isi.items():
        if not isinstance(d, dict):
            continue
        sidik = d.get("sidik") or []
        if sidik:
            hasil[peran] = Tokoh(
                peran=peran,
                catatan=d.get("catatan", ""),
                sidik=sidik,
                dicatat=d.get("dicatat", ""),
            )
    return hasil


def catat(peran: str, sidik: list[list[float]], catatan: str = "", kanal: str = "") -> None:
    """Simpan tokoh. Menimpa catatan lama untuk peran yang sama di konsep ini."""
    if not sidik:
        return
    kunci = kanal or KANAL_BAWAAN
    p = _berkas()
    semua = _baca()
    semua.setdefault(kunci, {})[peran] = Tokoh(
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

    log.info(
        "tokoh %s diingat untuk konsep %s: %s (%d pose) -> %s",
        peran, kunci, catatan or "tanpa label", len(sidik), p.name,
    )
