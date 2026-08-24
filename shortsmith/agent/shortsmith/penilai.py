"""Memeriksa apakah klip hasil generate pantas berdiri di antara bahan asli.

## Dua pertanyaan yang berbeda, dan keduanya perlu dijawab

**Apakah ia terlihat tertempel?** Ini pertanyaan terukur. Klip yang eksposurnya
jauh dari bahan lain akan terbaca sebagai potongan dari video lain, seberapa pun
bagus isinya. Sudah ada alatnya di `warna.py`, dan jawabannya angka - tidak
perlu model apa pun, tidak perlu menunggu, tidak perlu biaya.

**Apakah isinya memang yang diminta?** Ini tidak bisa diukur. Klip bisa punya
eksposur yang pas sempurna dan tetap menampilkan hal yang sama sekali lain dari
promptnya - model video sering meleset begitu. Untuk ini gambarnya harus benar
benar dilihat.

Modul ini menjawab keduanya, dan memisahkan jawabannya supaya pengguna tahu
klipnya ditolak karena apa. "Kurang sesuai" tanpa menyebut sebabnya memaksa
pengguna menebak apakah ia harus mengulang promptnya atau cukup menerima saja.

## Kenapa satu panggilan untuk semua klip

Tiap pemanggilan `claude -p` memuat ulang konteksnya sendiri, dan itulah bagian
termahalnya - terukur $0,10 untuk satu pemanggilan yang cuma membaca satu
gambar, hampir seluruhnya dari pembuatan cache. Memeriksa lima klip satu per
satu berarti membayar ongkos itu lima kali untuk pekerjaan yang bisa muat dalam
satu percakapan.

Satu panggilan juga menghasilkan penilaian yang lebih baik: model melihat semua
klip berdampingan, jadi ia bisa menyebut klip mana yang paling menyimpang di
antara mereka - bukan menilai tiap klip terpisah tanpa pembanding.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .identitas import model_untuk, sebab_gagal
from .warna import _luma, ukur

log = logging.getLogger(__name__)

BATAS_DETIK = 240

# Selisih kecerahan (0-255) yang bikin klip terbaca sebagai tempelan.
#
# Diambil dari pengukuran di `warna.py`: pada hasil render nyata, lompatan di
# atas 25 adalah yang terlihat jelas sebagai kedipan, sedangkan yang di bawahnya
# lewat tanpa disadari. Ambang yang sama berlaku di sini karena pertanyaannya
# memang sama - apakah mata menangkap perpindahannya.
AMBANG_TERANG = 25.0

# Berapa frame yang diambil dari tiap klip untuk dilihat model.
#
# Dua, bukan satu: model video sering benar di frame pertama lalu menyimpang di
# detik berikutnya. Dan bukan lebih dari dua, karena tiap gambar menambah token
# untuk keuntungan yang menurun cepat.
FRAME_PER_KLIP = 2


@dataclass
class Penilaian:
    """Hasil pemeriksaan satu klip."""

    nama: str
    cocok: bool
    # Alasan teknis, dari pengukuran. Kosong berarti tidak ada masalah terukur.
    alasan_ukur: str = ""
    # Alasan isi, dari model yang melihat gambarnya.
    alasan_isi: str = ""
    # Prompt pengganti, hanya diisi kalau klipnya ditolak.
    prompt_baru: str = ""
    terang: float = 0.0

    @property
    def alasan(self) -> str:
        bagian = [x for x in (self.alasan_ukur, self.alasan_isi) if x]
        return " ".join(bagian)


@dataclass
class Hasil:
    penilaian: list[Penilaian] = field(default_factory=list)
    terang_bahan: float = 0.0

    @property
    def semua_cocok(self) -> bool:
        return all(p.cocok for p in self.penilaian)

    @property
    def ditolak(self) -> list[Penilaian]:
        return [p for p in self.penilaian if not p.cocok]


class PenilaiError(RuntimeError):
    pass


def _frame(video: Path, t: float, keluar: Path) -> Path | None:
    """Ambil satu frame jadi jpg, diperkecil supaya hemat token."""
    keluar.parent.mkdir(parents=True, exist_ok=True)
    hasil = subprocess.run(
        [
            "ffmpeg", "-v", "error",
            "-ss", f"{max(0.0, t):.3f}",
            "-i", str(video),
            "-frames:v", "1",
            # 640 px sudah cukup untuk menilai isi adegan, dan jauh lebih murah
            # daripada mengirim frame 1080p yang tidak menambah apa pun.
            "-vf", "scale=640:-1",
            "-q:v", "4",
            str(keluar), "-y",
        ],
        capture_output=True,
    )
    return keluar if hasil.returncode == 0 and keluar.exists() else None


def _terang(video: Path) -> float:
    """Kecerahan rata-rata satu video, 0-255."""
    from .probe import probe

    try:
        durasi = probe(video).durasi
    except Exception:
        return 0.0
    u = ukur(str(video), 0.0, durasi)
    return u.luma * 255 if u.ok else 0.0


def _minta_penilaian(
    klip: list[tuple[str, list[Path]]],
    bahan_frame: list[Path],
    jenis: str,
    prompts: dict[str, str],
    catatan_ukur: dict[str, str],
) -> dict[str, dict]:
    """Satu panggilan `claude -p` untuk seluruh klip sekaligus."""
    claude = shutil.which("claude")
    if not claude:
        raise PenilaiError("Perintah `claude` tidak ada di PATH.")

    baris = [
        "Kamu memeriksa klip hasil generate AI sebelum dipakai sebagai B-roll",
        f"dalam sebuah video berjenis '{jenis}'.",
        "",
        "CONTOH BAHAN ASLI milik pengguna (inilah yang harus disatukan dengannya):",
    ]
    baris += [f"  {p}" for p in bahan_frame]
    baris += ["", "KLIP YANG DIPERIKSA:"]

    for nama, frames in klip:
        baris.append(f"  [{nama}]")
        baris.append(f"    diminta lewat prompt: {prompts.get(nama, '(tidak diketahui)')}")
        for f in frames:
            baris.append(f"    frame: {f}")
        if catatan_ukur.get(nama):
            # Hasil pengukuran ikut diberikan supaya model tidak menebak-nebak
            # soal eksposur, dan supaya penilaiannya sejalan dengan angka yang
            # nanti ditampilkan ke pengguna - bukan bertentangan dengannya.
            baris.append(f"    catatan teknis: {catatan_ukur[nama]}")

    baris += [
        "",
        "Baca semua gambar di atas, lalu nilai TIAP klip:",
        "",
        "- cocok: apakah klip ini pantas berdiri di antara bahan asli tadi?",
        "- alasan: kalau TIDAK cocok, satu kalimat yang menyebut apa yang salah.",
        "  Sebutkan hal yang bisa dilihat - bukan penilaian samar seperti",
        "  'kurang bagus'. Kalau cocok, kosongkan.",
        "- prompt_baru: kalau TIDAK cocok, tulis prompt pengganti dalam BAHASA",
        "  INGGRIS yang memperbaiki persis masalah itu. Kalau cocok, kosongkan.",
        "",
        "Tolak hanya kalau memang ada yang salah. Menolak klip yang sebenarnya",
        "sudah pas membuat pengguna membuat ulang klip yang tidak perlu diulang.",
        "",
        'Balas HANYA JSON: {"hasil": {"<nama klip>": {"cocok": true/false,',
        '"alasan": "...", "prompt_baru": "..."}}}',
    ]

    proc = subprocess.run(
        [claude, "-p", "--output-format", "json", "--model", model_untuk("penilai")],
        input="\n".join(baris),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=BATAS_DETIK,
    )
    if proc.returncode != 0:
        raise PenilaiError(
            f"`claude -p` gagal (exit {proc.returncode}): {sebab_gagal(proc)}"
        )

    teks = json.loads(proc.stdout).get("result") or ""
    awal, akhir = teks.find("{"), teks.rfind("}")
    if awal < 0 or akhir < 0:
        raise PenilaiError(f"Keluaran penilai tidak mengandung JSON: {teks[:200]}")
    return json.loads(teks[awal : akhir + 1]).get("hasil") or {}


def periksa(
    klip: list[Path],
    bahan: list[Path],
    *,
    jenis: str = "cinematic",
    prompts: dict[str, str] | None = None,
    kerja: Path = Path(".shortsmith/penilai"),
) -> Hasil:
    """Periksa tiap klip terhadap bahan asli, secara terukur DAN secara isi.

    `bahan` boleh kosong - misalnya saat bahannya dibaca dari folder lokal dan
    tidak pernah menyentuh server. Pemeriksaan eksposurnya dilewati, dan yang
    tersisa adalah penilaian isi. Itu lebih jujur daripada membandingkan dengan
    angka yang dikarang.
    """
    if not klip:
        return Hasil()

    prompts = prompts or {}
    kerja.mkdir(parents=True, exist_ok=True)
    for lama in kerja.glob("*.jpg"):
        lama.unlink(missing_ok=True)

    # --- bagian terukur ---
    terang_bahan = 0.0
    if bahan:
        nilai = [t for t in (_terang(b) for b in bahan[:5]) if t > 0]
        if nilai:
            nilai.sort()
            terang_bahan = nilai[len(nilai) // 2]

    catatan: dict[str, str] = {}
    terang_klip: dict[str, float] = {}
    for k in klip:
        t = _terang(k)
        terang_klip[k.name] = t
        if terang_bahan and t:
            selisih = t - terang_bahan
            if abs(selisih) >= AMBANG_TERANG:
                arah = "lebih terang" if selisih > 0 else "lebih gelap"
                catatan[k.name] = (
                    f"jauh {arah} dari bahan asli "
                    f"({t:.0f} lawan {terang_bahan:.0f} dari 255)"
                )

    # --- bagian isi ---
    from .probe import probe

    bahan_frame: list[Path] = []
    for i, b in enumerate(bahan[:3]):
        try:
            d = probe(b).durasi
        except Exception:
            continue
        if (f := _frame(b, d * 0.5, kerja / f"bahan{i}.jpg")) is not None:
            bahan_frame.append(f)

    daftar: list[tuple[str, list[Path]]] = []
    for i, k in enumerate(klip):
        try:
            d = probe(k).durasi
        except Exception:
            d = 8.0
        frames = []
        for j, bagian in enumerate((0.3, 0.7)[:FRAME_PER_KLIP]):
            if (f := _frame(k, d * bagian, kerja / f"klip{i}_{j}.jpg")) is not None:
                frames.append(f)
        if frames:
            daftar.append((k.name, frames))

    jawaban: dict[str, dict] = {}
    if daftar:
        try:
            jawaban = _minta_penilaian(daftar, bahan_frame, jenis, prompts, catatan)
        except (PenilaiError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
            # Penilaian isi GAGAL bukan berarti klipnya ditolak. Menolak karena
            # pemeriksanya sendiri yang rusak akan menyuruh pengguna membuat
            # ulang klip yang mungkin sudah benar.
            log.warning("penilaian isi dilewati: %s", exc)

    hasil = Hasil(terang_bahan=terang_bahan)
    for k in klip:
        j = jawaban.get(k.name) or {}
        alasan_ukur = catatan.get(k.name, "")
        # Ukuran dan isi masing-masing bisa menolak. Klip yang eksposurnya jauh
        # menyimpang tetap ditolak walau isinya tepat, karena ia akan terlihat
        # tertempel - dan itu justru yang paling kentara di hasil jadi.
        cocok_isi = bool(j.get("cocok", True))
        cocok = cocok_isi and not alasan_ukur
        hasil.penilaian.append(
            Penilaian(
                nama=k.name,
                cocok=cocok,
                alasan_ukur=alasan_ukur,
                alasan_isi="" if cocok_isi else str(j.get("alasan") or "").strip(),
                prompt_baru="" if cocok else str(j.get("prompt_baru") or "").strip(),
                terang=terang_klip.get(k.name, 0.0),
            )
        )
    return hasil
