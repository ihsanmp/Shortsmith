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
from .identitas import model_untuk
from .models import ConceptProfile, CutPlan, PlannedCut, ProjectMap

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


SYSTEM_PROMPT = """\
Kamu adalah editor short video. Tugasmu memilih potongan mana dari sebuah rekaman \
panjang yang layak dirangkai menjadi satu short video vertikal.

Aturan kerja:
- Suara HANYA boleh diambil dari VIDEO 0. Selalu isi `sumber: 0`. Video lain \
adalah pustaka klip yang cuma dipakai gambarnya, tidak bersuara, dan tidak \
punya transkrip.
- Hasil akhirnya satu topik utuh. Jangan menjahit dua bahasan berbeda hanya \
karena keduanya sama-sama kuat — pilih satu benang, lalu ikuti sampai selesai.
- Kamu HANYA memilih rentang waktu. Jangan menulis caption, jangan mengarang \
narasi, jangan mengusulkan efek. Caption dibuat otomatis dari transkrip.
- Setiap rentang harus jatuh di dalam durasi rekaman dan diambil dari transkrip \
yang diberikan. Jangan pernah mengarang timestamp.
- Potong di jeda hening bila memungkinkan, bukan di tengah kata. Daftar jeda \
hening disediakan untuk itu.
- Urutan potongan di keluaranmu adalah urutan tayang. Ia tidak harus urut \
kronologis terhadap rekaman aslinya.
- Potongan pertama adalah hook: ia harus berdiri sendiri dan membuat orang \
berhenti scroll dalam 2 detik pertama.
- `zoom` adalah punch-in halus (1.0 = tanpa zoom, 1.15 = sedikit mendekat). \
Gunakan sesekali untuk memberi variasi visual, jangan di setiap potongan.
- `alasan` ditulis singkat dalam Bahasa Indonesia, untuk keperluan penelusuran.
"""


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


def _format_map(vmap: ProjectMap, *, max_silences: int = 40) -> str:
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
    for seg in utama.segments:
        baris.append(f"[{seg.start:.2f}-{seg.end:.2f}] {seg.text}")

    jeda = sorted(utama.silences, key=lambda s: s.durasi, reverse=True)[:max_silences]
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
    vmap: ProjectMap, profile: ConceptProfile, brief: str, *, koreksi: str | None = None
) -> str:
    target = profile.target_duration()
    jumlah_cut = profile.target_cuts()

    bagian = [
        "== KONSEP ==",
        _format_profile(profile),
        "",
        f"== VIDEO MENTAH ({len(vmap.videos)} file) ==",
        _format_map(vmap),
        "",
        "== FOKUS PEMBAHASAN ==",
        _format_fokus(brief, profile),
        "",
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


def _validate(cuts: list[PlannedCut], vmap: ProjectMap, profile: ConceptProfile) -> list[str]:
    """Clamp in-place ke durasi video sumbernya, lalu kembalikan sisa masalah."""
    masalah: list[str] = []

    # Pembanding rasio HARUS video suara saja, bukan vmap.total_durasi. Video
    # ke-2 dan seterusnya adalah pustaka klip yang tidak menyumbang satu detik
    # pun ke audio; ikut menghitungnya membuat penjaga 85% ini menggelembung
    # sampai tak pernah menyala. Tambah 20 klip B-roll dan penjaganya mati.
    durasi_sumber = vmap.videos[0].media.durasi

    for i, cut in enumerate(cuts):
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


def _call_via_cli(prompt: str) -> CutPlan:
    claude = shutil.which("claude")
    if not claude:
        raise DecisionError(
            "Perintah `claude` tidak ditemukan di PATH. Pasang Claude Code, atau "
            "pindah ke DECIDER=api dengan ANTHROPIC_API_KEY."
        )

    penuh = f"{SYSTEM_PROMPT}\n{SKEMA_JSON}\n\n{prompt}"

    cmd = [
        claude, "-p",
        "--output-format", "json",
        "--model", model_untuk("editor"),
        # Tugas ini murni teks -> JSON. Tanpa tool, tidak ada yang perlu diizinkan
        # dan tidak ada risiko job menggantung menunggu konfirmasi.
        "--allowedTools", "",
    ]

    log.info("memanggil `claude -p` (model %s, lewat stdin)", model_untuk("editor"))
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
        ekor = (proc.stderr or proc.stdout or "").strip()[-1200:]
        raise DecisionError(f"`claude -p` gagal (exit {proc.returncode}):\n{ekor}")

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


def _call_via_api(prompt: str) -> CutPlan:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise DecisionError(
            "SDK anthropic belum terpasang. Jalankan: pip install anthropic"
        ) from exc

    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=model_untuk("editor"),
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
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


def _call_llm(prompt: str) -> CutPlan:
    fn = _BACKEND.get(SETTINGS.decider)
    if fn is None:
        raise DecisionError(
            f"DECIDER '{SETTINGS.decider}' tidak dikenal. Pilihan: {', '.join(_BACKEND)}"
        )
    return fn(prompt)


def decide(vmap: ProjectMap, profile: ConceptProfile, brief: str = "") -> CutPlan:
    """Hasilkan rencana potongan yang sudah tervalidasi. Satu kali percobaan perbaikan."""
    if not any(v.segments for v in vmap.videos):
        raise DecisionError(
            "Peta video tidak punya transkrip. Tanpa transkrip tidak ada dasar untuk "
            "memilih potongan."
        )

    koreksi: str | None = None
    for percobaan in (1, 2):
        prompt = _build_prompt(vmap, profile, brief, koreksi=koreksi)
        log.info("meminta rencana potongan ke %s (percobaan %d)", model_untuk("editor"), percobaan)
        plan = _call_llm(prompt)

        masalah = _validate(plan.cuts, vmap, profile)
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
