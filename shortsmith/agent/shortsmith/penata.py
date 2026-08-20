"""Penata: memilih klip mana untuk slot mana, berdasarkan apa yang diucapkan.

## Yang digantikan

Penyusun sebelumnya memakai model "tumpukan kartu": semua klip dikocok,
dibagikan satu per slot, dan tidak ada yang muncul lagi sampai sisanya habis.
Itu memberi jarak maksimum antar pengulangan, dan itu memang benar — tapi ia
buta terhadap isi. Kalimat tentang orang yang selalu punya alasan bisa jatuh di
atas shot mobil mewah, dan tidak ada apa pun di dalam sistem yang tahu itu salah.

Di sini pilihannya dibuat dengan melihat DUA hal sekaligus: kata-kata yang
sedang terdengar di slot itu, dan label isi tiap klip dari pelabel.py.

## Kenapa tumpukan kartu tetap dipertahankan sebagai cadangan

Model bisa gagal, kehabisan waktu, mengembalikan slot yang tidak lengkap, atau
memilih klip yang sama dua kali. Semua itu ditangani dengan jatuh kembali ke
pilihan mekanis untuk slot yang bermasalah SAJA — bukan membatalkan seluruh
penataan, dan bukan menggagalkan render. Gambar yang kurang nyambung jauh lebih
ringan daripada tidak ada video sama sekali.

## Kenapa Sonnet, bukan Opus

Keputusan beratnya sudah diambil editor: potongan suara mana yang dipakai dan
urutannya. Yang tersisa di sini mencocokkan gambar ke kalimat yang sudah
ditetapkan, dengan pustaka tertutup dan jumlah slot yang tetap — jauh lebih
terkekang. Lihat identitas.py.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess

from .identitas import model_untuk
from .models import Adegan, PlannedCut, Word

log = logging.getLogger(__name__)

BATAS_DETIK = 240

# Pustaka yang lebih besar dari ini dipangkas sebelum dikirim. Bukan soal biaya:
# daftar ratusan baris membuat model mulai memilih asal dari bagian awal daftar,
# dan slot-slot terakhir kebagian pilihan yang makin buruk.
MAKS_PUSTAKA = 120


class PenataError(RuntimeError):
    pass


def _sumber_pada(t: float, cuts: list[PlannedCut]) -> float | None:
    jalan = 0.0
    for c in cuts:
        if jalan <= t < jalan + c.durasi:
            return c.in_ + (t - jalan)
        jalan += c.durasi
    return None


def ucapan_per_slot(
    rentang: list[tuple[float, float]], cuts: list[PlannedCut], kata: list[Word]
) -> list[str]:
    """Kata-kata yang terdengar selama tiap slot, dalam urutan timeline.

    Slot berada di garis waktu HASIL, sedangkan timestamp kata berada di garis
    waktu REKAMAN ASLI. Keduanya tidak sama karena potongan suara diambil dari
    tempat yang berjauhan lalu disambung, jadi tiap slot harus dipetakan balik
    lewat daftar potongan.
    """
    hasil: list[str] = []
    for mulai, panjang in rentang:
        awal = _sumber_pada(mulai, cuts)
        akhir = _sumber_pada(mulai + panjang - 0.001, cuts)
        if awal is None or akhir is None or akhir < awal:
            hasil.append("")
            continue
        teks = [w.text.strip() for w in kata if awal <= w.start < akhir]
        hasil.append(" ".join(teks).strip())
    return hasil


def _minta_penataan(
    ucapan: list[str],
    pustaka: list[str],
    panjang: list[float],
    durasi_klip: list[float],
    tepi: float,
) -> dict[int, int]:
    claude = shutil.which("claude")
    if not claude:
        raise PenataError("Perintah `claude` tidak ada di PATH.")

    # Tiap slot membawa daftar klip yang BOLEH dipakai untuknya.
    #
    # Sebelumnya durasi hanya ditulis di sebelah tiap klip dan model diminta
    # menghitung sendiri. Terukur di satu render: 8 dari 16 jawaban ditolak
    # karena klipnya terlalu pendek. Bukan karena modelnya ceroboh — pustaka
    # bahan ini bermedian 1,6 detik, sehingga untuk slot 2,8 detik hanya 15%
    # klip yang layak, dan yang 85% itu tidak ditandai apa pun. Menyaring di
    # sini mengubah tugasnya dari menebak-lalu-ditolak jadi memilih dari yang sah.
    baris: list[str] = []
    for i, (u, p) in enumerate(zip(ucapan, panjang), start=1):
        layak = [j for j, d in enumerate(durasi_klip, start=1) if d >= p + tepi]
        if len(layak) == len(durasi_klip):
            boleh = "semua klip"
        elif layak:
            boleh = ", ".join(str(j) for j in layak)
        else:
            boleh = "(tidak ada yang cukup panjang — pilih yang terpanjang)"
        teks = f'"{u}"' if u else "(tidak ada kata)"
        baris.append(f"Slot {i} ({p:.1f}s) {teks}\n    boleh pakai: {boleh}")
    baris_slot = "\n".join(baris)
    baris_klip = "\n".join(f"[{i}] {l}" for i, l in enumerate(pustaka, start=1))

    prompt = (
        "Kamu editor video shorts. Jalur suara sudah final; tugasmu memilih "
        "gambar yang tampil di atasnya.\n\n"
        "Untuk tiap slot, pilih SATU klip dari pustaka yang paling mendukung "
        "kata-kata yang terdengar saat itu.\n\n"
        "Pedoman:\n"
        "- Gambar boleh mendukung secara harfiah maupun kiasan. Kalimat tentang "
        "kerja keras cocok dengan shot orang bekerja larut, bukan hanya kata yang sama.\n"
        "- JANGAN memakai klip yang sama dua kali.\n"
        "- WAJIB memilih dari daftar 'boleh pakai' milik slot itu. Klip di luar "
        "daftar tersebut lebih pendek dari slotnya, sehingga gambarnya akan "
        "menyeberang ke adegan lain di tengah slot.\n"
        "- Slot bersebelahan sebaiknya tidak memakai gambar yang nyaris sama.\n"
        "- Kalau tidak ada yang benar-benar cocok, pilih yang paling netral "
        "daripada yang bertentangan dengan kalimatnya.\n\n"
        f"UCAPAN PER SLOT:\n{baris_slot}\n\n"
        f"PUSTAKA KLIP:\n{baris_klip}\n\n"
        f'Balas HANYA JSON: {{"1": nomor_klip, "2": nomor_klip, ...}} '
        f"untuk seluruh {len(ucapan)} slot."
    )

    proc = subprocess.run(
        [
            claude, "-p",
            "--output-format", "json",
            "--model", model_untuk("penata"),
        ],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=BATAS_DETIK,
    )
    if proc.returncode != 0:
        raise PenataError(f"`claude -p` gagal (exit {proc.returncode}): {proc.stderr[-300:]}")

    teks = (json.loads(proc.stdout).get("result") or "")
    awal, akhir = teks.find("{"), teks.rfind("}")
    if awal < 0 or akhir < 0:
        raise PenataError(f"Keluaran penata tidak mengandung JSON: {teks[:200]}")

    mentah = json.loads(teks[awal : akhir + 1])
    return {int(k): int(v) for k, v in mentah.items()}


def tata(
    rentang: list[tuple[float, float]],
    adegan: list[Adegan],
    cuts: list[PlannedCut],
    kata: list[Word],
    *,
    tepi: float = 0.0,
) -> dict[int, int]:
    """Petakan indeks slot -> indeks adegan. Slot yang tidak terpetakan diserahkan
    kembali ke penyusun mekanis oleh pemanggil.

    Kembalikan dict kosong kalau penataan tidak bisa dilakukan sama sekali —
    itu bukan error, hanya berarti hasilnya sama seperti sebelum fitur ini ada.
    """
    berlabel = [(i, a) for i, a in enumerate(adegan) if a.label]
    if not berlabel:
        log.info("penata: tidak ada adegan berlabel — memakai penyusun mekanis")
        return {}
    if not kata:
        log.info("penata: transkrip kosong — memakai penyusun mekanis")
        return {}

    if len(berlabel) > MAKS_PUSTAKA:
        log.info("penata: pustaka dipangkas dari %d ke %d klip", len(berlabel), MAKS_PUSTAKA)
        berlabel = berlabel[:MAKS_PUSTAKA]

    ucapan = ucapan_per_slot(rentang, cuts, kata)
    if not any(ucapan):
        log.info("penata: tidak ada kata yang jatuh di slot mana pun — penyusun mekanis")
        return {}

    try:
        jawab = _minta_penataan(
            ucapan,
            [f"{a.label} [{a.durasi:.1f}s]" for _, a in berlabel],
            [p for _, p in rentang],
            [a.durasi for _, a in berlabel],
            tepi,
        )
    except (PenataError, json.JSONDecodeError, subprocess.TimeoutExpired, ValueError) as exc:
        log.warning("penata gagal (%s) — memakai penyusun mekanis", exc)
        return {}

    # Divalidasi ketat: nomor di luar jangkauan dan pengulangan dibuang, bukan
    # dipaksakan. Slot yang gugur di sini ditangani penyusun mekanis, jadi
    # jawaban yang setengah benar tetap memberi manfaat sebagian.
    hasil: dict[int, int] = {}
    terpakai: set[int] = set()
    ditolak = 0
    for slot_1, klip_1 in sorted(jawab.items()):
        slot = slot_1 - 1
        if not (0 <= slot < len(rentang)) or not (1 <= klip_1 <= len(berlabel)):
            ditolak += 1
            continue
        idx = berlabel[klip_1 - 1][0]
        if idx in terpakai:
            ditolak += 1
            continue
        # Penjaga terakhir, dan yang sebenarnya menentukan. Model boleh salah
        # menghitung durasi; kode tidak boleh. Adegan yang lebih pendek dari
        # slotnya akan menyeberang ke adegan berikutnya di tengah slot —
        # satu slot berisi dua gambar tak berhubungan, persis yang dicegah
        # oleh pemecahan adegan.
        if adegan[idx].durasi < rentang[slot][1] + tepi:
            ditolak += 1
            continue
        terpakai.add(idx)
        hasil[slot] = idx

    log.info(
        "penata: %d/%d slot ditata dari makna kalimat%s",
        len(hasil), len(rentang),
        f", {ditolak} jawaban ditolak" if ditolak else "",
    )
    return hasil
