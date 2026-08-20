"""Renderer overlay — audio dari satu rekaman, gambar dari klip lain.

Tiga tahap, masing-masing hanya mengerjakan satu hal:

  1. **Jalur suara.** Potongan pidato diekstrak sebagai audio saja lalu
     disambung. Gambar dari rekaman suara dibuang di sini, dan tidak pernah
     ikut sampai akhir.
  2. **Jalur gambar.** Tiap slot B-roll diekstrak tanpa audio, dinormalkan ke
     rasio dan fps target, lalu disambung.
  3. **Penyatuan.** Kedua jalur digabung dalam satu encode, caption dibakar
     di atasnya.

Kenapa dua jalur digabung di ujung, bukan ditumpuk slot demi slot: menumpuk
berarti satu filter graph raksasa dengan puluhan input, yang lambat dieksekusi
dan nyaris mustahil dibaca saat ada yang salah. Dua concat sederhana lalu satu
mux memberi hasil yang sama dengan bagian yang bisa diperiksa sendiri-sendiri.

Sama seperti renderer ffmpeg, semua perintah dijalankan dengan cwd = work_dir
supaya nama file di filter graph bisa relatif — itu menghindari seluruh masalah
escaping drive letter Windows di dalam filter.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import SETTINGS
from ..kaidah import target_mendatar, target_tegak
from ..models import OverlayEDL, PlannedCut, VideoSlot
from ..probe import run
from .base import Renderer, RenderError
from .ffmpeg import _fade_audio, _punya_audio

log = logging.getLogger(__name__)


def _tangga(titik: list[tuple[float, float]]) -> str:
    """Ekspresi ffmpeg untuk nilai yang berubah terhadap waktu, lurus antar titik.

    ffmpeg tidak punya array di bahasa ekspresinya, jadi jalur disusun sebagai
    if() bersarang. Panjang tapi lurus: sebelum titik pertama nilainya ditahan,
    di antara dua titik diinterpolasi lurus, setelah titik terakhir ditahan lagi.

    Menahan nilai di kedua ujung penting — tanpa itu, bingkai melompat di frame
    pertama dan terakhir slot, tepat di tempat potongan paling terlihat.
    """
    if len(titik) == 1:
        return f"{titik[0][1]:.4f}"

    ekspresi = f"{titik[-1][1]:.4f}"
    for (t0, v0), (t1, v1) in reversed(list(zip(titik, titik[1:]))):
        span = max(1e-6, t1 - t0)
        lurus = f"{v0:.4f}+({v1 - v0:.4f})*(t-{t0:.4f})/{span:.4f}"
        ekspresi = f"if(lt(t,{t1:.4f}),{lurus},{ekspresi})"
    return f"if(lt(t,{titik[0][0]:.4f}),{titik[0][1]:.4f},{ekspresi})"


def posisi_crop(
    fokus_x: float | None,
    fokus_y: float | None,
    arah: float = 0.0,
    jalur: list[list[float]] | None = None,
) -> str:
    """Ekspresi x:y untuk filter crop ffmpeg, mengikuti kaidah bingkai.

    Tanpa x:y, ffmpeg memusatkan crop di tengah frame. Itu asumsi yang sering
    salah: shot 16:9 biasanya membingkai subjeknya di sepertiga kiri atau kanan,
    jadi "tengah" jatuh di antara — pada satu shot bahan pengguna, tepat di setir
    mobil sementara wajahnya terpotong di tepi.

    Wajahnya TIDAK ditaruh persis di tengah bingkai baru. Ke mana ia ditaruh
    ditentukan kaidah.py: ruang pandang di depan arah hadapnya, dan mata di
    sekitar sepertiga atas. Menaruh wajah tepat di tengah adalah kesalahan yang
    lebih halus daripada crop tengah, tapi tetap kesalahan.

    `clip` menjaga jendelanya tetap di dalam gambar, jadi wajah yang berada
    sangat di tepi menghasilkan bingkai mepet tepi, bukan bilah hitam.
    """
    tx = target_mendatar(arah)
    ty = target_tegak()

    # Jalur menang atas titik statis: kalau wajahnya bergerak selama slot,
    # bingkai harus ikut, bukan berdiri di satu tempat sambil kehilangan orangnya.
    if jalur and len(jalur) > 1:
        ex = _tangga([(p[0], p[1]) for p in jalur])
        ey = _tangga([(p[0], p[2]) for p in jalur])
        return (
            f":'clip(({ex})*iw-{tx:.4f}*ow,0,iw-ow)'"
            f":'clip(({ey})*ih-{ty:.4f}*oh,0,ih-oh)'"
        )

    if jalur:
        fokus_x, fokus_y = jalur[0][1], jalur[0][2]
    if fokus_x is None and fokus_y is None:
        return ""
    fx = 0.5 if fokus_x is None else fokus_x
    fy = 0.5 if fokus_y is None else fokus_y
    return (
        f":'clip({fx:.4f}*iw-{tx:.4f}*ow,0,iw-ow)'"
        f":'clip({fy:.4f}*ih-{ty:.4f}*oh,0,ih-oh)'"
    )


def _vf_slot(slot: VideoSlot, width: int, height: int, fps: int) -> str:
    """Crop ke rasio target diarahkan ke wajah (dengan punch-in opsional), lalu scale."""
    z = max(1.0, float(slot.zoom))
    ratio_w = width / height

    crop_w = f"min(iw,ih*{ratio_w:.6f})/{z:.4f}"
    crop_h = f"min(ih,iw/{ratio_w:.6f})/{z:.4f}"

    # Bilah hitam bawaan berkas dibuang LEBIH DULU. Kalau tidak, crop rasio di
    # bawah akan memotong dari gambar yang sudah berbingkai hitam, dan bilahnya
    # ikut sampai ke hasil akhir meski rasionya sudah 9:16.
    buang_bilah = f"crop={slot.crop}," if slot.crop else ""

    return (
        f"{buang_bilah}"
        f"crop='{crop_w}':'{crop_h}'{posisi_crop(slot.fokus_x, slot.fokus_y, slot.arah, slot.jalur)},"
        f"scale={width}:{height}:flags=lanczos,"
        f"setsar=1,"
        f"fps={fps},"
        f"format=yuv420p"
    )



def _tulis_concat(work_dir: Path, nama: str, berkas: list[str]) -> str:
    (work_dir / nama).write_text(
        "\n".join(f"file '{b}'" for b in berkas) + "\n", encoding="utf-8"
    )
    return nama


class OverlayRenderer(Renderer):
    name = "overlay"

    def preflight(self) -> list[str]:
        from ..probe import preflight as probe_preflight

        return probe_preflight()

    # ------------------------------------------------------------------
    # Tahap 1 — jalur suara
    # ------------------------------------------------------------------

    def _potong_audio(self, cut: PlannedCut, i: int, src: str, work_dir: Path) -> str:
        nama = f"aud_{i:03d}.wav"
        cmd = [
            SETTINGS.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{cut.in_:.3f}",
            "-i", src,
            "-t", f"{cut.durasi:.3f}",
            "-vn",
            "-af", _fade_audio(cut.durasi),
            "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
            nama,
        ]
        run(cmd, cwd=work_dir)
        if not (work_dir / nama).exists():
            raise RenderError(f"Potongan suara {i} gagal dibuat.")
        return nama

    # ------------------------------------------------------------------
    # Tahap 2 — jalur gambar
    # ------------------------------------------------------------------

    def _potong_video(
        self, slot: VideoSlot, i: int, edl: OverlayEDL, work_dir: Path
    ) -> str:
        nama = f"vid_{i:03d}.mov"

        # Jumlah frame ditetapkan eksplisit, BUKAN lewat `-t`.
        #
        # Dengan `-t`, panjang keluaran bergantung pada di mana fast-seek `-ss`
        # mendarat, sehingga tiap segmen bisa meleset sepertiga frame. Kecil,
        # tapi menumpuk: diukur pada satu render, 40 segmen membuat jalur gambar
        # 0,47 detik lebih pendek dari jalur suara. Caption dibakar ke gambar
        # sementara posisinya dihitung dari garis waktu suara, jadi selisih itu
        # muncul sebagai subtitle yang makin tertinggal.
        #
        # `-frames:v` menghasilkan tepat N frame, setiap kali.
        jumlah_frame = max(1, round(slot.durasi * edl.fps))

        cmd = [
            SETTINGS.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{slot.in_:.3f}",
            "-i", slot.src,
            "-frames:v", str(jumlah_frame),
            "-an",  # audio klip dibuang total — suaranya datang dari jalur lain
            "-map", "0:v:0",
            "-vf", _vf_slot(slot, edl.resolution.width, edl.resolution.height, edl.fps),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
            nama,
        ]
        run(cmd, cwd=work_dir)
        if not (work_dir / nama).exists():
            raise RenderError(f"Slot gambar {i} gagal dibuat.")
        return nama

    # ------------------------------------------------------------------
    # Tahap 3 — satukan
    # ------------------------------------------------------------------

    def _satukan(
        self,
        daftar_video: str,
        daftar_audio: str,
        edl: OverlayEDL,
        work_dir: Path,
        output: Path,
        ass_file: str | None,
    ) -> None:
        graph = [f"[0:v]{'ass=' + ass_file if ass_file else 'null'}[v]"]

        cmd = [
            SETTINGS.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", daftar_video,
            "-f", "concat", "-safe", "0", "-i", daftar_audio,
            "-filter_complex", ";".join(graph),
            "-map", "[v]", "-map", "1:a:0",
            # Jalur gambar disusun agar sama panjang dengan jalur suara, tapi
            # pembulatan frame bisa menyisakan selisih puluhan milidetik.
            # -shortest memotongnya di titik terpendek, jadi tidak pernah ada
            # ekor hitam atau suara menggantung tanpa gambar.
            "-shortest",
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

    def build(self, edl: OverlayEDL, work_dir: Path, output: Path) -> Path:
        work_dir.mkdir(parents=True, exist_ok=True)
        output.parent.mkdir(parents=True, exist_ok=True)

        if not _punya_audio(edl.audio.src):
            raise RenderError(
                f"Sumber suara '{Path(edl.audio.src).name}' tidak punya track audio. "
                "Format overlay tidak punya apa pun untuk dibunyikan."
            )

        log.info(
            "render overlay: %.1fs suara (%d potongan) + %d slot gambar, %dx%d @ %dfps",
            edl.total_duration, len(edl.audio.cuts), len(edl.video),
            edl.resolution.width, edl.resolution.height, edl.fps,
        )

        potongan_audio: list[str] = []
        for i, cut in enumerate(edl.audio.cuts):
            log.info(
                "  suara %d/%d: %.2f-%.2f (%.2fs, %s)",
                i + 1, len(edl.audio.cuts), cut.in_, cut.out, cut.durasi, cut.role.value,
            )
            potongan_audio.append(self._potong_audio(cut, i, edl.audio.src, work_dir))

        potongan_video: list[str] = []
        for i, slot in enumerate(edl.video):
            log.info(
                "  gambar %d/%d: t=%.2f (%.2fs) <- %s @ %.2f",
                i + 1, len(edl.video), slot.t, slot.durasi,
                Path(slot.src).name, slot.in_,
            )
            potongan_video.append(self._potong_video(slot, i, edl, work_dir))

        daftar_video = _tulis_concat(work_dir, "concat_video.txt", potongan_video)
        daftar_audio = _tulis_concat(work_dir, "concat_audio.txt", potongan_audio)

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

        self._satukan(daftar_video, daftar_audio, edl, work_dir, output, ass_file)

        if not output.exists() or output.stat().st_size == 0:
            raise RenderError(f"Render selesai tapi {output} kosong.")

        log.info("selesai: %s (%.1f MB)", output, output.stat().st_size / 1e6)
        return output
