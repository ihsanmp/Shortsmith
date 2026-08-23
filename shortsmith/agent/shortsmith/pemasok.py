"""Jembatan Claude - Veo: mengubah kekurangan bahan jadi klip yang benar-benar ada.

## Pembagian kerjanya

Dua model, dua tugas yang tidak saling menggantikan:

  - **Claude** menulis prompt. Ia yang tahu jenis videonya, gaya konsepnya, dan
    apa yang sudah ada di pustaka — jadi ia yang bisa menyebut gambar apa yang
    KURANG, bukan gambar apa yang bagus secara umum.
  - **Veo** membuat gambarnya.

Keputusan editorial tidak pindah ke mana pun. Potongan mana yang akhirnya
dipakai tetap diputuskan `penata` dari pustaka — klip hasil Veo cuma masuk ke
pustaka itu sebagai kandidat, sama seperti rekaman yang diunggah pengguna.

## Kenapa harus diminta, bukan otomatis

Tiap klip menagih akun Google pengguna. Sesuatu yang mengeluarkan uang tidak
boleh berjalan sebagai efek samping dari menekan "buat video" — pengguna harus
tahu ia sedang membelanjakan sesuatu, dan berapa banyak.

Karena itu `pasok()` selalu dipanggil dari perintah CLI yang eksplisit, dan
`BATAS_SEKALI` membatasi berapa klip yang boleh dibuat dalam satu perintah.
Bahkan kalau nanti dipanggil otomatis, batas itu tetap berlaku.

## Kenapa penambal, bukan pengganti

Untuk short dan podcast, yang dijual adalah orang yang bicara — dan itu tidak
bisa dihasilkan model. Untuk cinematic, bahan asli tetap lebih murah dan
sudah ada di disk. Yang ditambal adalah kekurangan yang bisa dihitung: `penata`
tidak boleh memakai satu klip dua kali, jadi pustaka yang lebih kecil dari
jumlah slot adalah kekurangan yang nyata, bukan perasaan.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from .identitas import model_untuk
from .veo import VeoError, hasilkan, rasio_terdekat

log = logging.getLogger(__name__)

BATAS_DETIK = 180

# Berapa banyak klip yang boleh dibuat dalam SATU perintah.
#
# Bukan batas teknis — batas tagihan. Salah ketik satu angka nol pada perintah
# yang membelanjakan uang tidak boleh berakhir dengan ratusan klip.
BATAS_SEKALI = 12

# Folder tujuan per jenis, mengikuti folder yang sudah ada di dalam `bahan/`.
FOLDER = {
    "short": "Short",
    "cinematic": "Cinematic",
    "podcast": "Podcast",
}

# Arahan gaya per jenis, diturunkan dari contoh yang benar-benar diukur — bukan
# dari bayangan tentang apa arti kata "cinematic".
#
#     CINE rpm.cinema     shot 1,90s   0,35 potongan/detik   67% piksel gelap
#     CINE sdmedia.hk     shot 2,07s   0,50 potongan/detik   82% piksel gelap
#     POD  thecliper554   shot 2,00s   0,26 potongan/detik   subtitle terbakar
GAYA = {
    "short": "gambar terang dan jelas, subjek di tengah, mudah terbaca di layar kecil",
    "cinematic": (
        "eksposur gelap dan berkontras tinggi, gerak kamera lambat dan mantap, "
        "shot panjang yang bernapas"
    ),
    "podcast": "ruangan dengan cahaya hangat, gerak kamera minim, tenang",
}

# Hal yang selalu salah untuk B-roll, apa pun jenisnya.
#
# Teks paling penting: Veo suka menempelkan tulisan ke dalam gambar, dan
# Shortsmith membakar subtitle-nya sendiri di atas gambar itu. Dua lapis teks
# yang tidak saling tahu akan saling menimpa.
NEGATIF = "teks, tulisan, subtitle, watermark, logo, wajah orang terkenal, gambar buram"


class PemasokError(RuntimeError):
    pass


def kekurangan(jumlah_slot: int, jumlah_klip: int) -> int:
    """Berapa klip yang kurang untuk mengisi seluruh slot tanpa mengulang.

    `penata` dilarang memakai satu klip dua kali — gambar yang berulang dalam
    satu video pendek langsung terlihat sebagai kehabisan bahan. Jadi kekurangan
    di sini bukan tebakan kualitas, melainkan selisih yang bisa dihitung.
    """
    return max(0, jumlah_slot - jumlah_klip)


def _tulis_prompt(
    jumlah: int, jenis: str, tema: str, sudah_ada: list[str], durasi: float
) -> list[str]:
    """Minta Claude menuliskan `jumlah` prompt B-roll."""
    claude = shutil.which("claude")
    if not claude:
        raise PemasokError("Perintah `claude` tidak ada di PATH.")

    gaya = GAYA.get(jenis, GAYA["short"])
    daftar = "\n".join(f"- {x}" for x in sudah_ada) if sudah_ada else "(pustaka kosong)"

    prompt = (
        "Kamu menulis prompt untuk model video Veo. Hasilnya dipakai sebagai "
        "B-roll dalam sebuah video yang sedang diedit.\n\n"
        f"JENIS VIDEO: {jenis}\n"
        f"GAYA YANG DIMINTA: {gaya}\n"
        f"TEMA VIDEO: {tema or '(tidak disebutkan)'}\n"
        f"PANJANG TIAP KLIP: sekitar {durasi:.0f} detik\n\n"
        f"SUDAH ADA DI PUSTAKA:\n{daftar}\n\n"
        "Tulis prompt untuk gambar yang BELUM ada di pustaka itu. Kalau pustaka "
        "sudah penuh shot kota malam, jangan menambah shot kota malam lagi.\n\n"
        "Aturan tiap prompt:\n"
        "- Satu adegan saja per prompt. Prompt yang memuat dua adegan membuat "
        "Veo memotong sendiri di tengah, dan potongan itu tidak diketahui editor.\n"
        "- Sebutkan subjek, cahaya, dan gerak kameranya secara konkret.\n"
        "- JANGAN meminta teks, tulisan, atau logo di dalam gambar. Video ini "
        "membakar subtitle-nya sendiri di atas gambar.\n"
        "- JANGAN meminta orang yang bisa dikenali atau tokoh nyata.\n"
        "- Tanpa dialog dan tanpa suara yang perlu dimengerti; gambar ini akan "
        "ditumpuk di atas jalur suara yang sudah ada."
        "- TULIS PROMPTNYA DALAM BAHASA INGGRIS, walau instruksi ini berbahasa "
        "Indonesia. Model videonya jauh lebih andal membaca bahasa Inggris, dan "
        "istilah kamera seperti dolly, push-in, dan rim lighting memang "
        "istilah Inggris.\n\n"
        f'Balas HANYA JSON: {{"prompts": ["...", "..."]}} berisi persis '
        f"{jumlah} prompt."
    )

    proc = subprocess.run(
        [claude, "-p", "--output-format", "json", "--model", model_untuk("pemasok")],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=BATAS_DETIK,
    )
    if proc.returncode != 0:
        raise PemasokError(
            f"`claude -p` gagal (exit {proc.returncode}): {proc.stderr[-300:]}"
        )

    teks = json.loads(proc.stdout).get("result") or ""
    awal, akhir = teks.find("{"), teks.rfind("}")
    if awal < 0 or akhir < 0:
        raise PemasokError(f"Keluaran pemasok tidak mengandung JSON: {teks[:200]}")

    daftar_prompt = json.loads(teks[awal : akhir + 1]).get("prompts") or []
    bersih = [p.strip() for p in daftar_prompt if isinstance(p, str) and p.strip()]
    if not bersih:
        raise PemasokError("Pemasok tidak menghasilkan satu prompt pun.")

    # Kalau modelnya memberi lebih dari yang diminta, kelebihannya DIBUANG di
    # sini — bukan diteruskan ke Veo. Yang diminta pengguna adalah sejumlah itu,
    # dan tiap klip berlebih adalah tagihan yang tidak ia setujui.
    if len(bersih) > jumlah:
        log.warning("pemasok memberi %d prompt, dipangkas ke %d", len(bersih), jumlah)
    return bersih[:jumlah]


def tulis_saja(
    jumlah: int,
    *,
    jenis: str = "cinematic",
    tema: str = "",
    durasi: float = 8,
    sudah_ada: list[str] | None = None,
) -> list[str]:
    """Tulis promptnya saja, tanpa memanggil Veo dan tanpa menagih apa pun.

    ## Kenapa ini ada

    Langganan Gemini konsumen (Plus, Pro, Ultra) TIDAK memberi kuota API — ia
    memberi kuota di aplikasi Gemini dan Google Flow. Dua dompet yang berbeda:
    `pasok()` menagih billing Cloud, sedangkan langganan yang sudah dibayar
    pengguna tidak bisa menyentuh jalur itu sama sekali.

    Yang bisa menjembataninya cuma tangan pengguna: prompt ditempel ke Flow,
    hasilnya diunduh, lalu ditaruh di folder bahan. Berkasnya mp4 biasa, dan
    pipeline ini memang sudah membaca bahan langsung dari disk — tidak ada yang
    perlu diubah untuk menerimanya.

    Bagian Claude-nya tetap berguna utuh: yang mahal dari menulis prompt B-roll
    bukan mengetiknya, melainkan tahu gambar apa yang KURANG dari pustaka.
    """
    return _tulis_prompt(jumlah, jenis, tema, sudah_ada or [], durasi)


def pasok(
    jumlah: int,
    *,
    jenis: str = "cinematic",
    tema: str = "",
    rasio: str = "16:9",
    durasi: float = 8,
    bahan_dir: Path = Path("bahan"),
    sudah_ada: list[str] | None = None,
    resolusi: str = "720p",
) -> list[Path]:
    """Tulis prompt lewat Claude, buat klipnya lewat Veo, simpan ke folder jenis.

    Mengembalikan daftar berkas yang BERHASIL dibuat. Kegagalan satu klip tidak
    membatalkan sisanya: klip yang sudah jadi terlanjur ditagih, jadi membuang
    semuanya karena satu gagal berarti membayar untuk nol hasil.
    """
    if jumlah < 1:
        return []
    if jumlah > BATAS_SEKALI:
        raise PemasokError(
            f"{jumlah} klip melebihi batas sekali jalan ({BATAS_SEKALI}). "
            "Batas ini soal tagihan, bukan kemampuan — jalankan beberapa kali "
            "kalau memang sebanyak itu yang dibutuhkan."
        )

    tujuan = bahan_dir / FOLDER.get(jenis, "B-roll")
    tujuan.mkdir(parents=True, exist_ok=True)

    prompts = _tulis_prompt(jumlah, jenis, tema, sudah_ada or [], durasi)
    log.info("pemasok: %d prompt siap, mulai membuat klip", len(prompts))

    ar = rasio_terdekat(rasio)
    jadi: list[Path] = []
    for i, p in enumerate(prompts, start=1):
        # Nama berurutan yang tidak menimpa apa pun. Angkanya melanjutkan berkas
        # veo yang sudah ada di folder, supaya menjalankan perintah ini dua kali
        # tidak menghapus hasil yang pertama.
        nomor = len(list(tujuan.glob("veo-*.mp4"))) + 1
        berkas = tujuan / f"veo-{nomor:03d}.mp4"
        log.info("pemasok: klip %d/%d -> %s", i, len(prompts), berkas.name)
        try:
            hasilkan(
                p,
                berkas,
                rasio=ar,
                durasi=durasi,
                resolusi=resolusi,
                negatif=NEGATIF,
            )
            jadi.append(berkas)
        except VeoError as exc:
            log.error("pemasok: klip %d gagal — %s", i, exc)

    log.info("pemasok: %d dari %d klip jadi, di %s", len(jadi), len(prompts), tujuan)
    return jadi
