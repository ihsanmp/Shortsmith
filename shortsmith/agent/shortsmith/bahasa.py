"""Memperbaiki transkrip yang menyimpang jadi terjemahan bahasa Inggris.

## Gejalanya

Whisper diminta `language="id"` dan `task="transcribe"`, dan tetap menghasilkan
bahasa Inggris. Bukan sebagian kecil: pada satu rekaman podcast 61 menit, 72%
transkripnya keluar sebagai terjemahan Inggris yang rapi, dan caption yang
dibuat darinya ikut berbahasa Inggris seluruhnya.

Titik baliknya terukur di detik 182,0::

    181,x  Ini agenda krisis ...        <- masih Indonesia
    182,0  the agenda is indeed a death crisis.   <- terbalik, dan tidak kembali

## Kenapa bukan diperbaiki lewat setelan Whisper

Tiga jalur dicoba dan diukur, bukan dikira-kira:

  - `task="transcribe"` eksplisit. Sudah bawaannya; tidak mengubah apa pun.

  - `condition_on_previous_text=False`. MEMPERBURUK: 30% Inggris dengan
    simpangan mulai detik 58, lawan 0% pada setelan apa adanya di rentang uji
    yang sama. Konteks sebelumnya ternyata yang MENAHAN bahasa Indonesia;
    membuangnya membuat tiap jendela memutuskan sendiri, dan sebagian memilih
    Inggris.

  - `initial_prompt` berbahasa Indonesia. Menghapus simpangan sepenuhnya (0%,
    tanpa titik balik) TAPI kosakata promptnya bocor ke dalam transkrip:
    "Saya rasa krisis mati" menjadi "Saya rasa bahasa matahari". Caption yang
    dihasilkan jadi omong kosong, jadi ini lebih buruk daripada masalahnya.

## Yang dipakai, dan kenapa ia bekerja

Penyimpangannya bersifat menular lewat konteks: sekali terbalik, konteks
Inggris menahannya sampai akhir. Tapi jendela audio yang ditranskrip TERPISAH
tidak mewarisi konteks itu. Terukur pada dua titik di tengah wilayah yang
rusak::

    @800 detik, jendela 120 detik terpisah   ID=99  EN=0   -> Indonesia
    @1400 detik, jendela 120 detik terpisah  ID=97  EN=0   -> Indonesia

Jadi: transkrip seperti biasa, cari rentang yang menyimpang, lalu transkrip
ULANG rentang itu saja dalam potongan pendek yang tidak saling mewarisi
konteks.

## Kenapa penilaiannya per RENTANG, bukan per segmen

Dua percobaan per-segmen gagal, dan keduanya gagal dengan cara yang
mengajarkan sesuatu:

  - Menghitung kata fungsi Inggris: "it can lead to inflation and so on" lolos
    sebagai bahasa Indonesia, karena tidak memuat kata dari daftar sempit mana
    pun.
  - Menuntut adanya kata fungsi Indonesia: 81% segmen tertandai, termasuk
    "Ya." dan "Bagus, kan?" yang jelas Indonesia — segmen pendek memang tidak
    memuat kata fungsi apa pun.

Whisper menyimpang dalam rentang panjang, bukan segmen tunggal, jadi di situlah
ia harus dinilai. Penghalusan atas beberapa segmen membuat segmen pendek ikut
terbawa tetangganya, dan satu istilah serapan tidak cukup membalik penilaian.

## Kata serapan sengaja tidak diganggu

Penutur Indonesia menyelipkan istilah Inggris terus-menerus — "trading",
"market", "cash flow" — dan itu HARUS tetap tertulis sebagai bahasa Inggris.
Yang diperbaiki di sini hanyalah kalimat yang seluruhnya berpindah bahasa.
Transkrip ulangnya pun tetap memakai `language="id"`, yang memang menuliskan
istilah asing apa adanya: uji di atas mempertahankan "Rolex" dan "watches".
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from pathlib import Path

from .models import TranscriptSegment, Word

log = logging.getLogger(__name__)

# Kata fungsi. Sengaja kata fungsi, bukan kata benda: yang diselipkan penutur
# Indonesia adalah kata benda ("trading", "market"), tidak pernah "the" atau
# "that". Perbedaan itulah yang memisahkan terjemahan dari serapan.
_ID = re.compile(
    r"\b(yang|dan|itu|ini|tidak|dengan|untuk|dari|akan|adalah|di|ke|kita|saya"
    r"|kalau|bisa|sudah|juga|karena|pada|ada|jadi|atau|apa|kan|nya|lebih|masih)\b",
    re.I,
)
_EN = re.compile(
    r"\b(the|is|are|was|were|will|would|that|this|of|have|has|been|they|there"
    r"|which|because|and|to|in|it|can|not|for|with|but|so|we|you|they)\b",
    re.I,
)

# Berapa segmen tetangga di tiap sisi yang ikut dihitung. Sepuluh ke kiri dan
# sepuluh ke kanan cukup untuk menenggelamkan segmen sependek "Ya." tanpa
# mengaburkan batas rentangnya.
JENDELA = 10

# Rentang yang lebih pendek dari ini diabaikan. Beberapa segmen Inggris
# berturut-turut bisa saja memang diucapkan — pembicara mengutip kalimat
# Inggris utuh, misalnya — dan menranskrip ulang itu justru merusaknya.
MIN_SEGMEN = 6

# Panjang potongan saat menranskrip ulang, dalam detik. Harus cukup pendek
# supaya tidak menyimpang lagi: simpangan pertama terukur muncul di detik 182,
# sedangkan jendela 120 detik terbukti bersih di dua titik uji.
POTONG = 120.0

# Bahasa yang tidak perlu diperiksa. Kalau memang menargetkan bahasa Inggris,
# keluaran berbahasa Inggris bukan penyimpangan.
_LEWATI = {"", "en"}


def _skor(teks: str) -> int:
    return len(_ID.findall(teks)) - len(_EN.findall(teks))


def rentang_simpang(segments: list[TranscriptSegment]) -> list[tuple[int, int]]:
    """Indeks segmen awal dan akhir tiap rentang yang menyimpang."""
    if not segments:
        return []

    skor = [_skor(s.text) for s in segments]
    halus = [
        sum(skor[max(0, i - JENDELA) : min(len(skor), i + JENDELA + 1)])
        for i in range(len(skor))
    ]

    rentang: list[tuple[int, int]] = []
    mulai: int | None = None
    for i, h in enumerate(halus):
        if h < 0 and mulai is None:
            mulai = i
        elif h >= 0 and mulai is not None:
            rentang.append((mulai, i - 1))
            mulai = None
    if mulai is not None:
        rentang.append((mulai, len(halus) - 1))

    return [(a, b) for a, b in rentang if b - a + 1 >= MIN_SEGMEN]


def _potong_audio(src: Path, mulai: float, panjang: float, keluar: Path) -> bool:
    hasil = subprocess.run(
        [
            "ffmpeg", "-v", "error",
            "-ss", f"{mulai:.3f}", "-t", f"{panjang:.3f}",
            "-i", str(src),
            "-vn", "-ac", "1", "-ar", "16000",
            str(keluar), "-y",
        ],
        capture_output=True,
    )
    return hasil.returncode == 0 and keluar.exists() and keluar.stat().st_size > 0


def perbaiki(
    path: str | Path,
    segments: list[TranscriptSegment],
    words: list[Word],
    bahasa: str,
    ulang,
) -> tuple[list[TranscriptSegment], list[Word]]:
    """Ganti rentang yang menyimpang dengan transkrip ulang yang terpisah.

    `ulang(berkas)` mentranskrip satu potongan audio dan mengembalikan
    (segments, words) berwaktu relatif terhadap potongan itu. Disuntikkan
    sebagai parameter, bukan diimpor: modul ini tidak perlu tahu backend mana
    yang dipakai, dan itu membuatnya bisa diuji tanpa memuat model apa pun.

    Tidak pernah melempar. Perbaikan ini penghalusan; transkrip yang menyimpang
    masih jauh lebih berguna daripada job yang gagal karena perbaikannya sendiri
    bermasalah.
    """
    if bahasa.lower() in _LEWATI:
        return segments, words

    try:
        rentang = rentang_simpang(segments)
        if not rentang:
            return segments, words

        src = Path(path)
        total = sum(segments[b].end - segments[a].start for a, b in rentang)
        log.warning(
            "transkrip menyimpang ke bahasa lain pada %d rentang (%.0f detik, %.0f%% "
            "dari durasi) — ditranskrip ulang per potongan",
            len(rentang), total, total * 100 / max(1e-9, segments[-1].end),
        )

        tmp = Path(tempfile.mkdtemp(prefix="shortsmith-bahasa-"))
        baru_seg: list[TranscriptSegment] = []
        baru_kata: list[Word] = []
        batas: list[tuple[float, float]] = []

        for n, (a, b) in enumerate(rentang):
            t0, t1 = segments[a].start, segments[b].end
            batas.append((t0, t1))
            log.info("  rentang %d: %.1f-%.1fs", n + 1, t0, t1)

            t = t0
            while t < t1:
                panjang = min(POTONG, t1 - t)
                berkas = tmp / f"p{n:02d}_{int(t):06d}.wav"
                if not _potong_audio(src, t, panjang, berkas):
                    log.warning("  gagal memotong audio di %.1fs — bagian ini dibiarkan", t)
                    t += panjang
                    continue
                try:
                    s2, w2 = ulang(berkas)
                except Exception as exc:  # noqa: BLE001
                    log.warning("  transkrip ulang %.1fs gagal (%s) — dibiarkan", t, exc)
                    t += panjang
                    continue
                # Waktu potongan relatif terhadap potongannya sendiri, jadi
                # digeser kembali ke waktu berkas aslinya.
                for s in s2:
                    baru_seg.append(
                        TranscriptSegment(start=s.start + t, end=s.end + t, text=s.text)
                    )
                for w in w2:
                    baru_kata.append(
                        Word(start=w.start + t, end=w.end + t, text=w.text)
                    )
                berkas.unlink(missing_ok=True)
                t += panjang

        import shutil

        shutil.rmtree(tmp, ignore_errors=True)

        def di_luar(t0: float) -> bool:
            return not any(a <= t0 < b for a, b in batas)

        gabung_seg = [s for s in segments if di_luar(s.start)] + baru_seg
        gabung_kata = [w for w in words if di_luar(w.start)] + baru_kata
        gabung_seg.sort(key=lambda s: s.start)
        gabung_kata.sort(key=lambda w: w.start)

        log.info(
            "transkrip diperbaiki: %d -> %d segmen, %d -> %d kata",
            len(segments), len(gabung_seg), len(words), len(gabung_kata),
        )
        return gabung_seg, gabung_kata
    except Exception:  # noqa: BLE001
        log.warning("perbaikan bahasa dilewati", exc_info=True)
        return segments, words
