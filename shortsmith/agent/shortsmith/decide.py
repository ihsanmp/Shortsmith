"""Tahap keputusan: peta video + concept profile + brief -> rencana potongan.

LLM hanya mengembalikan rentang waktu dan alasannya. Caption, musik, dan detail
render lain tidak pernah datang dari model — semuanya diturunkan di sisi kita.

Validasi dijalankan SEBELUM menyentuh renderer. Gagal lebih awal jauh lebih murah
daripada gagal di tengah render.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from .config import SETTINGS
from .benih import Benih, benih
from .identitas import model_untuk, sebab_gagal
from .models import Arahan, ConceptProfile, CutPlan, PlannedCut, ProjectMap

log = logging.getLogger(__name__)

# Durasi video contoh TIDAK mengikat durasi hasil.
#
# Angka dari video contoh hanya masuk ke prompt sebagai gambaran gaya. Contoh 1:30
# yang menghasilkan 2:30 itu wajar — materinyalah yang menentukan, bukan panjang
# contohnya.
#
# Karena itu validator tidak lagi membandingkan hasil dengan durasi contoh sama
# sekali. Ia hanya menangkap dua keadaan yang memang menandakan KEGAGALAN, dan
# keduanya diukur terhadap hal yang relevan — bukan terhadap contoh:
DURASI_MINIMUM = 8.0        # absolut: di bawah ini bukan video, model gagal memilih
RASIO_MAKS_SUMBER = 0.85    # terhadap REKAMAN: kalau hampir seluruhnya dipakai,
                            # berarti tidak ada penyuntingan yang terjadi


class DecisionError(RuntimeError):
    pass




def _format_profile(profile: ConceptProfile) -> str:
    baris = [f"Nama konsep: {profile.nama} (versi {profile.versi})"]

    for kunci, stat in profile.metrik.items():
        deskripsi = f"  - {kunci}: rata-rata {stat.mean:g}"
        if stat.std:
            deskripsi += f", deviasi {stat.std:g}"
        baris.append(deskripsi)

    if profile.metrik:
        baris.insert(1, "Metrik gaya editing (diekstrak dari video contoh):")

    asl = profile.metrik.get("avg_shot_length")
    if asl and asl.std:
        rasio = asl.std / max(asl.mean, 1e-6)
        if rasio < 0.25:
            baris.append(
                "  Deviasi panjang shot rendah -> ritme metronomik. Buat durasi antar "
                "potongan relatif seragam."
            )
        elif rasio > 0.6:
            baris.append(
                "  Deviasi panjang shot tinggi -> ritme dinamis. Variasikan durasi "
                "potongan: selipkan potongan sangat pendek di antara yang panjang."
            )

    baris.append(f"Struktur yang diharapkan: {' -> '.join(r.value for r in profile.struktur)}")
    return "\n".join(baris)


def _format_arahan(arahan: Arahan | None) -> str | None:
    """Empat komponen brief, ditulis sebagai syarat — bukan sebagai saran.

    Nadanya sengaja berbeda dari `_format_fokus`. Fokus menyempitkan RUANG
    pilihan ("ambil bagian yang membahas ini"); arahan menetapkan apa yang harus
    ADA di hasilnya. Yang pertama boleh diterjemahkan longgar kalau bahannya
    tidak ideal, yang kedua tidak — pengguna menuliskannya justru karena
    videonya dipakai untuk sesuatu.

    Yang TIDAK dilakukan di sini: menyuruh model mengarang kalimat untuk memenuhi
    komponennya. Semua yang keluar tetap harus berasal dari rekaman. Kalau
    bahannya benar-benar tidak memuat narasinya, yang benar adalah memilih yang
    paling mendekati dan membiarkan kekurangannya terlihat, bukan menambal
    dengan potongan yang tidak mengatakannya.
    """
    if arahan is None or not arahan.terisi():
        return None

    baris = [
        "Empat komponen berikut diisi pengguna dan WAJIB terpenuhi. Ini bukan "
        "bahan pertimbangan; ini syarat hasilnya.",
        "",
    ]

    # Tiap komponen jadi BLOK berlabel, dan isinya diindentasi.
    #
    # Sebelumnya ditulis "- <label>: <nilai>" satu baris. Itu benar untuk nilai
    # sebaris, dan hancur untuk yang sebenarnya dikirim pengguna: narasi mereka
    # berupa daftar berbutir, dan butir-butirnya menyatu dengan daftar
    # komponennya sendiri —
    #
    #     - Narasi yang wajib sampai: - Menunjukkan perjalanan hidup David
    #     - Membuat audience relate
    #     - Fokus kemampuan David di dunia saham
    #     - Kesan yang diinginkan: Edukatif / step-by-step
    #
    # dan "Kesan yang diinginkan" terbaca sebagai butir keempat dari narasinya.
    # Batas antar komponen hilang persis di tempat yang paling mahal.
    for label, nilai in arahan.butir():
        baris.append(f"{label.upper()}:")
        baris += [f"    {b}" for b in nilai.splitlines() if b.strip()]
        baris.append("")
    # Petunjuk hanya untuk komponen yang BENAR-BENAR diisi. Menjelaskan cara
    # memakai "kesan yang diinginkan" kepada pengguna yang mengosongkannya
    # memaksa model mendamaikan aturan dengan bahan yang tidak ada.
    baris += ["", "Cara memakainya:"]
    if arahan.narasi.strip():
        baris.append(
            "- Pilih potongan yang benar-benar MENYAMPAIKAN narasinya. Potongan "
            "yang cuma bersinggungan dengan temanya tidak memenuhi syarat ini."
        )
        # Narasi berbutir banyak adalah bentuk yang biasa dipakai, dan enam
        # butir tidak muat utuh di satu short 45 detik. Tanpa aturan urutan,
        # yang tersisa ditentukan kebetulan — dan butir pertama, yang biasanya
        # paling penting, bisa jadi justru yang terbuang.
        if len([b for b in arahan.narasi.splitlines() if b.strip()]) > 1:
            baris.append(
                "- Narasinya berisi beberapa butir. Usahakan SEMUANYA tersentuh. "
                "Kalau bahannya tidak cukup untuk semua, urutan di atas adalah "
                "urutan kepentingan: butir pertama tidak boleh hilang, butir "
                "terakhir yang pertama dilepas."
            )
    if arahan.kesan.strip():
        baris.append(
            "- Susun urutannya supaya kesan yang diminta itulah yang terbentuk. "
            "Urutan menentukan perasaan sama besarnya dengan isi."
        )
    if arahan.tujuan.strip():
        baris.append(
            "- Tujuan itu yang menentukan potongan mana yang layak masuk saat "
            "dua potongan sama bagusnya. Pilih yang paling melayaninya."
        )
    baris.append(
        "- Semua tetap harus berasal dari rekaman. JANGAN memaksakan potongan "
        "yang tidak mengatakannya hanya supaya komponennya terlihat terpenuhi; "
        "kalau bahannya kurang, ambil yang paling mendekati."
    )
    if arahan.cta.strip():
        baris.append(
            "- Potongan TERAKHIR harus membawa ajakan itu dan diberi role "
            '"cta". Ambil bagian rekaman yang paling dekat dengan ajakan '
            "tersebut; kalau pembicara tidak pernah mengajak secara langsung, "
            "pakai kalimat penutup yang paling mengarah ke sana."
        )
        # CTA-nya boleh bersyarat, dan memang begitu dipakai: "kalau topiknya
        # soal AI, ajak ke workshop; kalau soal crypto, ajak ke komunitas".
        # Tanpa baris ini model bisa memperlakukan seluruh teks syarat itu
        # sebagai satu ajakan harfiah yang harus disebut apa adanya.
        if len(arahan.cta.strip().splitlines()) > 1 or "jika" in arahan.cta.lower():
            baris.append(
                "- Ajakan di atas BERSYARAT. Tentukan dulu klip ini sebenarnya "
                "membahas apa, pilih cabang yang cocok, lalu penuhi cabang ITU "
                "saja. Jangan menggabungkan beberapa cabang, dan jangan "
                "menyebut syaratnya sebagai bagian dari videonya."
            )
    return "\n".join(baris)


# Panjang satu blok transkrip, dalam detik.
#
# Whisper memenggal per frasa, dan hasilnya jauh lebih halus daripada yang
# dibutuhkan siapa pun di sini. Diukur pada rekaman podcast 3.303 detik::
#
#     1.634 segmen, durasi median 1,80 detik, median 5 KATA per segmen
#     isi kalimat     11.459 token   61,7%
#     penanda waktu    7.105 token   38,3%
#
# Penandanya hampir sebesar isinya. Dan ketelitian sehalus itu tidak pernah
# sampai ke hasil: batas potongan yang dipilih model langsung dirapikan
# `rapikan_kata`, `rapikan_batas`, dan `rapikan_energi` ke jeda hening dan titik
# berenergi rendah terdekat. Jadi desimal keduanya dibuang dua kali -- sekali
# oleh perapian, sekali lagi oleh kisi frame.
#
# Delapan detik masih jauh lebih halus daripada potongan terpendek yang masuk
# akal, jadi model tetap bisa menunjuk bagian yang ia maksud.
BLOK_DETIK = 8.0

# Jeda selebar ini memisahkan blok walau blok itu belum penuh. Di sanalah
# pembicara berganti napas atau berganti gagasan, dan menyatukan dua sisi jeda
# panjang jadi satu blok menghapus batas yang justru paling berguna.
BLOK_JEDA = 0.6


def _transkrip(segments) -> list[str]:
    """Transkrip yang sudah dipadatkan jadi blok, satu baris per blok.

    Menggabungkan segmen TIDAK membuang satu kata pun: teksnya disambung apa
    adanya, dan yang hilang cuma penanda waktu di tengah blok -- penanda yang
    ketelitiannya memang tidak pernah dipakai. Lihat BLOK_DETIK untuk ukurannya.
    """
    blok: list[str] = []
    mulai = akhir = None
    isi: list[str] = []

    def tutup() -> None:
        if isi:
            blok.append(f"[{mulai:.1f}-{akhir:.1f}] " + " ".join(isi))

    for seg in segments:
        teks = seg.text.strip()
        if not teks:
            continue
        if mulai is None:
            mulai, akhir, isi = seg.start, seg.end, [teks]
            continue
        if seg.end - mulai > BLOK_DETIK or seg.start - akhir > BLOK_JEDA:
            tutup()
            mulai, akhir, isi = seg.start, seg.end, [teks]
        else:
            akhir = seg.end
            isi.append(teks)
    tutup()
    return blok


def _format_map(
    vmap: ProjectMap, *, max_silences: int = 40, jeda_hening: bool = True
) -> str:
    """Sajikan tiap video terpisah, dengan nomor yang dipakai di field `sumber`.

    Transkrip sengaja TIDAK disambung jadi satu garis waktu. Menyambungnya akan
    menciptakan timestamp semu yang tidak cocok dengan file mana pun saat render,
    dan kesalahannya baru ketahuan setelah video jadi.
    """
    baris: list[str] = []

    utama = vmap.videos[0]
    nama = Path(utama.media.path).name
    baris.append(f"--- VIDEO 0 (SUMBER SUARA) | {nama} | {utama.media.durasi:.1f} detik ---")
    baris.append("TRANSKRIP (format: [mulai-selesai] teks):")
    baris += _transkrip(utama.segments)

    # Daftar jeda hening gunanya cuma satu: memilih titik potong yang tidak
    # memenggal kata. Jenis yang potongannya tidak ditentukan ucapan tidak
    # membutuhkannya, dan benihnya yang memutuskan itu -- lihat benih.py.
    jeda = (
        sorted(utama.silences, key=lambda s: s.durasi, reverse=True)[:max_silences]
        if jeda_hening
        else []
    )
    if jeda:
        baris.append("")
        baris.append("JEDA HENING TERPANJANG (titik potong paling aman):")
        for s in sorted(jeda, key=lambda s: s.start):
            baris.append(f"  {s.start:.2f} - {s.end:.2f} ({s.durasi:.2f}s)")
    baris.append("")

    # Klip B-roll didaftar tanpa transkrip — memang tidak punya. Ia disebut di
    # sini semata supaya model tahu gambarnya akan datang dari tempat lain, dan
    # karena itu tidak perlu memilih potongan hanya karena "gambarnya bagus".
    # Penempatannya dikerjakan tahap berikutnya, bukan di sini.
    klip = vmap.videos[1:]
    if klip:
        total = sum(v.media.durasi for v in klip)
        baris.append(
            f"--- PUSTAKA KLIP: {len(klip)} file, {total:.0f} detik (gambar saja) ---"
        )
        baris.append(
            "Klip-klip ini akan ditumpuk di atas suara pilihanmu oleh tahap "
            "berikutnya. JANGAN memakainya sebagai `sumber` — mereka tidak "
            "bersuara dan tidak punya transkrip. Kamu tidak perlu memikirkan "
            "visual sama sekali: pilih bagian yang paling kuat DIDENGAR."
        )
        baris.append("")

    return "\n".join(baris)


def _format_fokus(brief: str, profile: ConceptProfile) -> str:
    """Satu-satunya arahan manual di seluruh sistem.

    Nilainya datang dari project (kolom "Fokus pembahasan"), dengan konsep
    sebagai cadangan untuk pemakaian lewat CLI. Project menang karena topik
    adalah sifat SATU video, bukan sifat gayanya: konsep dipakai berulang, dan
    topik yang terkunci di sana akan memaksa semua video membahas hal yang sama.

    Kosong bukan keadaan darurat — itu keadaan biasa, dan artinya editor bebas
    memilih bagian terkuat dari rekaman. Dikatakan eksplisit supaya model tidak
    mengarang batasan yang tidak diminta siapa pun.
    """
    fokus = brief.strip() or profile.manual.fokus.strip()
    if not fokus:
        return (
            "(tidak ditentukan) Bebas memilih topik mana pun yang dibahas di "
            "rekaman. Ambil bagian yang paling kuat dan paling utuh."
        )
    # Ditulis tegas: arahan yang setengah-setengah menghasilkan video yang
    # topiknya melenceng pelan-pelan, dan itu baru ketahuan setelah ditonton.
    return "\n".join(
        [
            fokus,
            "Pakai HANYA bagian rekaman yang membahas ini. Kalau tidak ada "
            "bagian yang cukup membahasnya, pakai potongan yang paling "
            "mendekati — jangan mengarang, dan jangan berpindah ke topik lain.",
        ]
    )


def _build_prompt(
    vmap: ProjectMap,
    profile: ConceptProfile,
    brief: str,
    b: Benih,
    *,
    arahan: Arahan | None = None,
    koreksi: str | None = None,
) -> str:
    target = profile.target_duration()
    jumlah_cut = profile.target_cuts()

    bagian = [
        "== KONSEP ==",
        _format_profile(profile),
        "",
        f"== VIDEO MENTAH ({len(vmap.videos)} file) ==",
        _format_map(vmap, jeda_hening=b.sertakan_jeda),
        "",
        "== FOKUS PEMBAHASAN ==",
        _format_fokus(brief, profile),
        "",
    ]

    # Ditaruh SETELAH fokus dan sebelum durasi: ia menyempitkan isi, dan yang
    # menyempitkan isi harus terbaca sebelum yang mengatur panjang.
    teks_arahan = _format_arahan(arahan)
    if teks_arahan:
        bagian += ["== ARAHAN WAJIB ==", teks_arahan, ""]

    bagian += [
        "== DURASI ==",
        f"Video contoh untuk konsep ini rata-rata {target:.0f} detik. Itu GAMBARAN GAYA, "
        f"bukan target yang harus dikejar. Panjang hasil ditentukan oleh materinya: "
        f"kalau bahan bagusnya cukup untuk {target * 1.7:.0f} detik, pakai segitu; "
        f"kalau hanya kuat sampai {target * 0.6:.0f} detik, jangan dipanjangkan dengan "
        f"potongan lemah. Jangan pernah menambah atau membuang potongan hanya demi "
        f"menyamai angka di atas.",
    ]
    # Jumlah potongan SUARA diambil dari penggal suara contoh, bukan dari
    # jumlah pergantian gambarnya.
    #
    # Keduanya sempat tertukar, dan akibatnya besar: satu contoh punya 22
    # pergantian gambar tapi audionya hanya 4 penggal. Model disuruh membuat 21
    # sambungan suara, dan tiap sambungan adalah tempat room tone melompat dan
    # konsonan terpotong — audionya jadi tersendat sepanjang video.
    penggal = profile.target_penggal()
    if penggal:
        bagian.append(
            f"Jumlah potongan suara: sekitar {penggal:.0f}, dan JANGAN jauh lebih banyak. "
            f"Ambil sedikit rentang yang PANJANG dan utuh, bukan banyak rentang pendek. "
            f"Tiap sambungan terdengar sebagai patahan, jadi makin sedikit makin baik."
        )
    elif jumlah_cut:
        bagian.append(f"Perkiraan jumlah potongan: sekitar {jumlah_cut:.0f}.")

    if koreksi:
        bagian += [
            "",
            "== PERBAIKAN ==",
            "Percobaan sebelumnya ditolak validator dengan alasan berikut. "
            "Perbaiki dan kirim ulang:",
            koreksi,
        ]

    return "\n".join(bagian)


# Di atas panjang ini, punch-in dilepas. Lihat alasannya di `_validate`.
ZOOM_MAKS_DETIK = 15.0

# Batas atas zoom yang diturunkan dari pengukuran kerapatan.
#
# Bukan selera: zoom memperkecil jendela crop lalu memperbesarnya ke ukuran
# keluaran, jadi tiap kenaikan membayar ketajaman. Untuk crop 9:16 dari sumber
# 1920x1080::
#
#     zoom 1,00   crop 608x1080   perbesaran 1,78x
#     zoom 1,40   crop 434x771    perbesaran 2,49x
#     zoom 1,60   crop 380x675    perbesaran 2,84x
#
# Dipatok 1,4: di atas itu gambarnya mulai terlihat lunak pada layar penuh,
# dan kemiripan dengan konsep tidak sepadan dengan ketajaman yang hilang.
ZOOM_DARI_KERAPATAN_MAKS = 1.4


def _validate(
    cuts: list[PlannedCut],
    vmap: ProjectMap,
    profile: ConceptProfile,
    arahan: Arahan | None = None,
) -> list[str]:
    """Clamp in-place ke durasi video sumbernya, lalu kembalikan sisa masalah."""
    masalah: list[str] = []

    # Pembanding rasio HARUS video suara saja, bukan vmap.total_durasi. Video
    # ke-2 dan seterusnya adalah pustaka klip yang tidak menyumbang satu detik
    # pun ke audio; ikut menghitungnya membuat penjaga 85% ini menggelembung
    # sampai tak pernah menyala. Tambah 20 klip B-roll dan penjaganya mati.
    durasi_sumber = vmap.videos[0].media.durasi

    dilepas = 0
    for i, cut in enumerate(cuts):
        # Punch-in yang tidak pernah dilepas bukan punch-in.
        #
        # Zoom gunanya menekankan sesuatu, dan penekanan hanya terbaca relatif
        # terhadap sekitarnya. Ditahan selama setengah menit, ia berhenti jadi
        # penekanan dan cuma jadi bingkai yang lebih rapat — dengan ongkos yang
        # terukur::
        #
        #     zoom 1,00   crop 608x1080   piksel sumber 100%   perbesaran 1,78x
        #     zoom 1,10   crop 552x982    piksel sumber  83%   perbesaran 1,96x
        #     zoom 1,15   crop 528x939    piksel sumber  76%   perbesaran 2,04x
        #
        # Jadi seperempat video jadi lebih lunak tanpa imbalan apa pun. Dan
        # karena bingkainya lebih rapat, gerak pelacakan yang sama ikut membesar
        # di keluaran.
        #
        # Batasnya datang dari laporan pengguna, bukan dari angka yang dikarang:
        # pada satu hasil ia mempertanyakan potongan 27 detik berzoom 1,10, dan
        # TIDAK mempertanyakan potongan 12,9 detik berzoom 1,15 di video yang
        # sama. Lima belas detik duduk di antara keduanya.
        if cut.zoom > 1.0 and cut.durasi > ZOOM_MAKS_DETIK:
            cut.zoom = 1.0
            dilepas += 1

        # Audio hanya boleh dari satu video: VIDEO 0. Ini bukan preferensi gaya
        # melainkan bentuk formatnya — satu suara, satu topik, satu alur.
        if cut.sumber != 0:
            masalah.append(
                f"Potongan #{i + 1}: sumber={cut.sumber}. Suara hanya boleh diambil "
                f"dari VIDEO 0. Video lain adalah pustaka klip yang hanya dipakai "
                f"gambarnya, dan transkripnya tidak ada."
            )
            continue

        v = vmap.get(cut.sumber)
        if v is None:
            masalah.append(
                f"Potongan #{i + 1}: sumber={cut.sumber} tidak ada. "
                f"Nomor video yang tersedia: 0 sampai {len(vmap.videos) - 1}."
            )
            continue

        batas = v.media.durasi
        if cut.in_ > batas:
            masalah.append(
                f"Potongan #{i + 1}: in={cut.in_:.2f} melewati durasi VIDEO "
                f"{cut.sumber} ({batas:.2f}s)."
            )
        # Clamp diam-diam untuk penyimpangan kecil di ujung.
        cut.out = min(cut.out, batas)
        if cut.out <= cut.in_:
            masalah.append(
                f"Potongan #{i + 1}: rentang tidak valid setelah clamp "
                f"(in={cut.in_:.2f}, out={cut.out:.2f})."
            )

    total = sum(c.durasi for c in cuts if c.out > c.in_)

    if total < DURASI_MINIMUM:
        masalah.append(
            f"Total durasi hanya {total:.1f} detik. Itu bukan video — kemungkinan besar "
            f"model gagal menemukan bagian yang layak dipakai. Periksa lagi transkripnya."
        )
    elif total > durasi_sumber * RASIO_MAKS_SUMBER:
        masalah.append(
            f"Total durasi {total:.1f}s memakai {total / durasi_sumber * 100:.0f}% dari "
            f"rekaman aslinya ({durasi_sumber:.0f}s). Praktis tidak ada yang dipotong — "
            f"pilih hanya bagian yang benar-benar kuat."
        )

    # Durasi contoh dicatat sebagai pembanding saja, tidak pernah menolak.
    contoh = profile.target_duration()
    if contoh > 0:
        log.info(
            "durasi hasil %.0fs (video contoh %.0fs, %.0f%%) — diterima, "
            "durasi contoh hanya gambaran gaya",
            total, contoh, total / contoh * 100,
        )

    if not any(c.role.value == "hook" for c in cuts):
        masalah.append("Tidak ada potongan dengan role 'hook'.")

    # CTA yang diminta pengguna diperiksa di sini, bukan cuma dititipkan ke
    # prompt.
    #
    # Dari empat komponen arahan, hanya ini yang punya bentuk yang bisa
    # diperiksa mesin: ajakan datang di AKHIR. Narasi, kesan, dan tujuan cuma
    # bisa dinilai dengan membaca, dan pemeriksa yang menebak-nebak keduanya
    # akan menolak rencana yang benar sama seringnya dengan yang salah.
    #
    # Memeriksa yang satu ini tetap berharga: ia justru komponen yang paling
    # mudah terlupakan, karena potongan terkuat hampir tidak pernah kebetulan
    # berupa ajakan.
    if arahan is not None and arahan.cta.strip() and cuts:
        if cuts[-1].role.value != "cta":
            masalah.append(
                "Pengguna meminta CTA di akhir video, tapi potongan terakhir "
                f"berrole '{cuts[-1].role.value}'. Potongan penutup harus membawa "
                f"ajakan berikut dan diberi role 'cta':\n{arahan.cta.strip()[:400]}"
            )

    if dilepas:
        log.info(
            "punch-in dilepas dari %d potongan yang lebih panjang dari %.0f detik",
            dilepas, ZOOM_MAKS_DETIK,
        )

    return masalah


# --------------------------------------------------------------------------
# Backend 1 — `claude -p` (Claude Code headless)
#
# Memakai kredensial langganan Claude yang sudah ada di mesin, jadi tidak perlu
# API key maupun kredit. Konsekuensinya tidak ada structured output yang dijamin
# server, jadi bentuk JSON diminta lewat prompt lalu diverifikasi pydantic.
# --------------------------------------------------------------------------

SKEMA_JSON = """\

== FORMAT KELUARAN ==
Balas HANYA dengan satu objek JSON, tanpa penjelasan apa pun sebelum atau
sesudahnya, tanpa pagar kode markdown. Bentuknya persis:

{
  "cuts": [
    {
      "sumber": 0,
      "in": 132.4,
      "out": 138.9,
      "role": "hook",
      "alasan": "pertanyaan pembuka yang memancing rasa penasaran",
      "zoom": 1.0
    }
  ],
  "ringkasan": "satu kalimat: cerita apa yang dirangkai potongan ini"
}

Aturan field:
- "sumber" adalah nomor VIDEO (lihat daftar di bagian VIDEO MENTAH), mulai dari 0
- "in" dan "out" dalam detik, RELATIF terhadap video itu sendiri (angka desimal), harus ada di dalam durasi rekaman
- "out" selalu lebih besar dari "in"
- "role" salah satu dari: hook, konteks, isi, cta
- "zoom" antara 1.0 dan 1.6; 1.0 berarti tanpa punch-in
- Urutan di dalam "cuts" adalah urutan tayang
"""


def _extract_json(teks: str) -> dict:
    """Ambil objek JSON dari keluaran model yang mungkin diselingi teks lain."""
    bersih = teks.strip()

    # Buang pagar kode markdown kalau model tetap memakainya.
    if bersih.startswith("```"):
        baris = bersih.splitlines()
        bersih = "\n".join(b for b in baris if not b.strip().startswith("```"))

    awal = bersih.find("{")
    akhir = bersih.rfind("}")
    if awal == -1 or akhir <= awal:
        raise DecisionError(
            f"Keluaran model tidak mengandung objek JSON:\n{teks[:400]}"
        )

    try:
        return json.loads(bersih[awal : akhir + 1])
    except json.JSONDecodeError as exc:
        raise DecisionError(f"JSON dari model tidak bisa dibaca: {exc}") from exc


def _call_via_cli(prompt: str, b: Benih) -> CutPlan:
    claude = shutil.which("claude")
    if not claude:
        raise DecisionError(
            "Perintah `claude` tidak ditemukan di PATH. Pasang Claude Code, atau "
            "pindah ke DECIDER=api dengan ANTHROPIC_API_KEY."
        )

    penuh = f"{b.sistem()}\n{SKEMA_JSON}\n\n{prompt}"

    cmd = [
        claude, "-p",
        "--output-format", "json",
        "--model", model_untuk(b.identitas),
        # Tugas ini murni teks -> JSON. Tanpa tool, tidak ada yang perlu diizinkan
        # dan tidak ada risiko job menggantung menunggu konfirmasi.
        "--allowedTools", "",
    ]

    log.info(
        "memanggil `claude -p` (%s, model %s, lewat stdin)",
        b.identitas, model_untuk(b.identitas),
    )
    try:
        # Prompt dikirim lewat stdin, BUKAN argumen: transkrip 30 menit bisa
        # melebihi batas 32.767 karakter untuk baris perintah Windows.
        proc = subprocess.run(
            cmd,
            input=penuh,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SETTINGS.cli_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise DecisionError(
            f"`claude -p` melewati batas {SETTINGS.cli_timeout} detik."
        ) from exc

    if proc.returncode != 0:
        # stdout dipilah, bukan disalin mentah: `claude -p --output-format json`
        # menulis alasannya sebagai satu field di dalam amplop JSON, dan 1200
        # karakter JSON mentah menenggelamkan kalimat yang sebenarnya berguna.
        raise DecisionError(
            f"`claude -p` gagal (exit {proc.returncode}): {sebab_gagal(proc)}"
        )

    try:
        amplop = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise DecisionError(
            f"Amplop JSON dari claude CLI tidak terbaca: {exc}\n{proc.stdout[:400]}"
        ) from exc

    if amplop.get("is_error"):
        raise DecisionError(
            f"claude CLI melaporkan error: {amplop.get('result') or amplop.get('subtype')}"
        )

    biaya = amplop.get("total_cost_usd")
    if biaya is not None:
        log.info("setara biaya %.4f USD (%.1f detik)", biaya, (amplop.get("duration_ms") or 0) / 1000)

    return CutPlan.model_validate(_extract_json(amplop.get("result") or ""))


# --------------------------------------------------------------------------
# Backend 2 — SDK anthropic (butuh API key + kredit)
# --------------------------------------------------------------------------


def _call_via_api(prompt: str, b: Benih) -> CutPlan:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise DecisionError(
            "SDK anthropic belum terpasang. Jalankan: pip install anthropic"
        ) from exc

    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=model_untuk(b.identitas),
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=b.sistem(),
        messages=[{"role": "user", "content": prompt}],
        output_format=CutPlan,
    )

    if response.stop_reason == "refusal":
        raise DecisionError(f"Model menolak permintaan: {response.stop_details}")
    if response.parsed_output is None:
        raise DecisionError(
            f"Model tidak mengembalikan struktur yang valid (stop_reason="
            f"{response.stop_reason})."
        )
    return response.parsed_output


_BACKEND = {"claude-cli": _call_via_cli, "api": _call_via_api}


def _call_llm(prompt: str, b: Benih) -> CutPlan:
    fn = _BACKEND.get(SETTINGS.decider)
    if fn is None:
        raise DecisionError(
            f"DECIDER '{SETTINGS.decider}' tidak dikenal. Pilihan: {', '.join(_BACKEND)}"
        )
    return fn(prompt, b)


def decide(
    vmap: ProjectMap,
    profile: ConceptProfile,
    brief: str = "",
    jenis: str = "short",
    arahan: Arahan | None = None,
) -> CutPlan:
    """Hasilkan rencana potongan yang sudah tervalidasi. Satu kali percobaan perbaikan.

    `jenis` memilih BENIH editornya: aturan penyuntingan, model, dan bagian
    konteks mana yang ikut dikirim. Tanpa ini ketiga jenis memakai satu prompt
    yang aturannya benar untuk short saja -- lihat benih.py.
    """
    if not any(v.segments for v in vmap.videos):
        raise DecisionError(
            "Peta video tidak punya transkrip. Tanpa transkrip tidak ada dasar untuk "
            "memilih potongan."
        )

    bnh = benih(jenis)
    koreksi: str | None = None
    for percobaan in (1, 2):
        prompt = _build_prompt(vmap, profile, brief, bnh, arahan=arahan, koreksi=koreksi)
        log.info(
            "meminta rencana potongan ke %s sebagai %s (percobaan %d)",
            model_untuk(bnh.identitas), bnh.identitas, percobaan,
        )
        plan = _call_llm(prompt, bnh)

        masalah = _validate(plan.cuts, vmap, profile, arahan)
        if not masalah:
            plan.cuts = [c for c in plan.cuts if c.out > c.in_]
            log.info(
                "rencana diterima: %d potongan, total %.1fs",
                len(plan.cuts),
                sum(c.durasi for c in plan.cuts),
            )
            return plan

        log.warning("rencana ditolak validator:\n  - %s", "\n  - ".join(masalah))
        koreksi = "\n".join(f"- {m}" for m in masalah)

    raise DecisionError(
        "Rencana potongan masih tidak valid setelah satu kali perbaikan:\n" + (koreksi or "")
    )
