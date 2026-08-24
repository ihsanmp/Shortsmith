"""Daftar identitas agent dan model yang dipakai masing-masing.

## Kenapa file ini ada

Pipeline Shortsmith terdiri dari beberapa peran yang kebutuhannya jauh berbeda.
Memilih potongan mana yang jadi hook adalah penilaian editorial yang sulit dan
salah sedikit merusak seluruh video — itu pantas dapat model termahal. Melabeli
klip B-roll jadi "kota malam" atau "gym" adalah klasifikasi sepele yang model
kecil pun sudah benar. Memakai model yang sama untuk keduanya adalah pemborosan.

## Yang perlu diluruskan: tidak semua peran memakai token

Peran `kurir` (mengunduh video mentah, mengunggah hasil ke Backblaze) dan
`pengukur` (mengekstrak konsep dari video contoh) **tidak memanggil LLM sama
sekali**. Kurir hanya HTTP biasa di `api.py`; pengukur murni pengukuran teknis
lewat ffprobe dan deteksi scene di `profile.py`. Keduanya sudah nol token hari
ini — tidak ada penghematan yang bisa diambil di sana, berapa pun kecilnya model
yang dipilih. Mereka tetap didaftarkan di sini supaya peta perannya lengkap dan
supaya tidak ada yang mencoba "menghemat" di tempat yang memang sudah gratis.

Penghematan yang nyata ada di antara peran-peran yang memang memanggil LLM.

## Cara menimpa

Setiap identitas bisa ditimpa lewat environment variable
`SHORTSMITH_MODEL_<NAMA>`, misalnya:

    SHORTSMITH_MODEL_PELABEL=claude-sonnet-5

`SHORTSMITH_MODEL` (tanpa nama peran) menimpa **semua** peran sekaligus, dan
tetap ada demi kompatibilitas dengan konfigurasi lama.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

# Model termahal dipakai hanya di satu tempat: keputusan editorial.
OPUS = "claude-opus-5"
SONNET = "claude-sonnet-5"
HAIKU = "claude-haiku-4-5-20251001"


@dataclass(frozen=True)
class Identitas:
    nama: str
    model: str
    tugas: str
    pakai_llm: bool = True

    @property
    def keterangan_model(self) -> str:
        # Sengaja ASCII murni: konsol Windows default cp1252 dan em-dash di sini
        # keluar sebagai mojibake di output `shortsmith doctor`.
        return self.model if self.pakai_llm else "(tanpa LLM, 0 token)"


_DAFTAR: tuple[Identitas, ...] = (
    Identitas(
        nama="editor",
        model=OPUS,
        tugas=(
            "Memilih potongan mana yang dipakai dan urutannya. Satu kesalahan "
            "penilaian di sini merusak seluruh video, dan tidak ada tahap "
            "berikutnya yang bisa memperbaikinya."
        ),
    ),
    Identitas(
        nama="penata",
        model=SONNET,
        tugas=(
            "Menyusun B-roll di atas tulang punggung audio yang sudah dipilih "
            "editor. Pilihan potongannya sudah ditetapkan; sisanya mencocokkan "
            "gambar dengan makna kalimat — jauh lebih terkekang."
        ),
    ),
    Identitas(
        nama="pelabel",
        model=HAIKU,
        tugas=(
            "Melabeli tiap klip di pustaka B-roll dengan beberapa kata kunci. "
            "Klasifikasi pendek dan berulang atas ribuan klip: justru di sinilah "
            "model besar paling boros dan paling tidak berguna."
        ),
    ),
    Identitas(
        nama="pengukur",
        model="",
        tugas=(
            "Mengekstrak konsep dari video contoh: durasi, ritme potongan, rasio, "
            "gaya caption. Seluruhnya pengukuran ffprobe dan deteksi scene."
        ),
        pakai_llm=False,
    ),
    Identitas(
        nama="penilai",
        model=SONNET,
        tugas=(
            "Melihat klip hasil generate dan memutuskan apakah ia pantas "
            "berdiri di antara bahan asli. Bukan klasifikasi sepele: "
            "keputusannya menyuruh pengguna membuat ulang klip, dan menolak "
            "klip yang sebenarnya sudah pas sama merugikannya dengan "
            "meloloskan yang tidak pas."
        ),
    ),
    Identitas(
        nama="pemasok",
        model=SONNET,
        tugas=(
            "Menulis prompt B-roll untuk Veo saat pustaka bahan tidak cukup. "
            "Bukan keputusan editorial — potongan mana yang dipakai tetap "
            "diputuskan penata dari klip yang sudah ada. Tugasnya menerjemahkan "
            "kekurangan yang terukur menjadi deskripsi gambar yang bisa dibuat, "
            "dan itu jauh lebih terkekang daripada memilih hook."
        ),
    ),
    Identitas(
        nama="kurir",
        model="",
        tugas=(
            "Mengunduh video mentah dari storage dan mengunggah hasil render ke "
            "Backblaze. Murni HTTP — tidak ada teks yang pernah dikirim ke model."
        ),
        pakai_llm=False,
    ),
)

IDENTITAS: dict[str, Identitas] = {i.nama: i for i in _DAFTAR}


def identitas(nama: str) -> Identitas:
    try:
        return IDENTITAS[nama]
    except KeyError:
        raise ValueError(
            f"Identitas '{nama}' tidak dikenal. Pilihan: {', '.join(IDENTITAS)}"
        ) from None


def model_untuk(nama: str) -> str:
    """Model yang dipakai peran ini, setelah menghitung penimpaan environment.

    Urutan menang: SHORTSMITH_MODEL (global) > SHORTSMITH_MODEL_<NAMA> > bawaan.
    Global sengaja ditaruh paling atas: kalau seseorang mengesetnya, maksudnya
    memang menyeragamkan semuanya untuk sementara — biasanya saat menguji model
    baru — dan penimpaan per peran tidak boleh diam-diam membatalkan niat itu.
    """
    ident = identitas(nama)
    if not ident.pakai_llm:
        raise ValueError(
            f"Identitas '{nama}' tidak memakai LLM ({ident.tugas.split('.')[0]}). "
            "Meminta modelnya berarti ada salah paham tentang perannya."
        )

    global_ = os.environ.get("SHORTSMITH_MODEL", "").strip()
    if global_:
        return global_

    khusus = os.environ.get(f"SHORTSMITH_MODEL_{nama.upper()}", "").strip()
    return khusus or ident.model


def sebab_gagal(proc) -> str:
    """Kenapa satu panggilan `claude -p` gagal, dari jawaban yang benar-benar ada.

    ## Kenapa ini perlu ada

    Ketiga pemanggil dulu melaporkan `proc.stderr[-300:]`. Itu masuk akal untuk
    program biasa, tapi salah untuk `claude -p --output-format json`: alasannya
    ditulis ke STDOUT sebagai JSON, dan stderr sering kosong.

    Akibatnya terbaca di log produksi, 17 kali dalam satu job::

        pelabel gagal untuk satu kelompok (`claude -p` gagal (exit 1): ) — dilewati

    Tanda kurung yang kosong itu adalah seluruh keterangan yang ada. Kegagalannya
    ditangani dengan benar — adegan tanpa label tetap dipakai — tapi tidak ada
    satu pun petunjuk apakah itu kuota habis, model salah, atau jaringan putus,
    jadi tidak ada yang bisa diperbaiki.

    Diperiksa langsung terhadap `claude -p` yang gagal: exit 1, stdout memuat
    ``{"is_error": true, "result": "There's an issue with the selected model
    (...)", "terminal_reason": "api_error"}``, dan stderr hanya ``[claude-code:
    unrecognized_model] {...}``. Yang berguna ada di stdout.

    Urutannya: `result` dari JSON, lalu stdout mentah kalau bukan JSON (crash
    sebelum amplopnya terbentuk), lalu stderr sebagai jaring terakhir.
    """
    keluar = (getattr(proc, "stdout", "") or "").strip()
    galat = (getattr(proc, "stderr", "") or "").strip()

    pesan = ""
    sebab = ""
    try:
        amplop = json.loads(keluar)
    except (ValueError, TypeError):
        # Bukan JSON sama sekali: prosesnya jatuh sebelum sempat menulis amplop.
        pesan = keluar[-300:]
    else:
        if isinstance(amplop, dict):
            pesan = str(amplop.get("result") or "").strip()[:300]
            sebab = str(
                amplop.get("terminal_reason") or amplop.get("subtype") or ""
            ).strip()

    bagian = [b for b in (sebab, pesan or galat[-300:]) if b]
    return " — ".join(bagian) or "tanpa keterangan (stdout dan stderr kosong)"
