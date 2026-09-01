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

from .identitas import model_untuk, sebab_gagal

log = logging.getLogger(__name__)

BATAS_DETIK = 120

# Berapa kata ucapan yang dikirim. Klip 90 detik berisi sekitar 250 kata; batas
# ini menampung yang panjang tanpa membiarkan satu klip aneh mengirim ribuan.
MAKS_KATA = 600


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
        "- Baris pertama adalah pembuka: satu kalimat yang membuat orang "
        "berhenti scroll. Bukan judul, bukan rangkuman.",
        "- Lalu 1-2 kalimat yang menyebut isi videonya secara konkret. Sebut "
        "hal yang benar-benar dikatakan, bukan janji umum.",
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
        'Balas HANYA JSON: {"keterangan": "...", "tagar": ["...", "..."]}',
        "Keterangan boleh memuat baris baru; tagar TANPA tanda pagar.",
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
        isi = str(data.get("keterangan") or "").strip()
        if not isi:
            raise KeteranganError("keterangan kosong")

        tagar = [
            "#" + str(t).strip().lstrip("#").replace(" ", "")
            for t in (data.get("tagar") or [])
            if str(t).strip()
        ]
        hasil = isi if not tagar else f"{isi}\n\n{' '.join(tagar[:5])}"
        log.info("keterangan ditulis: %d karakter, %d tagar", len(hasil), len(tagar[:5]))
        return hasil
    except Exception as exc:  # noqa: BLE001
        log.warning("keterangan gagal ditulis (%s) — dilewati", exc)
        return ""
