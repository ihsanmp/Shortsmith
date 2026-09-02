"""Menulis keterangan unggahan untuk satu klip yang sudah jadi.

## Bedanya dengan `captions.py`

`captions.py` membuat SUBTITLE — teks yang dibakar ke dalam gambar, diturunkan
langsung dari timestamp kata. Yang di sini adalah teks yang ditempel saat
mengunggah: kalimat pembuka yang membuat orang berhenti, ringkas isinya, dan
beberapa tagar.

Keduanya sering sama-sama disebut "caption", dan itu sumber kebingungan yang
mahal. Modul ini sengaja dinamai lain.

## Kenapa murah

Yang dikirim ke model hanya ucapan di dalam KLIP INI — sekitar 200-400 kata,
bukan transkrip rekaman satu jam. Satu panggilan per klip berbiaya sekitar
seperlima puluh panggilan pemilih potongan.

## Kenapa pendek

Tujuannya TikTok. Di sana keterangan dipotong setelah kira-kira satu baris, dan
sisanya bersembunyi di balik "more" yang jarang diketuk — jadi kalimat kedua dan
ketiga bukan hanya tidak menambah, mereka mendorong tagar keluar dari pandangan.
Batasnya di sini soal apa yang TERBACA, bukan apa yang diterima platform
(TikTok sendiri menampung 2200 karakter).

## Kenapa gagalnya tidak menjatuhkan apa pun

Videonya sudah jadi dan sudah bernilai saat fungsi ini dipanggil. Keterangan
adalah tambahan; menggagalkan job karena teks unggahan tidak berhasil ditulis
berarti membuang render yang berhasil demi sesuatu yang bisa diketik tangan
dalam satu menit.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from .identitas import model_untuk, sebab_gagal

log = logging.getLogger(__name__)

BATAS_DETIK = 120

# Berapa kata ucapan yang dikirim. Klip 90 detik berisi sekitar 250 kata; batas
# ini menampung yang panjang tanpa membiarkan satu klip aneh mengirim ribuan.
MAKS_KATA = 600

# Panjang maksimal kait + isi, di luar tagar. Kira-kira sepanjang yang terlihat
# di TikTok sebelum terpotong.
MAKS_KARAKTER = 150


class KeteranganError(RuntimeError):
    pass


def _prompt(ucapan: str, jenis: str, topik: str) -> str:
    bagian = [
        "Kamu menulis keterangan unggahan untuk satu video pendek.",
        "",
        "Yang kamu terima di bawah adalah UCAPAN di dalam video itu, hasil "
        "transkrip. Videonya sudah jadi; tugasmu hanya menulis teks yang "
        "ditempel saat mengunggahnya.",
        "",
        "Aturan:",
        "- Tulis dalam BAHASA YANG SAMA dengan ucapannya.",
        "- PENDEK. Ini untuk TikTok: yang terbaca sebelum terpotong cuma "
        "sekitar satu baris.",
        '- "kait" adalah pembuka yang membuat orang berhenti scroll. Satu '
        "kalimat, MAKSIMAL 12 KATA. Bukan judul, bukan rangkuman.",
        '- "isi" paling banyak SATU kalimat pendek yang menyebut isi videonya '
        "secara konkret. Kosongkan saja kalau kaitnya sudah cukup — itu "
        "pilihan yang baik, bukan kemalasan.",
        f"- kait + isi digabung HARUS di bawah {MAKS_KARAKTER} karakter.",
        "- JANGAN mengarang angka, nama, atau klaim yang tidak ada di ucapan.",
        "- Tagar 3-5 buah, relevan, huruf kecil, tanpa spasi di dalamnya.",
        "- Tanpa emoji berlebihan; paling banyak dua, dan hanya kalau menambah.",
    ]
    # Gaya bahasa dan CTA sengaja TIDAK diminta di sini.
    #
    # Keduanya pernah jadi isian manual di konsep dan dibuang — lihat docstring
    # ManualFields di models.py: pengaruhnya kecil, sementara ongkosnya dibayar
    # penuh pengguna di tiap konsep baru. Memintanya lagi lewat pintu ini akan
    # menghidupkan kembali sesuatu yang sudah diputuskan tidak sepadan.
    #
    # Nada tulisannya diambil dari ucapan di videonya sendiri, yang memang
    # sumber paling jujur untuk itu.
    if topik.strip():
        bagian.append(f"- Fokus videonya: {topik.strip()}")

    bagian += [
        "",
        f"Jenis video: {jenis}",
        "",
        "UCAPAN DI VIDEO:",
        ucapan,
        "",
        'Balas HANYA JSON: {"kait": "...", "isi": "...", "tagar": ["...", "..."]}',
        '"isi" boleh string kosong; tagar TANPA tanda pagar.',
    ]
    return "\n".join(bagian)


def tulis(ucapan: str, *, jenis: str = "short", topik: str = "") -> str:
    """Keterangan unggahan untuk klip ini. String kosong kalau tidak berhasil.

    Tidak pernah melempar: lihat docstring modul untuk alasannya.
    """
    kata = ucapan.split()
    if len(kata) < 15:
        # Terlalu sedikit untuk ditulis keterangannya secara jujur. Mengarang
        # dari lima kata menghasilkan kalimat yang tidak berasal dari videonya.
        log.info("ucapan terlalu pendek (%d kata) — keterangan dilewati", len(kata))
        return ""
    if len(kata) > MAKS_KATA:
        ucapan = " ".join(kata[:MAKS_KATA])

    claude = shutil.which("claude")
    if not claude:
        log.warning("perintah `claude` tidak ada — keterangan dilewati")
        return ""

    try:
        proc = subprocess.run(
            [claude, "-p", "--output-format", "json", "--model", model_untuk("penulis")],
            input=_prompt(ucapan, jenis, topik),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=BATAS_DETIK,
        )
        if proc.returncode != 0:
            raise KeteranganError(
                f"`claude -p` gagal (exit {proc.returncode}): {sebab_gagal(proc)}"
            )

        teks = json.loads(proc.stdout).get("result") or ""
        awal, akhir = teks.find("{"), teks.rfind("}")
        if awal < 0 or akhir < 0:
            raise KeteranganError(f"keluaran tidak mengandung JSON: {teks[:160]}")

        data = json.loads(teks[awal : akhir + 1])
        # `keterangan` adalah bentuk lama, saat kait dan isi masih satu string.
        kait = str(data.get("kait") or data.get("keterangan") or "").strip()
        isi = str(data.get("isi") or "").strip()
        if not kait:
            raise KeteranganError("keterangan kosong")

        # Kait dan isi dipisah justru supaya batasnya bisa ditegakkan tanpa
        # memotong kalimat di tengah: yang dibuang adalah isi UTUH, bukan
        # ekornya. Keterangan yang berhenti di "...yang bikin dia" lebih buruk
        # daripada keterangan yang hanya berisi kaitnya.
        if isi and len(kait) + 1 + len(isi) > MAKS_KARAKTER:
            log.info(
                "keterangan %d karakter, di atas batas %d - isi dilepas, kait dipertahankan",
                len(kait) + 1 + len(isi),
                MAKS_KARAKTER,
            )
            isi = ""

        tagar = [
            "#" + str(t).strip().lstrip("#").replace(" ", "")
            for t in (data.get("tagar") or [])
            if str(t).strip()
        ]
        teks_saja = kait if not isi else kait + "\n" + isi
        hasil = teks_saja if not tagar else teks_saja + "\n\n" + " ".join(tagar[:5])
        log.info(
            "keterangan ditulis: %d karakter teks, %d tagar",
            len(teks_saja),
            len(tagar[:5]),
        )
        return hasil
    except Exception as exc:  # noqa: BLE001
        log.warning("keterangan gagal ditulis (%s) — dilewati", exc)
        return ""


def tulis_ke(tujuan: Path, ucapan: str, *, jenis: str = "short", topik: str = "") -> None:
    """`tulis()` lalu simpan ke `tujuan`. Tidak menulis apa-apa kalau kosong."""
    ket = tulis(ucapan, jenis=jenis, topik=topik)
    if not ket:
        return
    try:
        tujuan.write_text(ket, encoding="utf-8")
    except OSError as exc:
        log.warning("keterangan gagal disimpan ke %s: %s", tujuan.name, exc)


class Antre:
    """Menulis keterangan di latar, di luar jalur kerja utama.

    ## Kenapa perlu

    `tulis()` menunggu jawaban `claude -p` — terukur 19,5 detik. Dipanggil di
    tempatnya semula, tepat sebelum `run()` mengembalikan hasilnya, detik-detik
    itu dibayar dua kali:

      - CPU menganggur. Tidak ada yang dirender selama panggilan itu menunggu
        jaringan.
      - Klip baru dilaporkan setelah keterangannya jadi, jadi unggahannya ikut
        mundur — padahal tumpang-tindih unggahan ada justru supaya waktu unggah
        bersembunyi di balik render.

    Render satu klip makan menit; panggilan ini makan 20 detik. Ia muat utuh di
    dalam bayangan render klip berikutnya, jadi menaruhnya di sini menghapus
    ongkosnya, bukan memindahkannya. Klip terakhir tetap membayar penuh — tidak
    ada render di belakangnya untuk menyembunyikannya.

    ## Kenapa satu pekerja

    Antreannya tidak pernah menumpuk: satu keterangan (20 detik) selesai jauh
    sebelum klip berikutnya (menit) tiba. Menambah pekerja berarti beberapa
    `claude -p` berjalan bersamaan tanpa satu detik pun yang dihemat.

    ## Kenapa pemanggil wajib `tunggu()`

    Laporan job memuat keterangannya, dan laporan itu dikirim setelah render
    selesai. Tanpa titik tunggu yang tegas, ada klip yang naik tanpa teks —
    kegagalan yang bergantung pada waktu, jadi ia muncul di sebagian job saja
    dan justru di job yang paling sibuk.
    """

    def __init__(self) -> None:
        self._ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="keterangan")
        self._tugas: list[Future] = []

    def kirim(self, tujuan: Path, ucapan: str, *, jenis: str, topik: str) -> None:
        self._tugas.append(self._ex.submit(tulis_ke, tujuan, ucapan, jenis=jenis, topik=topik))

    def tunggu(self) -> None:
        """Tunggu semua keterangan selesai ditulis. Aman dipanggil berulang."""
        for f in self._tugas:
            try:
                f.result()
            except Exception as exc:  # noqa: BLE001
                # `tulis_ke` sudah menelan kegagalannya sendiri; ini jaring
                # terakhir supaya satu keterangan tidak pernah menjatuhkan job.
                log.warning("keterangan gagal di latar (%s) — dilewati", exc)
        self._tugas.clear()
        self._ex.shutdown(wait=True)
