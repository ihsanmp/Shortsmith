"""Menjaga folder unduhan dan memindahkan klip baru ke folder bahan yang benar.

## Kenapa ini yang diotomatiskan, bukan Flow-nya

Langganan Gemini konsumen tidak punya jalur API sama sekali - sudah diperiksa di
halaman harga, halaman paket, dan dokumentasi billing Gemini API. Jadi
"otomatis" untuk langganan berarti menggerakkan antarmukanya, dan itu punya
harga yang tidak tertulis di halaman mana pun: akun Google yang sama memegang
email, Drive, dan foto pengguna.

Yang bisa dihapus tanpa menyentuh soal itu adalah sisanya, dan sisanya ternyata
bagian terbesar. Satu putaran manual terdiri dari: menulis prompt, menempel ke
Flow, menunggu, mengunduh, mencari berkasnya di folder unduhan, menebak nama
yang cocok, memindahkannya ke folder jenis yang benar. Hanya dua langkah tengah
yang benar-benar butuh tangan.

## Yang paling mudah salah di sini

Mengambil berkas yang BELUM selesai diunduh. Peramban menulis berkasnya
bertahap, dan berkas mp4 setengah jadi tetap terlihat seperti mp4 biasa dari
`os.listdir` - ukurannya saja yang masih bertambah. Memindahkannya saat itu juga
menghasilkan bahan rusak yang baru ketahuan berjam-jam kemudian, saat render
gagal di tengah.

Karena itu ada dua penjagaan berlapis:

  1. **Ukurannya harus berhenti berubah** selama `TENANG` detik berturut-turut.
  2. **ffprobe harus bisa membacanya.** Berkas yang lolos pemeriksaan pertama
     karena unduhannya tersendat tetap gagal di sini, karena moov atom-nya
     belum lengkap.

Berkas sementara peramban (`.crdownload`, `.part`, `.tmp`) diabaikan sejak awal
supaya keduanya tidak perlu dijalankan sia-sia.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

log = logging.getLogger(__name__)

VIDEO = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}

# Akhiran yang dipakai peramban untuk unduhan yang masih berjalan.
SEMENTARA = {".crdownload", ".part", ".tmp", ".download", ".partial"}

# Berapa detik ukuran berkas harus diam sebelum dianggap selesai diunduh.
#
# Bukan sekadar "dua kali baca sama": unduhan yang tersendat karena jaringan
# bisa diam beberapa ratus milidetik di tengah jalan. Tiga detik lebih panjang
# dari sendatan biasa dan masih jauh lebih pendek dari waktu membuat satu klip.
TENANG = 3.0

JEDA = 2.0


def _stabil(berkas: Path) -> bool:
    """True kalau ukuran berkas tidak berubah selama TENANG detik."""
    try:
        awal = berkas.stat().st_size
    except OSError:
        return False
    if awal == 0:
        return False
    time.sleep(TENANG)
    try:
        return berkas.stat().st_size == awal
    except OSError:
        return False


def _terbaca(berkas: Path) -> bool:
    """True kalau ffprobe bisa membacanya sebagai video yang punya durasi."""
    from .probe import probe

    try:
        info = probe(berkas)
    except Exception as exc:
        log.warning("pantau: %s belum terbaca (%s)", berkas.name, str(exc)[:80])
        return False

    # Akses atribut langsung, BUKAN getattr dengan nilai bawaan. Versi pertama
    # fungsi ini menulis `getattr(info, "duration", 0)` sementara fieldnya
    # bernama `durasi`; hasilnya selalu 0, tiap berkas selalu ditolak, dan tidak
    # ada satu pun pesan yang muncul karena nilai bawaannya menelan kesalahan
    # itu. Nama yang salah harus jatuh dengan berisik.
    if info.durasi <= 0:
        log.warning("pantau: %s terbaca tapi durasinya nol", berkas.name)
        return False
    return True


def _nama_kosong(tujuan: Path, awalan: str = "flow") -> Path:
    """Nama berurutan yang belum terpakai di folder tujuan."""
    n = len(list(tujuan.glob(f"{awalan}-*.mp4"))) + 1
    while (calon := tujuan / f"{awalan}-{n:03d}.mp4").exists():
        n += 1
    return calon


def satu_putaran(
    sumber: Path, tujuan: Path, terlihat: set[Path], awalan: str = "flow"
) -> list[Path]:
    """Periksa folder sumber sekali; pindahkan yang sudah siap.

    `terlihat` diubah di tempat, supaya berkas yang sudah ditangani (atau yang
    sudah ada sejak sebelum pemantauan dimulai) tidak diperiksa berulang kali.
    """
    pindah: list[Path] = []
    try:
        isi = list(sumber.iterdir())
    except OSError as exc:
        log.warning("pantau: tidak bisa membaca %s (%s)", sumber, exc)
        return pindah

    for berkas in isi:
        if berkas in terlihat or not berkas.is_file():
            continue
        if berkas.suffix.lower() in SEMENTARA:
            # Sengaja TIDAK ditandai terlihat: berkas ini akan berganti nama
            # jadi berkas asli begitu unduhannya selesai, dan versi itulah yang
            # harus tertangkap di putaran berikutnya.
            continue
        if berkas.suffix.lower() not in VIDEO:
            terlihat.add(berkas)
            continue

        log.info("pantau: menemukan %s - menunggu unduhannya selesai", berkas.name)
        if not _stabil(berkas):
            log.info("pantau: %s masih bertambah, dilewati dulu", berkas.name)
            continue
        if not _terbaca(berkas):
            continue

        terlihat.add(berkas)
        tujuan.mkdir(parents=True, exist_ok=True)
        sasaran = _nama_kosong(tujuan, awalan)
        try:
            # move, bukan copy: menyisakan salinan di folder unduhan berarti
            # putaran berikutnya melihatnya lagi sebagai berkas baru kalau
            # daftar `terlihat` hilang - misalnya setelah perintah ini
            # dijalankan ulang.
            shutil.move(str(berkas), str(sasaran))
        except OSError as exc:
            log.error("pantau: gagal memindahkan %s (%s)", berkas.name, exc)
            continue

        log.info(
            "pantau: %s -> %s (%.1f MB)",
            berkas.name, sasaran, sasaran.stat().st_size / 1e6,
        )
        pindah.append(sasaran)

    return pindah


def pantau(
    sumber: Path,
    tujuan: Path,
    *,
    batas: int = 0,
    awalan: str = "flow",
) -> list[Path]:
    """Jaga `sumber` terus-menerus, pindahkan klip baru ke `tujuan`.

    `batas` adalah jumlah klip yang ditunggu sebelum berhenti sendiri; 0 berarti
    jalan sampai dihentikan. Berguna saat pengguna tahu ia akan membuat tiga
    klip: perintahnya selesai sendiri setelah yang ketiga masuk, tanpa perlu
    diingat untuk dimatikan.

    Berkas yang SUDAH ada di folder sumber saat perintah dimulai diabaikan.
    Tanpa itu, menjalankan ini akan menyapu seluruh isi folder unduhan pengguna
    ke dalam folder bahan - termasuk video yang tidak ada hubungannya.
    """
    if not sumber.is_dir():
        raise NotADirectoryError(f"Folder sumber tidak ada: {sumber}")

    terlihat = {p for p in sumber.iterdir() if p.is_file()}
    log.info("pantau: menjaga %s", sumber)
    log.info("pantau: tujuan %s", tujuan)
    log.info("pantau: %d berkas lama diabaikan", len(terlihat))
    if batas:
        log.info("pantau: berhenti sendiri setelah %d klip", batas)

    masuk: list[Path] = []
    try:
        while True:
            masuk.extend(satu_putaran(sumber, tujuan, terlihat, awalan))
            if batas and len(masuk) >= batas:
                log.info("pantau: %d klip sudah masuk, selesai", len(masuk))
                return masuk
            time.sleep(JEDA)
    except KeyboardInterrupt:
        log.info("pantau: dihentikan, %d klip masuk", len(masuk))
        return masuk
