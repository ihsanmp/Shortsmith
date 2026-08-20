"""Pemilihan renderer lewat environment variable RENDERER."""

from __future__ import annotations

from ..config import SETTINGS
from .base import Renderer, RenderError

__all__ = ["Renderer", "RenderError", "get_renderer"]


def get_renderer(name: str | None = None) -> Renderer:
    name = (name or SETTINGS.renderer).lower()

    if name == "ffmpeg":
        from .ffmpeg import FfmpegRenderer

        return FfmpegRenderer()

    if name == "overlay":
        from .overlay import OverlayRenderer

        return OverlayRenderer()

    if name == "resolve":
        from .resolve import ResolveRenderer

        return ResolveRenderer()

    raise ValueError(f"Renderer '{name}' tidak dikenal. Pilihan: ffmpeg, overlay, resolve")
