"""Renderer DaVinci Resolve — jalur kedua.

PERINGATAN JUJUR: kode di file ini belum pernah dijalankan terhadap instalasi
Resolve yang nyata. Ia ditulis sesuai API DaVinciResolveScript, tapi anggap ia
BELUM TERBUKTI sampai kamu menjalankan Milestone 1 sendiri di mesinmu.

Syarat yang tidak bisa dinegosiasikan:
  - DaVinci Resolve **Studio** (versi gratis tidak mengizinkan scripting eksternal)
  - Resolve harus sudah berjalan dengan GUI terbuka
  - Preferences -> System -> General -> External scripting using: Local

Strategi: segmen tetap diekstrak lebih dulu dengan ffmpeg (CFR, sudah 1080x1920).
Resolve hanya menerima file yang sudah bersih, jadi seluruh kelas masalah VFR dan
H.265 tidak pernah sampai ke sana. Yang tersisa untuk Resolve adalah nilai
tambahnya sendiri: grading dan template Fusion.

## Hidup berdampingan dengan pekerjaan lain

Resolve di mesin ini bukan milik Shortsmith sendiri. Instance yang sama dipakai
untuk mengedit hal lain, dan API Resolve tidak punya konsep "sesi terpisah":
satu aplikasi, satu project aktif, satu antrean render. Apa pun yang dilakukan
skrip ini terjadi di jendela yang sama dengan pekerjaanmu.

Karena itu seluruh jalur render dibungkus `_SesiPinjaman`, yang menjamin empat hal:

1. **Tidak menyerobot.** Kalau Resolve sedang merender, job ditolak dan
   dikembalikan ke antrean, bukan dipaksa masuk.
2. **Tidak mencampur.** Project Shortsmith dibuat di dalam folder tersendiri di
   Project Manager, bukan di akar tempat project pribadimu berada.
3. **Tidak menyentuh milikmu.** Setiap operasi yang mengubah timeline lebih dulu
   memeriksa bahwa project aktif memang milik Shortsmith. Kalau perpindahan
   project gagal diam-diam, kode berhenti — bukan lanjut mengedit timeline-mu.
4. **Mengembalikan seperti semula.** Project yang tadinya terbuka dibuka lagi,
   dan project Shortsmith dihapus setelah sukses.

Satu hal yang TIDAK bisa dijamin dari sisi skrip: `CreateProject` akan menutup
project yang sedang terbuka. Kalau ada perubahan yang belum tersimpan dan Live
Save mati, perubahan itu hilang — API tidak menyediakan cara membaca status
"belum tersimpan". Nyalakan Preferences -> User -> Project Save and Load ->
Live Save sebelum memakai jalur ini.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from ..config import SETTINGS
from ..models import EDL
from .base import Renderer, RenderError
from .ffmpeg import FfmpegRenderer

log = logging.getLogger(__name__)

RENDER_TIMEOUT = 30 * 60  # detik — watchdog, supaya job macet tidak menggantung selamanya
CONNECT_TIMEOUT = 60


class ResolveSibuk(RenderError):
    """Resolve sedang dipakai untuk hal lain. Job harus antre, bukan menyerobot."""


def _setup_env() -> None:
    """Set tiga environment variable secara programatik, sebelum import.

    Sengaja tidak bergantung pada konfigurasi shell — agent harus jalan sama saja
    dari terminal mana pun. Jangan pernah membungkus path dengan tanda kutip di
    Windows; itu memutus koneksi.
    """
    if sys.platform == "win32":
        program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        api = os.environ.get(
            "RESOLVE_SCRIPT_API",
            rf"{program_data}\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting",
        )
        lib = os.environ.get(
            "RESOLVE_SCRIPT_LIB",
            r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
        )
    elif sys.platform == "darwin":
        api = os.environ.get(
            "RESOLVE_SCRIPT_API",
            "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting",
        )
        lib = os.environ.get(
            "RESOLVE_SCRIPT_LIB",
            "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/"
            "Fusion/fusionscript.so",
        )
    else:
        api = os.environ.get("RESOLVE_SCRIPT_API", "/opt/resolve/Developer/Scripting")
        lib = os.environ.get("RESOLVE_SCRIPT_LIB", "/opt/resolve/libs/Fusion/fusionscript.so")

    os.environ["RESOLVE_SCRIPT_API"] = api
    os.environ["RESOLVE_SCRIPT_LIB"] = lib

    modules = str(Path(api) / "Modules")
    if modules not in sys.path:
        sys.path.append(modules)


def _connect():
    """Sambung ke Resolve. scriptapp() mengembalikan None kalau Resolve tidak jalan."""
    _setup_env()
    try:
        import DaVinciResolveScript as dvr  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RenderError(
            "Modul DaVinciResolveScript tidak ditemukan. Periksa RESOLVE_SCRIPT_API "
            f"(sekarang: {os.environ.get('RESOLVE_SCRIPT_API')}) dan pastikan Resolve "
            "Studio terpasang."
        ) from exc

    batas = time.time() + CONNECT_TIMEOUT
    while time.time() < batas:
        resolve = dvr.scriptapp("Resolve")
        if resolve is not None:
            log.info("tersambung ke Resolve: %s", resolve.GetVersionString())
            return resolve
        log.info("Resolve belum merespons, coba lagi dalam 2 detik...")
        time.sleep(2)

    raise RenderError(
        "scriptapp('Resolve') mengembalikan None selama "
        f"{CONNECT_TIMEOUT} detik. Artinya Resolve belum berjalan, atau "
        "'External scripting using' belum diset ke Local di Preferences."
    )


class _SesiPinjaman:
    """Context manager yang meminjam Resolve, lalu mengembalikannya utuh.

    Dipakai sebagai:

        with _SesiPinjaman(resolve) as sesi:
            sesi.project.GetMediaPool()...

    Keluar dari blok — baik sukses maupun karena exception — selalu memulihkan
    project yang tadinya terbuka.
    """

    def __init__(self, resolve):
        self.resolve = resolve
        self.pm = resolve.GetProjectManager()
        self.nama = f"shortsmith_{datetime.now():%Y%m%d_%H%M%S}"
        self.project = None
        self._nama_sebelumnya: str | None = None
        self._sukses = False

    # -- masuk ------------------------------------------------------------

    def __enter__(self) -> "_SesiPinjaman":
        sebelumnya = self.pm.GetCurrentProject()
        self._nama_sebelumnya = sebelumnya.GetName() if sebelumnya else None

        # Menyerobot GPU dan antrean render orang lain adalah cara tercepat
        # merusak hasil kerja yang sedang berjalan. Lebih baik job ini gagal
        # sopan dan diulang nanti oleh reaper.
        if sebelumnya is not None and sebelumnya.IsRenderingInProgress():
            if not SETTINGS.resolve_paksa:
                raise ResolveSibuk(
                    f"Resolve sedang merender project '{self._nama_sebelumnya}'. "
                    "Job ditunda supaya tidak mengganggu. Set RESOLVE_PAKSA=1 "
                    "kalau memang ingin menyerobot."
                )
            log.warning("RESOLVE_PAKSA aktif — melanjutkan meski Resolve sedang merender")

        self._buka_folder()

        self.project = self.pm.CreateProject(self.nama)
        if not self.project:
            raise RenderError(
                f"CreateProject('{self.nama}') gagal. Biasanya karena project "
                "dengan nama sama sudah ada, atau database project sedang terkunci."
            )

        # Verifikasi keras: kalau perpindahan project gagal diam-diam, seluruh
        # operasi berikutnya akan mengedit timeline milik pengguna. Lebih baik
        # berhenti di sini.
        self.pastikan_milik_kita()
        log.info("project pinjaman: %s (sebelumnya: %s)", self.nama, self._nama_sebelumnya)
        return self

    def _buka_folder(self) -> None:
        """Pindah ke folder khusus Shortsmith di Project Manager.

        Kalau gagal, render tetap dilanjutkan di akar — project akan tercampur
        dengan milikmu tapi tidak ada yang rusak. Itu gangguan kerapian, bukan
        kegagalan, jadi tidak pantas membatalkan job.
        """
        folder = SETTINGS.resolve_folder.strip()
        if not folder:
            return
        try:
            self.pm.GotoRootFolder()
            if not self.pm.OpenFolder(folder):
                self.pm.CreateFolder(folder)
                self.pm.OpenFolder(folder)
        except Exception as exc:  # noqa: BLE001 — API Resolve hanya kembalikan True/False
            log.warning("gagal membuka folder '%s' (%s) — project dibuat di akar", folder, exc)

    # -- penjaga ----------------------------------------------------------

    def pastikan_milik_kita(self) -> None:
        """Pagar yang dipanggil sebelum tiap operasi yang mengubah timeline.

        Resolve hanya punya satu project aktif. Kalau karena alasan apa pun
        project aktif bukan milik kita, operasi apa pun setelah ini akan jatuh
        ke timeline pengguna.
        """
        aktif = self.pm.GetCurrentProject()
        nama_aktif = aktif.GetName() if aktif else None
        if nama_aktif != self.nama:
            raise RenderError(
                f"Project aktif di Resolve adalah '{nama_aktif}', bukan '{self.nama}'. "
                "Operasi dibatalkan supaya tidak mengubah project milikmu."
            )

    def tandai_sukses(self) -> None:
        self._sukses = True

    # -- keluar -----------------------------------------------------------

    def __exit__(self, exc_type, exc, tb) -> bool:
        # Seluruh pemulihan dibungkus try masing-masing: kegagalan membereskan
        # tidak boleh menutupi exception asli yang sedang naik.
        try:
            if self.project is not None:
                self.project.DeleteAllRenderJobs()
        except Exception as e:  # noqa: BLE001
            log.warning("gagal membersihkan antrean render: %s", e)

        try:
            if self.project is not None:
                self.pm.CloseProject(self.project)
        except Exception as e:  # noqa: BLE001
            log.warning("gagal menutup project pinjaman: %s", e)

        # Project hanya dihapus kalau rendernya sukses. Kalau gagal, ia
        # ditinggalkan sengaja — itu satu-satunya bukti yang bisa kamu buka
        # dan periksa sendiri untuk tahu apa yang salah.
        if self._sukses and SETTINGS.resolve_hapus:
            try:
                self.pm.DeleteProject(self.nama)
                log.info("project pinjaman dihapus: %s", self.nama)
            except Exception as e:  # noqa: BLE001
                log.warning("gagal menghapus project '%s': %s", self.nama, e)
        elif not self._sukses:
            log.warning("project '%s' sengaja ditinggalkan untuk diperiksa", self.nama)

        try:
            self.pm.GotoRootFolder()
            if self._nama_sebelumnya:
                if self.pm.LoadProject(self._nama_sebelumnya):
                    log.info("project semula dibuka kembali: %s", self._nama_sebelumnya)
                else:
                    log.warning(
                        "tidak bisa membuka kembali project '%s' — buka manual di Resolve",
                        self._nama_sebelumnya,
                    )
        except Exception as e:  # noqa: BLE001
            log.warning("gagal memulihkan project semula: %s", e)

        return False  # exception apa pun tetap diteruskan


class ResolveRenderer(Renderer):
    name = "resolve"

    def preflight(self) -> list[str]:
        masalah = FfmpegRenderer().preflight()
        try:
            _connect()
        except RenderError as exc:
            masalah.append(str(exc))
        return masalah

    def build(self, edl: EDL, work_dir: Path, output: Path) -> Path:
        work_dir.mkdir(parents=True, exist_ok=True)
        output.parent.mkdir(parents=True, exist_ok=True)

        # --- 1. Siapkan segmen bersih dengan ffmpeg ---
        # Sengaja dikerjakan SEBELUM menyentuh Resolve: bagian ini yang paling
        # lama dan paling mungkin gagal, dan tidak ada gunanya menahan sesi
        # Resolve selama itu berlangsung.
        helper = FfmpegRenderer()
        log.info("menyiapkan %d segmen CFR untuk Resolve", len(edl.cuts))
        segmen = [
            str((work_dir / helper._extract_segment(cut, i, edl, work_dir)).resolve())
            for i, cut in enumerate(edl.cuts)
        ]

        resolve = _connect()

        with _SesiPinjaman(resolve) as sesi:
            project = sesi.project

            project.SetSetting("timelineResolutionWidth", str(edl.resolution.width))
            project.SetSetting("timelineResolutionHeight", str(edl.resolution.height))
            project.SetSetting("timelineFrameRate", str(edl.fps))

            # --- 2. Impor dan susun ---
            sesi.pastikan_milik_kita()
            media_pool = project.GetMediaPool()
            items = media_pool.ImportMedia(segmen)
            if not items or len(items) != len(segmen):
                raise RenderError(
                    f"ImportMedia hanya mengembalikan {len(items or [])} dari {len(segmen)} klip."
                )

            timeline = media_pool.CreateEmptyTimeline(edl.timeline_name)
            if not timeline:
                raise RenderError(f"CreateEmptyTimeline('{edl.timeline_name}') gagal.")
            project.SetCurrentTimeline(timeline)

            # Segmen sudah dipotong persis oleh ffmpeg, jadi tiap klip masuk utuh —
            # tidak ada konversi detik->frame yang bisa meleset di sini.
            if not media_pool.AppendToTimeline(items):
                raise RenderError("AppendToTimeline mengembalikan False.")
            log.info("timeline tersusun: %d klip", len(items))

            # --- 3. Caption lewat Text+ (best-effort) ---
            if edl.captions and edl.caption_style.ada:
                sesi.pastikan_milik_kita()
                self._insert_captions(timeline, edl)

            # --- 4. Render ---
            sesi.pastikan_milik_kita()
            hasil = self._render(project, output)
            sesi.tandai_sukses()
            return hasil

    # ------------------------------------------------------------------

    def _insert_captions(self, timeline, edl: EDL) -> None:
        """Sisipkan Text+ per caption di track video 2.

        Ini bagian paling rapuh dari jalur Resolve: nama template ('Text+') harus
        ada di Effects Library, dan penempatannya bergantung pada posisi playhead.
        Kalau gagal, render tetap dilanjutkan tanpa caption — lebih baik keluar
        video tanpa teks daripada job gagal total.
        """
        try:
            fps = float(timeline.GetSetting("timelineFrameRate") or edl.fps)
            start_frame = int(timeline.GetStartFrame())

            if timeline.GetTrackCount("video") < 2:
                timeline.AddTrack("video")

            berhasil = 0
            for cap in edl.captions:
                frame = start_frame + int(round(cap.t * fps))
                timeline.SetCurrentTimecode(_frames_to_tc(frame, fps))

                item = timeline.InsertFusionTitleIntoTimeline("Text+")
                if not item:
                    continue

                comp = item.GetFusionCompByIndex(1)
                if comp:
                    tool = comp.FindToolByID("TextPlus")
                    if tool:
                        tool.SetInput("StyledText", cap.text)
                item.SetProperty("Duration", max(1, int(round(cap.durasi * fps))))
                berhasil += 1

            log.info("caption Text+ disisipkan: %d/%d", berhasil, len(edl.captions))
        except Exception as exc:  # noqa: BLE001 — API Resolve hanya kembalikan True/False
            log.warning("gagal menyisipkan caption Text+ (%s) — render dilanjut tanpa caption", exc)

    def _render(self, project, output: Path) -> Path:
        project.SetRenderSettings(
            {
                "TargetDir": str(output.parent.resolve()),
                "CustomName": output.stem,
                "FormatWidth": 1080,
                "FormatHeight": 1920,
            }
        )
        for preset in ("H.264 Master", "H.265 Master", "YouTube 1080p"):
            if project.LoadRenderPreset(preset):
                log.info("render preset: %s", preset)
                break
        else:
            log.warning("tidak ada render preset dikenal yang bisa dimuat — pakai default")

        job_id = project.AddRenderJob()
        if not job_id:
            raise RenderError("AddRenderJob mengembalikan nilai kosong.")
        if not project.StartRendering(job_id):
            raise RenderError("StartRendering mengembalikan False.")

        batas = time.time() + RENDER_TIMEOUT
        while project.IsRenderingInProgress():
            if time.time() > batas:
                # StopRendering dipanggil pada objek project MILIK KITA, bukan
                # pada aplikasi — antrean render project lain tidak terpengaruh.
                project.StopRendering()
                raise RenderError(
                    f"Render melewati batas {RENDER_TIMEOUT}s dan dihentikan paksa. "
                    "Kemungkinan besar ada dialog modal terbuka di Resolve "
                    "(media offline, codec tidak dikenali, atau project recovery)."
                )
            time.sleep(3)

        status = project.GetRenderJobStatus(job_id) or {}
        log.info("status render: %s", status)
        if str(status.get("JobStatus", "")).lower() not in {"complete", "completed", ""}:
            raise RenderError(f"Job render tidak selesai bersih: {status}")

        hasil = _find_output(output)
        if hasil is None:
            raise RenderError(
                f"Render dilaporkan selesai tapi tidak ada file bernama '{output.stem}.*' "
                f"di {output.parent}."
            )
        return hasil


def _frames_to_tc(frame: int, fps: float) -> str:
    f = int(round(fps))
    jam, sisa = divmod(frame, f * 3600)
    menit, sisa = divmod(sisa, f * 60)
    detik, frames = divmod(sisa, f)
    return f"{jam:02d}:{menit:02d}:{detik:02d}:{frames:02d}"


def _find_output(output: Path) -> Path | None:
    """Resolve menambahkan ekstensinya sendiri; cari file apa pun dengan stem yang sama."""
    if output.exists():
        return output
    kandidat = sorted(
        output.parent.glob(f"{output.stem}.*"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return kandidat[0] if kandidat else None
