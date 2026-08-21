"""Caption diturunkan, bukan dikarang.

LLM tidak pernah menulis caption. Teks dan waktunya dipetakan langsung dari
timestamp per kata Whisper melalui EDL, sehingga:

  - tidak ada kata yang muncul padahal tidak diucapkan
  - waktunya presisi sampai level kata, bukan tebakan
  - nol biaya token

Rumus pemetaan sumber -> output:

    t_output = (t_sumber - cut.in) + offset_kumulatif(cut)
"""

from __future__ import annotations

import re

import logging

from .models import Caption, CaptionStyle, Cut, Word

log = logging.getLogger(__name__)


# Caption dimajukan sedikit dari timestamp Whisper.
#
# Bukan angka selera: diukur pada satu render nyata, caption tertinggal median
# 103 ms di belakang onset suara. Penyebabnya sama dengan kenapa konsonan awal
# terpotong — Whisper menaruh `word.start` DI DALAM kata, bukan di awal
# bunyinya. Caption mewarisi bias yang sama.
#
# Memajukannya juga sejalan dengan praktik subtitle pada umumnya: teks muncul
# sesaat sebelum diucapkan, bukan sesudah.
LEAD = 0.10


# Berapa bagian sebuah kata harus terdengar sebelum ia layak diberi caption.
# Lihat alasan pemilihan angkanya di dalam derive_captions().
AMBANG_TERDENGAR = 0.6


def derive_captions(
    cuts: list[Cut],
    words: list[Word] | dict[int, list[Word]],
    style: CaptionStyle,
) -> list[Caption]:
    """Petakan kata-kata dari waktu sumber ke waktu output timeline.

    `words` boleh berupa satu daftar (satu video mentah) atau dict
    {nomor_video: daftar_kata} kalau video mentahnya lebih dari satu. Tiap
    potongan hanya mengambil kata dari video ASALNYA — kalau tidak, kalimat dari
    video lain akan bocor ke caption dan tidak ada yang mengucapkannya.
    """
    per_sumber: dict[int, list[Word]] = (
        words if isinstance(words, dict) else {0: words}
    )
    if not style.ada or not any(per_sumber.values()):
        return []

    max_kata = 1 if style.gaya == "kata-per-kata" else max(1, style.max_kata)
    captions: list[Caption] = []
    offset = 0.0

    for cut in cuts:
        # Kata yang jatuh di dalam rentang potongan ini, dari video asalnya saja.
        sumber_words = per_sumber.get(cut.sumber, [])

        # Syaratnya SEBERAPA BANYAK kata itu terdengar, bukan apakah ia utuh.
        #
        # Aturan sebelumnya menuntut kata berada seluruhnya di dalam potongan.
        # Itu benar untuk kata yang terbelah di UJUNG potongan — hanya pangkalnya
        # yang terdengar, dan menampilkannya membuat penonton melihat kata yang
        # tidak ia dengar. Tapi aturan yang sama ikut membuang kata yang terbelah
        # di AWAL potongan, padahal di sana justru sebagian besarnya terdengar.
        #
        # Terukur pada satu render: 'banyak' 68% terdengar dan 'lu' 70%, dua-duanya
        # hilang dari caption meski jelas terdengar; sementara 'lu' 30% dan
        # 'contoh,' 28% memang pantas disembunyikan. Ambang 60% memisahkan
        # keduanya dengan jarak lebar, bukan menebak di tengah-tengah.
        inside = []
        for w in sumber_words:
            terdengar = min(w.end, cut.out + 0.02) - max(w.start, cut.in_)
            panjang = w.end - w.start
            if panjang <= 0 or terdengar <= 0:
                continue
            if terdengar / panjang >= AMBANG_TERDENGAR:
                inside.append(w)

        for i in range(0, len(inside), max_kata):
            chunk = inside[i : i + max_kata]
            # Dijepit ke dalam potongan di KEDUA ujungnya. Kata yang pangkalnya
            # berada sebelum potongan ini dimulai tidak boleh menghasilkan waktu
            # negatif, dan durasinya harus sepanjang yang benar-benar terdengar.
            start_src = max(chunk[0].start, cut.in_)
            end_src = min(chunk[-1].end, cut.out)
            if end_src <= start_src:
                continue

            # Lead dipotong di batas potongan: caption tidak boleh muncul
            # sebelum potongannya sendiri dimulai.
            t = max(offset, (start_src - cut.in_) + offset - LEAD)
            durasi = end_src - start_src
            text = _seragamkan(" ".join(w.text for w in chunk).strip())
            if style.huruf_besar:
                text = text.upper()
            if text:
                captions.append(Caption(t=round(t, 3), durasi=round(durasi, 3), text=text))

        offset += cut.durasi

    # Rapatkan caption yang tumpang tindih agar tidak dua baris muncul bersamaan.
    for a, b in zip(captions, captions[1:]):
        if a.t + a.durasi > b.t:
            a.durasi = max(0.08, round(b.t - a.t, 3))

    total_kata = sum(len(w) for w in per_sumber.values())
    log.info("caption diturunkan: %d potongan dari %d kata", len(captions), total_kata)
    return captions


# --------------------------------------------------------------------------
# Penulisan file ASS
# --------------------------------------------------------------------------

# Ejaan yang selalu diseragamkan sebelum masuk caption. Whisper menuliskan
# ucapan apa adanya dan tidak konsisten untuk kata slang yang punya beberapa
# ejaan; yang tampil di layar harus satu bentuk saja.
EJAAN: dict[str, str] = {
    "gue": "gua",
    "gw": "gua",
    "gwa": "gua",
    # Salah dengar Whisper yang sudah terlihat di hasil nyata. Daftar ini hanya
    # menambal kasus yang SUDAH ketahuan — ia tidak menolong untuk kesalahan
    # baru, dan itu batas yang harus disadari saat memakainya.
    "lakuan": "lakukan",
    "lakuannya": "lakukannya",
    "ibaratek": "ibaratnya",
}

# Simbol tidak pernah terbaca sebagai kata di layar. Caption dibaca sambil
# lalu, dan "%" atau "1-3" memaksa penonton menerjemahkannya sendiri di kepala.
SATUAN: dict[str, str] = {
    "%": "persen",
    "$": "dolar",
    "&": "dan",
    "+": "plus",
    "=": "sama dengan",
}

ANGKA = [
    "nol", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh",
    "delapan", "sembilan", "sepuluh", "sebelas",
]


def _eja_angka(n: str) -> str:
    """Angka kecil dieja; angka besar dibiarkan.

    Batasnya sengaja rendah. "dua belas" masih enak dibaca, tapi "seratus dua
    puluh tujuh ribu" jauh lebih lambat dicerna daripada "127.000" — mengeja
    semuanya justru merusak hal yang mau diperbaiki.
    """
    try:
        v = int(n)
    except ValueError:
        return n
    return ANGKA[v] if 0 <= v < len(ANGKA) else n


def _eja_simbol(text: str) -> str:
    """Ubah simbol dan rentang angka jadi kata yang bisa langsung dibaca.

        "1-3"  -> "satu sampai tiga"
        "50%"  -> "50 persen"
        "3-5%" -> "tiga sampai lima persen"

    Dikerjakan sebelum penyeragaman ejaan supaya hasil pengejaan ikut melewati
    aturan ejaan juga.
    """
    # Rentang lebih dulu: "1-3" harus jadi satu frasa, bukan dua angka terpisah
    # yang tanda hubungnya hilang.
    text = re.sub(
        r"(?<![0-9])([0-9]+)\s*[-–—]\s*([0-9]+)(?![0-9])",
        lambda m: f"{_eja_angka(m.group(1))} sampai {_eja_angka(m.group(2))}",
        text,
    )
    # Simbol yang menempel di angka diberi spasi supaya terbaca sebagai kata.
    for sym, kata in SATUAN.items():
        text = text.replace(sym, " " + kata)
    return re.sub(r"\s{2,}", " ", text).strip()


def _seragamkan(text: str) -> str:
    """Ganti kata per kata, bukan substring.

    Penggantian substring akan merusak kata lain yang kebetulan memuatnya —
    "gueranteed" atau nama orang — dan kerusakan itu baru ketahuan setelah
    videonya jadi.
    """
    text = _eja_simbol(text)
    keluar: list[str] = []
    for potongan in text.split(" "):
        inti = potongan.strip(".,!?;:\"'()")
        hias_kiri = potongan[: len(potongan) - len(potongan.lstrip(".,!?;:\"'()"))]
        hias_kanan = potongan[len(potongan.rstrip(".,!?;:\"'()")) :]
        ganti = EJAAN.get(inti.lower())
        if ganti is None:
            keluar.append(potongan)
        else:
            # Pertahankan huruf besar di awal kalau memang aslinya begitu.
            if inti[:1].isupper():
                ganti = ganti.capitalize()
            keluar.append(hias_kiri + ganti + hias_kanan)
    return " ".join(keluar)


_ALIGNMENT = {"tengah-bawah": 2, "tengah": 5, "atas": 8}
_MARGIN_V = {"tengah-bawah": 320, "tengah": 0, "atas": 220}


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    jam, sisa = divmod(seconds, 3600)
    menit, detik = divmod(sisa, 60)
    return f"{int(jam)}:{int(menit):02d}:{detik:05.2f}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", " ")


def write_ass(
    captions: list[Caption], style: CaptionStyle, path, *, width: int = 1080, height: int = 1920
) -> None:
    """Tulis file .ass yang siap dibakar oleh filter `ass` ffmpeg."""
    alignment = _ALIGNMENT.get(style.posisi, 2)
    margin_v = _MARGIN_V.get(style.posisi, 320)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.font},{style.ukuran},{style.warna},&H000000FF,{style.outline_warna},&H80000000,-1,0,0,0,100,100,0,0,1,{style.outline},1,{alignment},80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [
        f"Dialogue: 0,{_ass_time(c.t)},{_ass_time(c.t + c.durasi)},Default,,0,0,0,,{_escape(c.text)}"
        for c in captions
    ]

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header)
        fh.write("\n".join(lines))
        fh.write("\n")
