"""Ekstraksi concept profile dari 2-4 video contoh yang sudah jadi.

Di sinilah PySceneDetect memang tepat: video contoh SUDAH diedit, jadi ia benar-benar
punya potongan keras untuk dideteksi. (Bandingkan dengan video mentah satu-take, yang
tidak punya satu pun — itu sebabnya scenedetect tidak dipakai di analyze.py.)

Kenapa minimal dua video: satu video adalah sampel n=1. Dengan beberapa video kita
bisa menghitung rata-rata DAN standar deviasi — dan deviasi itu sendiri informatif
(rendah = ritme metronomik, tinggi = ritme dinamis).
"""

from __future__ import annotations

import logging
import statistics
from pathlib import Path

from .models import (
    CaptionStyle,
    ConceptProfile,
    ManualFields,
    MetricStat,
    Role,
    rasio_terdekat,
)
from .format_video import deteksi_dari_file
from .gaya_visual import ukur_gaya
from .pelajari import pelajari_caption
from .probe import probe

log = logging.getLogger(__name__)

MIN_SAMPEL = 2


class ProfileError(RuntimeError):
    pass


def _detect_cuts(path: str | Path) -> list[float]:
    """Kembalikan panjang tiap shot (detik) di satu video contoh."""
    try:
        from scenedetect import ContentDetector, detect
    except ImportError as exc:
        raise ProfileError(
            "PySceneDetect belum terpasang. Jalankan: pip install 'scenedetect[opencv]'"
        ) from exc

    scenes = detect(str(path), ContentDetector(threshold=27.0))
    return [
        (end.get_seconds() - start.get_seconds())
        for start, end in scenes
        if end.get_seconds() > start.get_seconds()
    ]


def _stat(values: list[float]) -> MetricStat:
    if not values:
        return MetricStat(mean=0.0, std=0.0)
    return MetricStat(
        mean=round(statistics.fmean(values), 3),
        std=round(statistics.pstdev(values) if len(values) > 1 else 0.0, 3),
    )


def _rasio_terbanyak(rasio: list[str]) -> str:
    """Rasio yang paling sering muncul; kalau seri, yang paling TEGAK menang.

    Aturan seri ini bukan selera. Alat ini membuat short, dan short ditonton di
    ponsel dalam posisi tegak. Kalau dua contoh sama-sama satu suara, memilih
    yang lanskap menghasilkan video yang salah bentuk untuk tempat tayangnya —
    kegagalan yang jauh lebih mahal daripada memilih yang terlalu tegak.

    Sebelum ada aturan ini, pemenang seri ditentukan urutan set Python, yang
    tidak dijamin apa pun. Dua contoh 3:4 dan 16:9 menghasilkan 16:9.
    """
    if not rasio:
        return "9:16"

    from .models import RASIO

    terbanyak = max(rasio.count(r) for r in set(rasio))
    calon = [r for r in set(rasio) if rasio.count(r) == terbanyak]

    def ketegakan(nama: str) -> float:
        res = RASIO.get(nama)
        return res.width / res.height if res else 1.0

    return min(calon, key=ketegakan)


def extract_profile(
    sample_paths: list[str | Path],
    *,
    nama: str,
    fokus: str = "",
    manual: ManualFields | None = None,
    caption: CaptionStyle | None = None,
    struktur: list[Role] | None = None,
    music_path: str | None = None,
    aspect_ratio: str | None = None,
) -> ConceptProfile:
    """Analisis video contoh menjadi satu ConceptProfile."""
    if not sample_paths:
        raise ProfileError("Tidak ada video contoh yang diberikan.")

    if len(sample_paths) < MIN_SAMPEL:
        # Dulu ini error keras. Sekarang peringatan: user boleh sengaja memilih
        # satu video ("buatkan seperti ini"), dan menggagalkan job untuk itu
        # lebih merugikan daripada membiarkannya jalan dengan profil yang lemah.
        # Yang hilang bukan rata-ratanya, melainkan deviasinya — dengan n=1,
        # std selalu 0, sehingga sinyal ritme ke model jadi datar.
        log.warning(
            "hanya %d video contoh. Rata-rata tetap terukur, tapi deviasi tidak "
            "(std = 0), jadi sinyal ritme ke model lebih lemah. Dua video atau "
            "lebih memberi hasil yang lebih mewakili.",
            len(sample_paths),
        )

    durasi_total: list[float] = []
    avg_shot: list[float] = []
    jumlah_cut: list[float] = []
    hook: list[float] = []
    rasio: list[str] = []
    format_terdeteksi: list[str] = []
    porsi: list[float] = []
    penggal: list[float] = []
    caption_terbaca: CaptionStyle | None = None

    for path in sample_paths:
        media = probe(path)
        shots = _detect_cuts(path)

        durasi_total.append(media.durasi)
        jumlah_cut.append(float(max(0, len(shots) - 1)))
        if shots:
            avg_shot.append(statistics.fmean(shots))
            # Hook = shot pertama; itu definisi yang bisa diukur, bukan tebakan.
            hook.append(shots[0])
        if media.height:
            rasio.append(rasio_terdekat(media.width, media.height))

        # Hanya hasil yang meyakinkan yang ikut memilih. Contoh yang datanya
        # terlalu tipis untuk disimpulkan tidak boleh menyeret keputusan.
        fmt = deteksi_dari_file(path)
        if fmt.yakin:
            format_terdeteksi.append(fmt.format)
        if fmt.penggal_suara:
            penggal.append(float(fmt.penggal_suara))

        # Berapa banyak contohnya menampilkan satu tampilan yang berulang —
        # itulah pembicara. Nol berarti montase penuh tanpa talking-head.
        gaya = ukur_gaya(path, shots)
        log.info("gaya visual %s: %s", Path(path).name, gaya.ringkas())
        porsi.append(gaya.porsi_berulang)

        # Gaya caption dibaca dari contoh PERTAMA saja. Ia tidak berubah antar
        # video dalam satu konsep, dan membacanya berulang kali hanya menambah
        # biaya tanpa menambah keyakinan.
        if caption is None and caption_terbaca is None:
            caption_terbaca = pelajari_caption(path, shots)

        log.info(
            "contoh %s: %.1fs, %d shot, rata-rata %.2fs",
            Path(path).name, media.durasi, len(shots),
            statistics.fmean(shots) if shots else 0.0,
        )

    # Rasio: kalau user memilih eksplisit, hormati pilihannya. Kalau "auto"
    # (atau kosong), ambil dari video contoh — yang paling sering muncul menang.
    # Tanpa sentinel ini, deteksi akan selalu menimpa pilihan user, karena
    # ekstraksi menulis ulang seluruh profil.
    pilihan = (aspect_ratio or "auto").strip()
    if pilihan and pilihan != "auto":
        aspect = pilihan
        log.info("rasio ditetapkan user: %s", aspect)
    else:
        aspect = _rasio_terbanyak(rasio)
        if len(set(rasio)) > 1:
            # Contoh yang berbeda rasio biasanya berarti gaya yang berbeda juga.
            # Dikatakan terus terang supaya pengguna bisa memutuskan, bukan
            # dibiarkan menemukan sendiri setelah videonya jadi lanskap.
            log.warning(
                "video contoh punya rasio berbeda (%s) — dipilih %s. "
                "Untuk hasil yang konsisten, pakai contoh dengan rasio yang sama.",
                ", ".join(sorted(set(rasio))), aspect,
            )
        log.info("rasio dideteksi dari video contoh: %s", aspect)

    # Kalau contohnya terbagi rata antara dua format, dimenangkan "overlay":
    # ia bisa meniru satu jalur (klip diambil dari rekaman suaranya sendiri),
    # sedangkan satu jalur tidak akan pernah bisa meniru overlay.
    if format_terdeteksi:
        format_video = (
            "overlay"
            if format_terdeteksi.count("overlay") * 2 >= len(format_terdeteksi)
            else "satu-jalur"
        )
    else:
        format_video = "satu-jalur"
    log.info("format konsep: %s", format_video)

    porsi_pembicara = statistics.fmean(porsi) if porsi else 0.0
    log.info("porsi pembicara: %.0f%%", porsi_pembicara * 100)

    profile = ConceptProfile(
        nama=nama,
        format=format_video,
        porsi_pembicara=round(porsi_pembicara, 3),
        metrik={
            "durasi_total": _stat(durasi_total),
            "avg_shot_length": _stat(avg_shot),
            "jumlah_cut": _stat(jumlah_cut),
            # Jumlah SAMBUNGAN SUARA, bukan pergantian gambar. Dua besaran yang
            # sama sekali berbeda: satu contoh punya 22 shot tapi 4 penggal suara.
            "penggal_suara": _stat(penggal),
            "hook_duration": _stat(hook),
        },
        aspect_ratio=aspect,
        # Urutan menang: pilihan eksplisit user > hasil membaca contoh > bawaan.
        caption=caption or caption_terbaca or CaptionStyle(),
        struktur=struktur or [Role.hook, Role.konteks, Role.isi, Role.cta],
        manual=manual or ManualFields(fokus=fokus),
        music_path=music_path,
    )

    asl = profile.metrik["avg_shot_length"]
    if asl.mean:
        log.info(
            "profil '%s': target %.0fs, %.0f cut, shot %.2fs (deviasi %.2f)",
            nama, profile.metrik["durasi_total"].mean, profile.metrik["jumlah_cut"].mean,
            asl.mean, asl.std,
        )
    return profile
