"""Renderer FFmpeg — jalur utama.

Strategi dua tahap:

  1. Setiap potongan diekstrak sendiri-sendiri dan dinormalkan ke CFR 1080x1920
     dengan parameter yang identik. Di sinilah masalah VFR diselesaikan, dan
     hanya untuk detik-detik yang benar-benar dipakai — bukan untuk seluruh
     rekaman 30 menit.
  2. Segmen digabung dengan concat demuxer, caption dibakar dari file ASS, dan
     musik dicampur, semuanya dalam satu encode akhir.

ffmpeg dijalankan dengan cwd = work_dir sehingga nama file di filter graph
(`ass=captions.ass`) dan di concat list bisa relatif. Itu menghindari seluruh
masalah escaping drive letter Windows (`C\\:/...`) di dalam filter.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import SETTINGS
from ..models import EDL, Cut
from ..probe import FFmpegError, run
from .base import Renderer, RenderError

log = logging.getLogger(__name__)

# Sebagian batas potongan jatuh di tengah frasa yang memang tidak punya jeda —
# di rekaman uji, 21 dari 38. Di sana bentuk gelombang terputus mendadak dan
# terdengar sebagai klik. Fade 12 ms membuat sambungannya mulus tanpa terdengar
# sebagai fade: di bawah ~20 ms telinga membacanya sebagai potongan bersih,
# bukan sebagai suara yang mengecil.
FADE = 0.012


def _fade_audio(durasi: float) -> str:
    """Fade masuk dan keluar sangat pendek, untuk menghilangkan klik sambungan."""
    d = min(FADE, max(0.001, durasi / 4))
    keluar = max(0.0, durasi - d)
    return f"afade=t=in:st=0:d={d:.3f},afade=t=out:st={keluar:.3f}:d={d:.3f}"



def _vf_chain(cut: Cut, width: int, height: int, fps: int) -> str:
    """Crop tengah ke rasio target (dengan punch-in opsional), lalu scale."""
    z = max(1.0, float(cut.zoom))
    ratio_w = width / height  # 1080/1920 = 0.5625

    # Ambil area terbesar yang muat di rasio target, lalu perkecil sesuai zoom.
    crop_w = f"min(iw,ih*{ratio_w:.6f})/{z:.4f}"
    crop_h = f"min(ih,iw/{ratio_w:.6f})/{z:.4f}"

    # Bilah hitam yang terbakar di berkas dibuang lebih dulu, sebelum crop
    # rasio. Urutan terbalik akan memotong 9:16 dari gambar yang sudah
    # berbingkai — rasionya benar tapi bilahnya tetap ikut ke hasil.
    buang_bilah = f"crop={cut.crop}," if cut.crop else ""

    from .overlay import posisi_crop

    return (
        f"{buang_bilah}"
        f"crop='{crop_w}':'{crop_h}'{posisi_crop(cut.fokus_x, cut.fokus_y, cut.arah, cut.jalur)},"
        f"scale={width}:{height}:flags=lanczos,"
        f"setsar=1,"
        f"fps={fps},"
        f"format=yuv420p"
    )


class FfmpegRenderer(Renderer):
    name = "ffmpeg"

    def preflight(self) -> list[str]:
        from ..probe import preflight as probe_preflight

        return probe_preflight()

    # ------------------------------------------------------------------
    # Tahap 1 — ekstraksi segmen
    # ------------------------------------------------------------------

    def _extract_segment(self, cut: Cut, index: int, edl: EDL, work_dir: Path) -> str:
        nama = f"seg_{index:03d}.mov"
        target = work_dir / nama

        cmd = [
            SETTINGS.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            # -ss sebelum -i = fast seek; dengan re-encode ffmpeg tetap presisi
            # ke frame karena ia decode lalu buang sampai titik yang diminta.
            "-ss", f"{cut.in_:.3f}",
            "-i", cut.src,
        ]

        punya_audio = _punya_audio(cut.src)
        if not punya_audio:
            # Sisipkan audio hening supaya semua segmen punya jumlah stream sama;
            # concat demuxer menolak input yang tidak seragam.
            cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]

        cmd += [
            "-t", f"{cut.durasi:.3f}",
            "-map", "0:v:0",
            "-map", ("0:a:0" if punya_audio else "1:a:0"),
            "-vf", _vf_chain(cut, edl.resolution.width, edl.resolution.height, edl.fps),
            # Fade sangat pendek di kedua ujung: tanpa ini, sambungan antar
            # segmen memutus bentuk gelombang di tengah dan terdengar sebagai
            # klik. Sama seperti di renderer overlay.
            "-af", _fade_audio(cut.durasi),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
            "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
            nama,
        ]

        log.info(
            "  segmen %d/%d: %.2f-%.2f (%.2fs, %s, zoom %.2f)",
            index + 1, len(edl.cuts), cut.in_, cut.out, cut.durasi, cut.role.value, cut.zoom,
        )
        run(cmd, cwd=work_dir)

        if not target.exists() or target.stat().st_size == 0:
            raise RenderError(f"Segmen {index} gagal dibuat: {target}")
        return nama

    # ------------------------------------------------------------------
    # Tahap 2 — gabung, bakar caption, campur musik
    # ------------------------------------------------------------------

    def _final_encode(
        self,
        segmen: list[str],
        edl: EDL,
        work_dir: Path,
        output: Path,
        ass_file: str | None,
    ) -> None:
        list_file = work_dir / "concat.txt"
        list_file.write_text(
            "\n".join(f"file '{nama}'" for nama in segmen) + "\n", encoding="utf-8"
        )

        cmd = [
            SETTINGS.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", "concat.txt",
        ]

        pakai_musik = edl.music is not None
        if pakai_musik:
            cmd += ["-stream_loop", "-1", "-i", edl.music.src]

        # --- filter graph ---
        graph: list[str] = []
        graph.append(f"[0:v]{'ass=' + ass_file if ass_file else 'null'}[v]")

        if pakai_musik:
            total = edl.total_duration
            fade_start = max(0.0, total - edl.music.fade_out)
            graph.append(
                f"[1:a]volume={edl.music.gain_db}dB,"
                f"afade=t=out:st={fade_start:.2f}:d={edl.music.fade_out:.2f}[m]"
            )
            # normalize=0 penting: tanpa itu amix menurunkan volume suara utama.
            graph.append("[0:a][m]amix=inputs=2:duration=first:normalize=0[a]")
        else:
            graph.append("[0:a]anull[a]")

        cmd += [
            "-filter_complex", ";".join(graph),
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
            "-g", str(edl.fps * 2),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart",
            str(output.resolve()),
        ]

        log.info("encode akhir -> %s", output)
        run(cmd, cwd=work_dir)

    # ------------------------------------------------------------------

    def build(self, edl: EDL, work_dir: Path, output: Path) -> Path:
        work_dir.mkdir(parents=True, exist_ok=True)
        output.parent.mkdir(parents=True, exist_ok=True)

        log.info(
            "render %d potongan, total %.1fs, %dx%d @ %dfps",
            len(edl.cuts), edl.total_duration,
            edl.resolution.width, edl.resolution.height, edl.fps,
        )

        try:
            segmen = [
                self._extract_segment(cut, i, edl, work_dir)
                for i, cut in enumerate(edl.cuts)
            ]

            ass_file: str | None = None
            if edl.captions and edl.caption_style.ada:
                from ..captions import write_ass

                ass_file = "captions.ass"
                write_ass(
                    edl.captions,
                    edl.caption_style,
                    work_dir / ass_file,
                    width=edl.resolution.width,
                    height=edl.resolution.height,
                )

            self._final_encode(segmen, edl, work_dir, output, ass_file)
        except FFmpegError as exc:
            raise RenderError(str(exc)) from exc

        if not output.exists() or output.stat().st_size == 0:
            raise RenderError(f"Render selesai tanpa error tapi {output} kosong.")

        log.info("selesai: %s (%.1f MB)", output, output.stat().st_size / 1e6)
        return output


_audio_cache: dict[str, bool] = {}


def _punya_audio(src: str) -> bool:
    if src not in _audio_cache:
        from ..probe import probe

        _audio_cache[src] = probe(src).punya_audio
    return _audio_cache[src]
