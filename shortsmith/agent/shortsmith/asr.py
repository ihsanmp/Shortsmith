"""Transkrip dengan backend yang bisa ditukar.

Dua backend:

  faster-whisper  — CPU saja (CTranslate2 tidak punya jalur NPU/iGPU sama sekali).
                    Satu-satunya yang memberi timestamp PER KATA yang sungguhan.

  openvino        — Jalankan di Intel Arc iGPU atau Intel AI Boost NPU lewat
                    OpenVINO GenAI. Jauh lebih cepat di Core Ultra, tapi
                    WhisperPipeline hanya mengembalikan timestamp per potongan
                    (~beberapa detik), bukan per kata. Waktu tiap kata di sini
                    DIINTERPOLASI di dalam potongan, proporsional terhadap
                    panjang karakter.

Konsekuensi yang harus disadari: dengan backend openvino, caption tetap akurat
secara teks (tidak ada kata yang mengada-ada, karena tetap datang dari transkrip)
tapi presisi waktunya turun dari ~50ms ke ~150ms. Untuk caption per frasa itu
tidak terasa. Untuk gaya kata-per-kata yang ketat, pakai faster-whisper.
"""

from __future__ import annotations

import logging
import re
import shutil
import sys
from pathlib import Path

from .config import SETTINGS
from .models import TranscriptSegment, Word
from .probe import run

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


# --------------------------------------------------------------------------
# Utilitas bersama
# --------------------------------------------------------------------------


def load_audio(path: str | Path) -> "object":
    """Decode audio apa pun menjadi float32 mono 16 kHz lewat ffmpeg."""
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("numpy diperlukan untuk backend openvino: pip install numpy") from exc

    import subprocess

    cmd = [
        SETTINGS.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", str(path),
        "-f", "s16le", "-acodec", "pcm_s16le",
        "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            "Gagal decode audio:\n" + proc.stderr.decode("utf-8", "replace")[-2000:]
        )
    return np.frombuffer(proc.stdout, dtype=np.int16).astype("float32") / 32768.0


_TOKEN = re.compile(r"\S+")


def _interpolate_words(text: str, start: float, end: float) -> list[Word]:
    """Bagi rentang waktu satu potongan ke kata-katanya, proporsional panjang karakter.

    Ini aproksimasi, bukan pengukuran. Dipakai hanya oleh backend yang tidak
    memberi timestamp per kata.
    """
    tokens = _TOKEN.findall(text.strip())
    if not tokens or end <= start:
        return []

    total_chars = sum(len(t) for t in tokens)
    if total_chars == 0:
        return []

    span = end - start
    words: list[Word] = []
    cursor = start
    for tok in tokens:
        durasi = span * (len(tok) / total_chars)
        words.append(Word(start=round(cursor, 3), end=round(cursor + durasi, 3), text=tok))
        cursor += durasi
    return words


# --------------------------------------------------------------------------
# Backend 1 — faster-whisper (CPU, timestamp per kata sungguhan)
# --------------------------------------------------------------------------


def _transcribe_faster_whisper(path: str | Path) -> tuple[list[TranscriptSegment], list[Word]]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper belum terpasang. Jalankan: pip install faster-whisper"
        ) from exc

    log.info(
        "faster-whisper: model=%s device=%s compute=%s",
        SETTINGS.whisper_model, SETTINGS.whisper_device, SETTINGS.whisper_compute,
    )
    model = WhisperModel(
        SETTINGS.whisper_model,
        device=SETTINGS.whisper_device,
        compute_type=SETTINGS.whisper_compute,
    )
    raw_segments, info = model.transcribe(
        str(path),
        language=SETTINGS.whisper_language or None,
        word_timestamps=True,
        vad_filter=True,
    )
    log.info("bahasa: %s (p=%.2f)", info.language, info.language_probability)

    segments: list[TranscriptSegment] = []
    words: list[Word] = []
    for seg in raw_segments:
        text = (seg.text or "").strip()
        if text:
            segments.append(TranscriptSegment(start=seg.start, end=seg.end, text=text))
        for w in seg.words or []:
            wt = (w.word or "").strip()
            if wt and w.end > w.start:
                words.append(Word(start=w.start, end=w.end, text=wt))
    return segments, words


# --------------------------------------------------------------------------
# Backend 2 — OpenVINO (Intel Arc iGPU / Intel AI Boost NPU)
# --------------------------------------------------------------------------


def available_devices() -> list[str]:
    """Daftar device OpenVINO yang terdeteksi, mis. ['CPU', 'GPU', 'NPU']."""
    try:
        import openvino as ov
    except ImportError:
        return []
    return list(ov.Core().available_devices)


def _transcribe_openvino(path: str | Path) -> tuple[list[TranscriptSegment], list[Word]]:
    try:
        import openvino_genai as ov_genai
    except ImportError as exc:
        raise RuntimeError(
            "openvino-genai belum terpasang. Jalankan:\n"
            "  pip install openvino openvino-genai optimum[openvino]"
        ) from exc

    model_dir = Path(SETTINGS.ov_model_dir)
    if not model_dir.exists():
        raise RuntimeError(
            f"Model OpenVINO tidak ada di '{model_dir}'.\n"
            f"Konversi dulu:  python -m shortsmith.cli prepare-model --device "
            f"{SETTINGS.ov_device}"
        )

    device = SETTINGS.ov_device.upper()
    tersedia = available_devices()
    if tersedia and device not in tersedia:
        raise RuntimeError(
            f"Device '{device}' tidak terdeteksi OpenVINO. Yang tersedia: {tersedia}"
        )

    log.info("openvino: model=%s device=%s", model_dir, device)
    pipe = ov_genai.WhisperPipeline(str(model_dir), device=device)

    audio = load_audio(path)
    result = pipe.generate(
        audio,
        language=f"<|{SETTINGS.whisper_language}|>" if SETTINGS.whisper_language else None,
        task="transcribe",
        return_timestamps=True,
    )

    segments: list[TranscriptSegment] = []
    words: list[Word] = []
    for chunk in getattr(result, "chunks", None) or []:
        text = (chunk.text or "").strip()
        start = float(chunk.start_ts)
        end = float(chunk.end_ts)
        if not text or end <= start:
            continue
        segments.append(TranscriptSegment(start=start, end=end, text=text))
        words.extend(_interpolate_words(text, start, end))

    if not segments:
        # Tanpa timestamp sama sekali kita tidak bisa memotong apa pun.
        raise RuntimeError(
            "WhisperPipeline tidak mengembalikan potongan bertimestamp. "
            "Pastikan model diekspor dengan dukungan timestamp."
        )

    log.info(
        "openvino: %d potongan, %d kata (waktu kata diinterpolasi)", len(segments), len(words)
    )
    return segments, words


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------

_BACKENDS = {
    "faster-whisper": _transcribe_faster_whisper,
    "openvino": _transcribe_openvino,
}


def transcribe(path: str | Path) -> tuple[list[TranscriptSegment], list[Word]]:
    backend = SETTINGS.asr_backend.lower()
    fn = _BACKENDS.get(backend)
    if fn is None:
        raise RuntimeError(
            f"Backend ASR '{backend}' tidak dikenal. Pilihan: {', '.join(_BACKENDS)}"
        )
    return fn(path)


# --------------------------------------------------------------------------
# Konversi model ke format OpenVINO
# --------------------------------------------------------------------------


def _optimum_cli() -> list[str]:
    """Temukan optimum-cli tanpa bergantung pada PATH.

    Kalau venv tidak diaktifkan (mis. agent dijalankan lewat path absolut ke
    python.exe), direktori Scripts/ tidak ada di PATH dan `optimum-cli` tidak
    ketemu. Cari dulu di sebelah interpreter yang sedang jalan; kalau tidak ada,
    panggil sebagai modul.
    """
    scripts = Path(sys.executable).parent
    for nama in ("optimum-cli.exe", "optimum-cli"):
        kandidat = scripts / nama
        if kandidat.exists():
            return [str(kandidat)]

    if which := shutil.which("optimum-cli"):
        return [which]

    return [sys.executable, "-m", "optimum.commands.optimum_cli"]


def export_openvino_model(
    hf_model: str, out_dir: Path, *, device: str, weight_format: str = "int8"
) -> None:
    """Jalankan optimum-cli untuk mengubah model Whisper HuggingFace ke OpenVINO IR.

    Catatan penting soal NPU: NPU butuh graph berbentuk statis, jadi ekspornya
    harus memakai --disable-stateful. Model hasil ekspor untuk NPU tidak optimal
    untuk GPU dan sebaliknya — simpan di direktori terpisah kalau ingin
    membandingkan keduanya.
    """
    cmd = [
        *_optimum_cli(),
        "export", "openvino",
        "--model", hf_model,
        "--task", "automatic-speech-recognition-with-past",
        "--weight-format", weight_format,
    ]
    if device.upper() == "NPU":
        cmd.append("--disable-stateful")
    cmd.append(str(out_dir))

    log.info("mengekspor %s -> %s (device=%s)", hf_model, out_dir, device)
    run(cmd)
