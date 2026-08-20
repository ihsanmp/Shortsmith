"""Interface renderer.

Seluruh lapisan di atas EDL tidak tahu apa-apa soal ffmpeg maupun Resolve.
Menukar implementasi cukup lewat environment variable RENDERER.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import EDL, OverlayEDL


class RenderError(RuntimeError):
    pass


class Renderer(ABC):
    """Terima EDL, kembalikan path file hasil render."""

    name: str = "base"

    @abstractmethod
    def build(self, edl: EDL | OverlayEDL, work_dir: Path, output: Path) -> Path:
        """Render EDL menjadi satu file video di `output`.

        Dua bentuk EDL diterima: `EDL` untuk format satu jalur, `OverlayEDL`
        untuk format audio + B-roll. Tiap renderer hanya menangani salah satu;
        yang memilih adalah pipeline berdasarkan `profile.format`.
        """

    def preflight(self) -> list[str]:
        """Cek kesiapan lingkungan. Kembalikan daftar masalah; kosong berarti siap."""
        return []
