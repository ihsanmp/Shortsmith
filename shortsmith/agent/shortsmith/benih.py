"""Benih editor: satu identitas per jenis video, dengan aturan miliknya sendiri.

## Masalah yang diperbaiki

Sebelum ini ada SATU prompt sistem untuk ketiga jenis, dan ia dibuka dengan::

    Kamu adalah editor short video. Tugasmu memilih potongan mana dari sebuah
    rekaman panjang yang layak dirangkai menjadi satu short video vertikal.

Kalimat itu dikirim apa adanya untuk job podcast dan cinematic. Bukan sekadar
tidak rapi — beberapa aturannya berlawanan dengan yang benar untuk jenis itu:

    "Potongan pertama adalah hook: berhenti scroll dalam 2 detik"
        Klip podcast tidak di-scroll. Yang dibutuhkan pembukanya adalah konteks
        secukupnya supaya percakapannya bisa diikuti tanpa menonton episodenya.

    "Caption dibuat otomatis dari transkrip"
        Cinematic TIDAK punya caption sama sekali (lihat jenis.py). Menyebut
        caption di sana memberi model gagasan bahwa ada teks yang akan tampil.

    "satu short video vertikal"
        Rasio podcast dan cinematic TIDAK dipaksa, dan contoh yang diukur
        pengguna 16:9 lanskap.

Jadi untuk dua dari tiga jenis, model bekerja dengan sebagian arahan yang salah.

## Bentuknya: inti bersama + aturan milik sendiri

Aturan yang benar untuk SEMUA jenis ditulis sekali di `INTI`. Yang berbeda per
jenis ditulis di benihnya masing-masing, dan tidak ada benih yang membawa aturan
benih lain. Itu arti "kemampuannya tidak tumpang tindih": bukan tiga salinan
prompt yang saling menimpa, melainkan satu inti yang tidak diperdebatkan plus
satu lapis yang memang khas.

Menambah jenis baru berarti menambah satu entri di sini — bukan menambah `if`
di tengah prompt yang sudah dipakai jenis lain.

## Soal penghematan token: yang diukur, bukan yang diharapkan

Diukur pada job podcast nyata (rekaman 3.303 detik), satu panggilan editor::

    transkrip + peta video   19.304 token   96,2%
    prompt sistem               332 token    1,7%
    skema JSON                  206 token    1,0%
    profil konsep + fokus       111 token    0,6%

Prompt sistemnya 1,7%. Memecahnya per jenis membuat tiap benih lebih pendek
daripada prompt gabungan yang lama, tapi selisihnya puluhan token — itu bukan
penghematan yang berarti, dan mengklaimnya sebagai penghematan akan menyesatkan.

Yang benar-benar mahal adalah transkrip, dan benih inilah tempat keputusan itu
dibuat per jenis: `sertakan_jeda` sudah memakainya. Kalau nanti sebuah jenis
terbukti tidak membutuhkan transkrip verbatim, keputusan itu ditulis di sini
juga — di satu tempat, per jenis, bukan disebar sebagai percabangan.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .identitas import OPUS

log = logging.getLogger(__name__)

# Aturan yang benar untuk SETIAP jenis, tanpa kecuali.
#
# Yang boleh masuk ke sini hanya aturan yang kalau dilanggar akan merusak hasil
# di jenis mana pun — bentuk keluaran, kejujuran timestamp, dan batas wewenang.
# Selera penyuntingan TIDAK masuk sini; itu milik benih.
INTI: tuple[str, ...] = (
    "Suara HANYA boleh diambil dari VIDEO 0. Selalu isi `sumber: 0`. Video lain "
    "adalah pustaka klip yang cuma dipakai gambarnya, tidak bersuara, dan tidak "
    "punya transkrip.",
    "Kamu HANYA memilih rentang waktu. Jangan menulis caption, jangan mengarang "
    "narasi, jangan mengusulkan efek.",
    "Setiap rentang harus jatuh di dalam durasi rekaman dan diambil dari "
    "transkrip yang diberikan. Jangan pernah mengarang timestamp.",
    "Urutan potongan di keluaranmu adalah urutan tayang. Ia tidak harus urut "
    "kronologis terhadap rekaman aslinya.",
    "`alasan` ditulis singkat dalam Bahasa Indonesia, untuk keperluan penelusuran.",
)


@dataclass(frozen=True)
class Benih:
    """Satu jenis video: siapa editornya, dan apa yang khas untuknya."""

    jenis: str
    identitas: str
    model: str
    peran: str
    aturan: tuple[str, ...] = ()

    # Daftar jeda hening ikut dikirim atau tidak. Gunanya cuma satu: memilih
    # titik potong yang tidak memenggal kata. Jenis yang potongannya tidak
    # ditentukan ucapan tidak membutuhkannya.
    sertakan_jeda: bool = True

    def sistem(self) -> str:
        """Prompt sistem lengkap untuk jenis ini."""
        baris = [self.peran, "", "Aturan kerja:"]
        baris += [f"- {a}" for a in (*INTI, *self.aturan)]
        return "\n".join(baris)


_DAFTAR: tuple[Benih, ...] = (
    Benih(
        jenis="short",
        identitas="editor-short",
        model=OPUS,
        peran=(
            "Kamu editor short video vertikal. Tugasmu memilih potongan mana "
            "dari sebuah rekaman panjang yang layak dirangkai jadi satu short."
        ),
        aturan=(
            # Hook hanya masuk akal di tempat yang penontonnya sedang scroll.
            "Potongan pertama adalah hook: ia harus berdiri sendiri dan membuat "
            "orang berhenti scroll dalam 2 detik pertama.",
            "Hasil akhirnya satu topik utuh. Jangan menjahit dua bahasan berbeda "
            "hanya karena keduanya sama-sama kuat — pilih satu benang, lalu "
            "ikuti sampai selesai.",
            "Potong di jeda hening bila memungkinkan, bukan di tengah kata.",
            "Caption dibakar otomatis dari transkrip, jadi yang terpilih akan "
            "ikut terbaca. Pilih kalimat yang utuh, bukan potongan kalimat.",
            "`zoom` adalah punch-in halus (1.0 = tanpa zoom, 1.15 = sedikit "
            "mendekat). Gunakan sesekali untuk variasi, jangan di setiap potongan.",
        ),
    ),
    Benih(
        jenis="podcast",
        identitas="editor-podcast",
        model=OPUS,
        peran=(
            "Kamu editor klip podcast. Tugasmu memotong satu bagian dari "
            "percakapan panjang menjadi klip yang utuh dan bisa dimengerti "
            "sendirian, tanpa menonton episode lengkapnya."
        ),
        aturan=(
            # Bedanya yang paling penting dengan short. Klip podcast tidak
            # bersaing melawan jempol yang sedang scroll; ia bersaing melawan
            # kebingungan. Pembuka yang memaksakan kejutan tanpa konteks
            # menghasilkan klip yang menarik selama dua detik lalu tidak
            # dimengerti selama sisanya.
            "Pembukanya harus memberi konteks secukupnya supaya percakapannya "
            "bisa diikuti. Jangan membuka di tengah jawaban atas pertanyaan "
            "yang tidak ikut terdengar.",
            "Pertanyaan dan jawabannya adalah satu kesatuan. Kalau mengambil "
            "jawaban, ambil juga pertanyaannya — kecuali jawabannya memang "
            "berdiri sendiri.",
            "Ambil SEDIKIT rentang yang panjang dan utuh, bukan banyak rentang "
            "pendek. Tiap sambungan terdengar sebagai patahan di tengah "
            "percakapan, dan percakapan yang tersendat terdengar dipotong-potong.",
            "Jangan memotong di tengah argumen yang sedang dibangun. Kalau "
            "pembicara sedang menuju satu kesimpulan, bawa sampai kesimpulannya.",
            "Caption dibakar otomatis dari transkrip.",
            "`zoom` adalah punch-in halus (1.0 = tanpa zoom, 1.15 = sedikit "
            "mendekat). Gunakan sesekali, jangan di setiap potongan.",
        ),
    ),
    Benih(
        jenis="cinematic",
        identitas="editor-cinematic",
        model=OPUS,
        peran=(
            "Kamu editor video cinematic. Tugasmu memilih bagian mana dari "
            "rekaman yang layak berdiri sebagai rangkaian gambar — yang ditonton, "
            "bukan yang dibaca."
        ),
        aturan=(
            # Cinematic tidak punya caption sama sekali (jenis.py). Aturan
            # bawaan yang menyebut caption memberi model gagasan bahwa ada teks
            # yang akan tampil, dan ia mulai memilih demi kalimat yang bagus
            # dibaca alih-alih gambar yang bagus ditonton.
            "TIDAK ada subtitle di jenis ini. Apa pun yang terpilih tidak akan "
            "pernah muncul sebagai teks, jadi jangan memilih sebuah rentang "
            "karena kalimatnya bagus dibaca.",
            "Yang dijual adalah gambar dan suasananya. Pilih bagian yang kuat "
            "ditonton; ucapan di dalamnya adalah pengiring, bukan alasannya.",
            # Ditulis sebagai pernyataan positif, bukan sebagai penyangkalan
            # atas "hook" dan "scroll".
            #
            # Menyangkal sesuatu tetap memperkenalkannya. Kalau prompt ini
            # berkata "tidak perlu hook", model sudah terlanjur memikirkan hook
            # dan sisanya jadi tawar-menawar dengan gagasan yang tidak pernah
            # relevan di sini. Yang dibutuhkan bukan larangan, melainkan tahu
            # bagaimana pembuka yang benar untuk jenis ini.
            "Video ini ditonton dengan sengaja, dari awal. Pembukanya boleh "
            "membangun suasana pelan-pelan sebelum sampai ke bagian terkuatnya.",
            "Ritmenya datang dari konsep, bukan dari isi kalimat. Ikuti panjang "
            "shot yang diukur dari video contoh.",
        ),
        # Jeda hening gunanya menghindari kata yang terpenggal. Di sini tidak ada
        # teks yang terbaca dan ucapannya bukan alasan sebuah rentang dipilih,
        # jadi daftarnya tidak dipakai untuk apa pun.
        sertakan_jeda=False,
    ),
)

BENIH: dict[str, Benih] = {b.jenis: b for b in _DAFTAR}


def benih(jenis: str) -> Benih:
    """Benih untuk jenis ini. Jatuh ke short kalau namanya tidak dikenal.

    Jatuh ke short, dan BUKAN melempar: jenis datang dari kolom di web, dan
    nilai yang tidak dikenal di sana tidak boleh menggagalkan render yang
    bahannya sudah lengkap. Sama seperti `terapkan_jenis` di jenis.py, dan
    kejatuhannya dicatat supaya tidak diam-diam.
    """
    b = BENIH.get(jenis)
    if b is None:
        log.warning(
            "jenis video '%s' tidak punya benih editor — memakai benih short", jenis
        )
        return BENIH["short"]
    return b
