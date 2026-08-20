"""Konfigurasi agent — semuanya bisa dioverride lewat environment variable."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path


def _muat_dotenv() -> None:
    """Muat agent/.env kalau ada, tanpa menimpa variabel yang sudah diset.

    Ditulis tangan alih-alih memakai python-dotenv karena agent ini sengaja
    ramping: satu file 20 baris tidak sebanding dengan menambah dependensi yang
    harus ikut terpasang di tiap mesin yang menjalankan agent.

    Yang sudah ada di environment SELALU menang. Menjalankan agent dengan
    variabel yang diset di terminal harus bisa menimpa isi file — kalau tidak,
    mengujinya terhadap server lain jadi menyusahkan.
    """
    berkas = Path(__file__).resolve().parent.parent / ".env"
    if not berkas.exists():
        return
    for baris in berkas.read_text(encoding="utf-8").splitlines():
        teks = baris.strip()
        if not teks or teks.startswith("#"):
            continue
        nama, pisah, nilai = teks.partition("=")
        if not pisah:
            continue
        nama = nama.removeprefix("export ").strip()
        if nama and nama not in os.environ:
            os.environ[nama] = nilai.strip().strip("\"'")


_muat_dotenv()


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _find(binary: str, env_name: str) -> str:
    """Cari binary di PATH, atau ambil dari env var kalau diset eksplisit."""
    explicit = os.environ.get(env_name)
    if explicit:
        return explicit
    found = shutil.which(binary)
    return found or binary


@dataclass
class Settings:
    # --- eksekusi ---
    renderer: str = field(default_factory=lambda: _env("RENDERER", "ffmpeg"))
    work_dir: Path = field(
        default_factory=lambda: Path(_env("SHORTSMITH_WORK_DIR", ".shortsmith"))
    )

    # Folder tempat agent mencari bahan mentah yang TIDAK diunggah.
    #
    # Di mode ini berkasnya tidak pernah menyentuh internet: ia dibaca langsung
    # dari disk dan dipakai di tempat, tanpa disalin. Sebelumnya satu berkas
    # 388 MB diunggah ke Backblaze lalu diunduh kembali oleh agent di PC yang
    # sama — berkeliling internet untuk berpindah antar folder di disk yang sama.
    bahan_dir: Path = field(
        default_factory=lambda: Path(_env("SHORTSMITH_BAHAN_DIR", "bahan"))
    )

    # Tempat salinan hasil render disimpan, dengan nama yang bisa dibaca.
    #
    # Hasilnya memang sudah ada di work dir, tapi di sana namanya "output.mp4"
    # di dalam folder ber-UUID — tidak mungkin ditemukan tanpa membuka log.
    # Tanpa salinan ini, satu-satunya cara menontonnya adalah mengunduhnya dari
    # Backblaze: memakai kuota untuk berkas yang sudah ada di disk yang sama.
    hasil_dir: Path = field(
        default_factory=lambda: Path(_env("SHORTSMITH_HASIL_DIR", "hasil"))
    )

    # --- binary eksternal ---
    ffmpeg: str = field(default_factory=lambda: _find("ffmpeg", "FFMPEG_PATH"))
    ffprobe: str = field(default_factory=lambda: _find("ffprobe", "FFPROBE_PATH"))

    # --- DaVinci Resolve ---
    # Resolve di mesin ini juga dipakai untuk pekerjaan lain, jadi jalur resolve
    # harus meminjam, bukan menempati. Tiga setelan di bawah yang menjaganya.
    #
    # resolve_folder  — semua project Shortsmith ditaruh di folder ini di Project
    #                   Manager, tidak dicampur dengan project pribadi.
    # resolve_hapus   — hapus project Shortsmith setelah render sukses. Kalau
    #                   dimatikan, project-nya tertinggal untuk diperiksa manual.
    # resolve_paksa   — kalau True, tetap jalan meski Resolve sedang sibuk.
    #                   Default False: lebih baik job antre daripada menyerobot
    #                   sesi edit yang sedang berjalan.
    resolve_folder: str = field(default_factory=lambda: _env("RESOLVE_FOLDER", "Shortsmith"))
    resolve_hapus: bool = field(
        default_factory=lambda: _env("RESOLVE_HAPUS_PROJECT", "1") not in {"0", "false", ""}
    )
    resolve_paksa: bool = field(
        default_factory=lambda: _env("RESOLVE_PAKSA", "0") not in {"0", "false", ""}
    )

    # --- transkrip ---
    # Default faster-whisper (CPU) berdasarkan pengukuran di Core Ultra 7 155H:
    # ia paling cepat DAN satu-satunya yang memberi timestamp per kata sungguhan.
    # Lihat README bagian "Hasil benchmark". Jalur openvino tetap tersedia.
    asr_backend: str = field(default_factory=lambda: _env("ASR_BACKEND", "faster-whisper"))
    whisper_language: str = field(default_factory=lambda: _env("WHISPER_LANGUAGE", "id"))

    # faster-whisper (CPU) — hanya dipakai kalau asr_backend = "faster-whisper"
    # "medium", bukan "small".
    #
    # `small` salah dengar di konteks panjang meski benar saat potongannya
    # diisolasi — terukur pada bahan pengguna, "lakukan" jadi "lakuannya" di
    # jendela 45 detik padahal benar di jendela 4 detik. Setelan dekoding tidak
    # menolong: beam lebih besar, tanpa VAD, dan condition_on_previous_text=False
    # semuanya tetap salah. Yang tersisa hanya model yang lebih besar.
    #
    # Ongkosnya transkrip lebih lama, tapi hasilnya di-cache per berkas — jadi
    # dibayar sekali per bahan, bukan tiap render.
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "small"))
    whisper_device: str = field(default_factory=lambda: _env("WHISPER_DEVICE", "cpu"))
    whisper_compute: str = field(default_factory=lambda: _env("WHISPER_COMPUTE", "int8"))

    # OpenVINO — GPU = Intel Arc iGPU, NPU = Intel AI Boost, CPU = fallback
    ov_device: str = field(default_factory=lambda: _env("OV_DEVICE", "GPU"))
    ov_model_dir: Path = field(
        default_factory=lambda: Path(_env("OV_MODEL_DIR", "models/whisper-small-ov"))
    )
    ov_hf_model: str = field(
        default_factory=lambda: _env("OV_HF_MODEL", "openai/whisper-small")
    )

    # --- LLM ---
    # decider:
    #   "claude-cli" — panggil `claude -p` (Claude Code headless). Memakai
    #                  kredensial langganan Claude, jadi TIDAK perlu API key
    #                  maupun kredit. Default, karena inilah yang tersedia.
    #   "api"        — SDK anthropic langsung. Butuh ANTHROPIC_API_KEY + kredit,
    #                  tapi memberi structured output yang dijamin valid.
    decider: str = field(default_factory=lambda: _env("DECIDER", "claude-cli"))
    model: str = field(default_factory=lambda: _env("SHORTSMITH_MODEL", "claude-opus-5"))
    cli_timeout: int = field(default_factory=lambda: int(_env("CLAUDE_CLI_TIMEOUT", "600")))

    # --- output ---
    width: int = 1080
    height: int = 1920
    fps: int = field(default_factory=lambda: int(_env("SHORTSMITH_FPS", "30")))

    def ensure_work_dir(self, job_id: str) -> Path:
        d = self.work_dir / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d


SETTINGS = Settings()
