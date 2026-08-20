"""Pembungkus ffprobe/ffmpeg tingkat rendah."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from .config import SETTINGS
from .models import MediaInfo

log = logging.getLogger(__name__)


class ToolMissing(RuntimeError):
    pass


class FFmpegError(RuntimeError):
    pass


def run(cmd: list[str], *, cwd: Path | None = None, capture: bool = True) -> str:
    """Jalankan satu perintah dan kembalikan stdout. Melempar FFmpegError kalau gagal."""
    log.debug("run: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise ToolMissing(
            f"'{cmd[0]}' tidak ditemukan. Install ffmpeg dan pastikan ada di PATH, "
            f"atau set FFMPEG_PATH / FFPROBE_PATH."
        ) from exc

    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-25:]
        raise FFmpegError(
            f"{Path(cmd[0]).name} keluar dengan kode {proc.returncode}:\n" + "\n".join(tail)
        )
    return proc.stdout or ""


def run_capture_stderr(cmd: list[str]) -> str:
    """ffmpeg menulis banyak informasi berguna (silencedetect, dll) ke stderr."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except FileNotFoundError as exc:
        raise ToolMissing(f"'{cmd[0]}' tidak ditemukan di PATH.") from exc
    return proc.stderr or ""


def _fraction(value: str | None) -> float:
    if not value:
        return 0.0
    if "/" in value:
        num, _, den = value.partition("/")
        try:
            d = float(den)
            return float(num) / d if d else 0.0
        except ValueError:
            return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


_memo: dict[tuple[str, int, int], MediaInfo] = {}


def probe(path: str | Path) -> MediaInfo:
    """Baca metadata dasar satu file media.

    Hasilnya diingat per berkas selama proses berjalan. Metadata tidak berubah
    saat kita memeriksanya, jadi memanggil ffprobe berulang untuk berkas yang
    sama murni pemborosan — dan bukan pemborosan kecil.

    Deteksi bilah dan pemecahan adegan memanggil fungsi ini per POTONGAN, bukan
    per berkas, sehingga satu berkas bisa memicu ratusan pemanggilan. Pada satu
    job nyata, rentetan itu membuat ffprobe.exe jatuh dengan 0xC0000409
    (STATUS_STACK_BUFFER_OVERRUN) dan menggagalkan seluruh job. Mengingat
    hasilnya menghapus rentetannya sekaligus.

    Kunci memo memuat ukuran dan waktu ubah, jadi berkas yang diganti di
    tengah jalan tetap dibaca ulang.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File tidak ada: {path}")

    st = path.stat()
    kunci = (str(path.resolve()), st.st_size, st.st_mtime_ns)
    if (ada := _memo.get(kunci)) is not None:
        # SALINAN, bukan objek aslinya. MediaInfo bisa diubah pemanggil —
        # build_map menulis media.crop ke situ — dan membagikan satu objek
        # yang sama akan membuat perubahan satu pemanggil bocor ke semua.
        return ada.model_copy()

    out = run(
        [
            SETTINGS.ffprobe,
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    data = json.loads(out)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if video is None:
        raise FFmpegError(f"Tidak ada stream video di {path}")

    durasi = float(data.get("format", {}).get("duration") or video.get("duration") or 0.0)
    avg = _fraction(video.get("avg_frame_rate"))
    r = _fraction(video.get("r_frame_rate"))

    # Heuristik VFR: r_frame_rate (rate nominal) menyimpang jauh dari avg_frame_rate
    # (rate sebenarnya). Rekaman ponsel & OBS hampir selalu kena di sini.
    vfr = bool(avg and r and abs(r - avg) / max(avg, 1e-6) > 0.02)

    info = MediaInfo(
        path=str(path),
        durasi=durasi,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=avg or r or 30.0,
        punya_audio=audio is not None,
        codec_video=str(video.get("codec_name") or ""),
        vfr=vfr,
    )
    _memo[kunci] = info
    return info.model_copy()


def preflight() -> list[str]:
    """Cek lingkungan. Kembalikan daftar masalah — kosong berarti siap jalan."""
    masalah: list[str] = []
    for name, binary in (("ffmpeg", SETTINGS.ffmpeg), ("ffprobe", SETTINGS.ffprobe)):
        try:
            run([binary, "-version"])
        except (ToolMissing, FFmpegError):
            masalah.append(f"{name} tidak bisa dijalankan ('{binary}')")
    return masalah
