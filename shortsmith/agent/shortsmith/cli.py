"""Antarmuka baris perintah.

    python -m shortsmith.cli doctor
    python -m shortsmith.cli prepare-model --device NPU
    python -m shortsmith.cli concept --nama vlog-cepat --samples a.mp4 b.mp4 -o concepts/vlog.json
    python -m shortsmith.cli render rekaman.mp4 --concept concepts/vlog.json -o hasil.mp4
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .config import SETTINGS
from .identitas import IDENTITAS, model_untuk
from .models import CaptionStyle, ManualFields


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)


# --------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    """Periksa lingkungan sebelum menjalankan job apa pun."""
    from .asr import available_devices
    from .probe import preflight

    print("== Binary ==")
    masalah = preflight()
    if masalah:
        for m in masalah:
            print(f"  [X] {m}")
    else:
        print(f"  [ok] ffmpeg   {SETTINGS.ffmpeg}")
        print(f"  [ok] ffprobe  {SETTINGS.ffprobe}")

    print("\n== Backend transkrip ==")
    print(f"  backend      : {SETTINGS.asr_backend}")
    if SETTINGS.asr_backend == "openvino":
        devices = available_devices()
        if devices:
            print(f"  device OV    : {SETTINGS.ov_device}  (tersedia: {', '.join(devices)})")
            if SETTINGS.ov_device.upper() not in devices:
                print(f"  [X] device '{SETTINGS.ov_device}' tidak terdeteksi")
                masalah.append("device OpenVINO tidak tersedia")
        else:
            print("  [X] openvino belum terpasang")
            masalah.append("openvino belum terpasang")

        model_dir = Path(SETTINGS.ov_model_dir)
        if model_dir.exists():
            print(f"  [ok] model   : {model_dir}")
        else:
            print(f"  [X] model belum ada: {model_dir}")
            print("      jalankan: python -m shortsmith.cli prepare-model")
            masalah.append("model OpenVINO belum dikonversi")
    else:
        try:
            import faster_whisper  # noqa: F401

            print(f"  [ok] faster-whisper (model={SETTINGS.whisper_model}, CPU)")
        except ImportError:
            print("  [X] faster-whisper belum terpasang")
            masalah.append("faster-whisper belum terpasang")

    print("\n== Sambungan ke server ==")
    api_url = os.environ.get("SHORTSMITH_API_URL", "").strip()
    agent_key = os.environ.get("AGENT_KEY", "").strip()
    if api_url:
        print(f"  [ok] SHORTSMITH_API_URL : {api_url}")
    else:
        print("  [X] SHORTSMITH_API_URL belum diset")
        masalah.append("SHORTSMITH_API_URL belum diset")
    # Panjangnya saja yang dicetak — cukup untuk membedakan "kosong" dari
    # "terisi tapi terpotong", tanpa menaruh kuncinya di layar atau di log.
    if agent_key:
        print(f"  [ok] AGENT_KEY          : terisi ({len(agent_key)} karakter)")
    else:
        print("  [X] AGENT_KEY belum diset")
        masalah.append("AGENT_KEY belum diset")

    print("\n== Keputusan editing ==")
    print(f"  backend      : {SETTINGS.decider}")

    print("\n== Bahan lokal ==")
    bahan = SETTINGS.bahan_dir.resolve()
    if bahan.is_dir():
        berkas = sorted(p.name for p in bahan.iterdir() if p.is_file())
        print(f"  [ok] folder : {bahan}")
        print(f"       isi    : {len(berkas)} berkas")
        for n in berkas[:8]:
            print(f"                {n}")
        if len(berkas) > 8:
            print(f"                ... dan {len(berkas) - 8} lagi")
    else:
        # Bukan kegagalan: jalur unggah tetap jalan tanpa folder ini. Karena itu
        # tidak ditambahkan ke daftar `masalah`.
        print(f"  [-] folder belum ada: {bahan}")
        print("       Buat foldernya kalau ingin memakai mode bahan lokal, atau")
        print("       set SHORTSMITH_BAHAN_DIR ke folder yang sudah ada.")

    print("\n== Identitas agent ==")
    for ident in IDENTITAS.values():
        model = model_untuk(ident.nama) if ident.pakai_llm else ident.keterangan_model
        print(f"  {ident.nama:<9}: {model}")

    if SETTINGS.decider == "claude-cli":
        import shutil as _shutil

        claude = _shutil.which("claude")
        if claude:
            print(f"  [ok] claude  : {claude}")
            print("       memakai kredensial langganan Claude, tidak perlu API key")
        else:
            print("  [X] perintah `claude` tidak ada di PATH")
            masalah.append("claude CLI tidak ditemukan")
    else:
        try:
            import anthropic  # noqa: F401

            print("  [ok] SDK anthropic terpasang")
        except ImportError:
            print("  [X] SDK anthropic belum terpasang (pip install anthropic)")
            masalah.append("anthropic belum terpasang")

        if os.environ.get("ANTHROPIC_API_KEY"):
            print("  [ok] ANTHROPIC_API_KEY terset")
        else:
            print("  [X] ANTHROPIC_API_KEY kosong")
            masalah.append("ANTHROPIC_API_KEY belum diset")

    print("\n== Renderer ==")
    print(f"  aktif: {SETTINGS.renderer}")
    if SETTINGS.renderer == "resolve":
        from .renderer import get_renderer

        for m in get_renderer("resolve").preflight():
            print(f"  [X] {m}")

    print()
    if masalah:
        print(f"{len(masalah)} masalah harus dibereskan sebelum menjalankan job.")
        return 1
    print("Semua siap.")
    return 0


def cmd_prepare_model(args: argparse.Namespace) -> int:
    """Konversi model Whisper HuggingFace ke OpenVINO IR."""
    from .asr import export_openvino_model

    out_dir = Path(args.out or SETTINGS.ov_model_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    export_openvino_model(
        args.hf_model or SETTINGS.ov_hf_model,
        out_dir,
        device=args.device,
        weight_format=args.weight_format,
    )
    print(f"\nModel siap di {out_dir}")
    print(f"Pakai dengan:  set OV_MODEL_DIR={out_dir}  &&  set OV_DEVICE={args.device}")
    return 0


def cmd_concept(args: argparse.Namespace) -> int:
    """Ekstrak concept profile dari beberapa video contoh."""
    from .profile import extract_profile

    profile = extract_profile(
        args.samples,
        nama=args.nama,
        fokus=args.fokus,
        caption=CaptionStyle(posisi=args.caption_posisi, gaya=args.caption_gaya),
        music_path=args.music,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    print(f"Konsep '{profile.nama}' tersimpan di {out}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    from .pipeline import load_profile, run

    profile = load_profile(args.concept)
    hasil = run(
        args.source,
        profile,
        args.out,
        brief=args.brief,
        music=args.music,
        renderer_name=args.renderer,
        refresh=args.refresh,
        dry_run=args.dry_run,
    )
    if hasil:
        print(f"\nSelesai: {hasil}")
    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    """Jalankan agent sebagai daemon yang polling job dari web."""
    from .api import ApiClient
    from .daemon import Daemon

    api = ApiClient(base_url=args.api_url, agent_key=args.agent_key)
    Daemon(api).run_forever()
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    """Hanya jalankan analisis dan tulis peta video — berguna untuk debugging."""
    from .analyze import build_map

    vmap = build_map(args.source, skip_transcript=args.no_transcript)
    out = Path(args.out or "map.json")
    out.write_text(vmap.model_dump_json(indent=2), encoding="utf-8")
    print(f"Peta video: {out}  ({len(vmap.segments)} segmen, {len(vmap.silences)} jeda)")
    return 0


# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="shortsmith", description="Agent pembuat short video otomatis."
    )
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Periksa kesiapan lingkungan").set_defaults(func=cmd_doctor)

    pm = sub.add_parser("prepare-model", help="Konversi Whisper ke OpenVINO (iGPU/NPU)")
    pm.add_argument("--device", default="GPU", choices=["GPU", "NPU", "CPU"],
                    help="GPU=Intel Arc, NPU=Intel AI Boost. NPU butuh ekspor statis.")
    pm.add_argument("--hf-model", default=None, help="mis. openai/whisper-small")
    pm.add_argument("--weight-format", default="int8", choices=["fp16", "int8", "int4"])
    pm.add_argument("-o", "--out", default=None)
    pm.set_defaults(func=cmd_prepare_model)

    pc = sub.add_parser("concept", help="Buat concept profile dari video contoh")
    pc.add_argument("--nama", required=True)
    pc.add_argument("--samples", nargs="+", required=True, help="minimal 2 video contoh")
    pc.add_argument("-o", "--out", required=True)
    pc.add_argument(
        "--fokus",
        default="",
        help="opsional; kalau diisi, hanya bagian yang membahas topik ini yang dipakai",
    )
    pc.add_argument("--music", default=None)
    pc.add_argument("--caption-posisi", default="tengah-bawah",
                    choices=["tengah-bawah", "tengah", "atas"])
    pc.add_argument("--caption-gaya", default="frasa", choices=["frasa", "kata-per-kata"])
    pc.set_defaults(func=cmd_concept)

    pd = sub.add_parser("daemon", help="Jalankan agent sebagai daemon (ambil job dari web)")
    pd.add_argument("--api-url", default=None, help="default: env SHORTSMITH_API_URL")
    pd.add_argument("--agent-key", default=None, help="default: env AGENT_KEY")
    pd.set_defaults(func=cmd_daemon)

    pa = sub.add_parser("analyze", help="Analisis saja, tanpa render")
    pa.add_argument("source")
    pa.add_argument("-o", "--out", default=None)
    pa.add_argument("--no-transcript", action="store_true")
    pa.set_defaults(func=cmd_analyze)

    pr = sub.add_parser("render", help="Pipeline penuh: video mentah -> short video")
    pr.add_argument("source")
    pr.add_argument("--concept", required=True, help="path concept profile .json")
    pr.add_argument("-o", "--out", default="output.mp4")
    pr.add_argument("--brief", default="", help="instruksi tambahan untuk job ini")
    pr.add_argument("--music", default=None)
    pr.add_argument("--renderer", default=None, choices=["ffmpeg", "resolve"])
    pr.add_argument("--refresh", action="store_true", help="abaikan cache analisis & rencana")
    pr.add_argument("--dry-run", action="store_true", help="berhenti setelah EDL dibuat")
    pr.set_defaults(func=cmd_render)

    return p


def main(argv: list[str] | None = None) -> int:
    # Konsol Windows default cp1252, sementara pesan log memakai em-dash dan
    # tanda kutip tipografis. Tanpa ini, log daemon yang dipandangi berjam-jam
    # penuh karakter rusak. Diperbaiki di satu tempat, bukan dengan mengubah
    # setiap kalimat jadi ASCII.
    for aliran in (sys.stdout, sys.stderr):
        try:
            aliran.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError):
            # Aliran yang dialihkan ke pipa atau file bisa tidak mendukungnya.
            # Itu bukan alasan untuk menggagalkan perintah.
            pass

    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nDibatalkan.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        logging.getLogger("shortsmith").error("%s: %s", type(exc).__name__, exc)
        if args.verbose:
            raise
        return 1


if __name__ == "__main__":
    sys.exit(main())
