"""Orkestrator: satu file video mentah -> satu short video.

Urutan tahapan sengaja dibalik dari draf konsep awal. Draf itu mentranscode
SELURUH rekaman ke codec perantara sebelum analisis; itu menghabiskan puluhan
gigabyte untuk rekaman 30 menit dan memakan menit-menit yang tidak perlu.

Di sini:

    1. probe        — metadata dasar
    2. analisis     — LANGSUNG dari file asli (whisper + silencedetect tidak
                      peduli VFR; keduanya bekerja dari audio)
    3. keputusan    — LLM memilih rentang waktu
    4. validasi     — clamp + tolak sebelum menyentuh renderer
    5. EDL          — caption diturunkan dari timestamp, musik dilampirkan
    6. render       — normalisasi CFR hanya untuk segmen yang terpilih

Hasilnya: dari 30 menit yang harus ditranscode, menjadi ~45 detik.

Setiap tahap menulis artefaknya ke work dir, dan tahap yang artefaknya sudah ada
akan dilewati. Iterasi prompt jadi murah — tidak perlu menjalankan Whisper ulang
setiap kali.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from . import cache_peta
from .analyze import build_map
from .captions import derive_captions
from .config import SETTINGS
from .decide import decide
from .models import (
    EDL,
    ConceptProfile,
    Cut,
    CutPlan,
    Music,
    ProjectMap,
    VideoMap,
    resolution_for,
)
from .renderer import get_renderer
from .wajah import lacak, periksa_adegan

log = logging.getLogger(__name__)


def load_profile(path: str | Path) -> ConceptProfile:
    return ConceptProfile.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, model) -> None:
    path.write_text(model.model_dump_json(indent=2, by_alias=True), encoding="utf-8")


def build_edl(
    plan: CutPlan,
    vmap: ProjectMap,
    profile: ConceptProfile,
    *,
    concept_id: str,
    music: str | None = None,
    music_gain_db: float = -20.0,
) -> EDL:
    """Ubah rencana potongan menjadi EDL lengkap yang siap dirender."""
    # Tiap potongan membawa nomor video sumbernya; di sinilah nomor itu
    # diterjemahkan kembali jadi path file yang benar.
    cuts: list[Cut] = []
    for c in plan.cuts:
        v = vmap.get(c.sumber)
        if v is None:
            raise ValueError(f"Potongan menunjuk sumber {c.sumber} yang tidak ada")
        # Bilah hitam, pengarahan ke wajah, dan tracking berlaku di SINI juga.
        #
        # Ketiganya sempat hanya ada di jalur overlay, sehingga konsep berformat
        # satu-jalur diam-diam kehilangan semuanya: bilah bawaan berkas ikut
        # terbawa, bingkai memotong dari tengah, dan subjek yang bergerak keluar
        # sendiri dari bingkai. Bentuk EDL-nya berbeda, tapi masalah gambarnya
        # persis sama, jadi penanganannya harus sama.
        temuan = periksa_adegan(
            v.media.path, mulai=c.in_, panjang=c.durasi, crop=v.media.crop
        )
        titik = lacak(v.media.path, mulai=c.in_, panjang=c.durasi, crop=v.media.crop)
        cuts.append(
            Cut(
                src=v.media.path,
                crop=v.media.crop,
                fokus_x=temuan.fokus_x if temuan else None,
                fokus_y=temuan.fokus_y if temuan else None,
                arah=temuan.arah if temuan else 0.0,
                jalur=[[round(t, 3), round(x, 4), round(y, 4)] for t, x, y in titik]
                if titik
                else [],
                **c.model_dump(by_alias=True),
            )
        )

    # Caption diturunkan per potongan dari kata-kata video ASALNYA masing-masing.
    kata_per_sumber = {i: v.words for i, v in enumerate(vmap.videos)}
    captions = derive_captions(cuts, kata_per_sumber, profile.caption)

    # Musik dipasang kalau diberikan.
    #
    # Sebelumnya jalur ini SELALU dilewati — keputusan lama ketika lagu memang
    # ditambahkan sendiri oleh pengguna setelah render. Sekarang lagu bisa
    # dipilih di form, jadi melewatinya berarti mengabaikan berkas yang sengaja
    # dikirim.
    #
    # Kekerasannya tetap datang dari jenis video lewat parameter, bukan angka
    # tetap di sini — walau ketiga jenis yang tersisa sama-sama memakai -20 dB,
    # yaitu latar yang terdengar tanpa menutupi ucapan.
    music_obj = None
    sumber_musik = music or profile.music_path
    if sumber_musik:
        music_obj = Music(src=str(sumber_musik), gain_db=music_gain_db)
        log.info("musik: %s @ %.0f dB", Path(sumber_musik).name, music_gain_db)

    # Rasio keluaran mengikuti konsep, bukan angka tetap di config. Konsep
    # "clipper 3:4" dan "vlog 9:16" bisa hidup berdampingan tanpa saling
    # mengganggu, dan tanpa perlu mengubah setelan apa pun saat berganti.
    resolusi = resolution_for(profile.aspect_ratio)
    log.info("rasio keluaran: %s (%dx%d)", profile.aspect_ratio, resolusi.width, resolusi.height)

    return EDL(
        timeline_name=f"short_{datetime.now():%Y%m%d_%H%M%S}",
        concept_id=concept_id,
        target_duration=profile.target_duration(),
        resolution=resolusi,
        fps=SETTINGS.fps,
        cuts=cuts,
        captions=captions,
        music=music_obj,
        caption_style=profile.caption,
    )


def run_banyak(
    sources,
    profile,
    output,
    *,
    jenis: str = "short",
    brief: str = "",
    job_id: str | None = None,
    on_progress=None,
    **kw,
) -> list[Path]:
    """Jalankan pipeline, menghasilkan BEBERAPA klip kalau topiknya dikosongkan.

    ## Kenapa klip pertama dijalankan lebih dulu, bukan semua sekaligus

    Topik hanya bisa dicari setelah ada transkrip, dan transkrip baru ada
    setelah tahap analisis berjalan. Menjalankan klip pertama seperti biasa
    memberi keduanya sekaligus: satu video yang sudah jadi, dan peta video yang
    dipakai untuk mencari topik sisanya.

    Konsekuensinya klip pertama memakai pilihan model sendiri tanpa arahan --
    persis perilaku sebelum fitur ini ada. Yang bertambah adalah klip-klip
    setelahnya.

    ## Kenapa ringkasan klip pertama ikut dikirim

    Supaya topik yang dicari BERBEDA darinya. Tanpa itu, model kemungkinan besar
    memilih bagian terbaik rekaman untuk klip kedua juga -- bagian yang sama
    yang baru saja dipakai.
    """
    import json as _json

    from .topik import boleh_dipecah, cari_topik, jumlah_klip

    output = Path(output).resolve()
    pertama = run(
        sources, profile, output,
        brief=brief, job_id=job_id, on_progress=on_progress, **kw,
    )
    if pertama is None or not boleh_dipecah(jenis, brief):
        return [pertama] if pertama else []

    work = SETTINGS.ensure_work_dir(
        job_id or f"{Path(str(sources[0] if isinstance(sources, list) else sources)).stem}"
    )
    peta = work / "map.json"
    if not peta.exists():
        return [pertama]

    vmap = ProjectMap.model_validate_json(peta.read_text(encoding="utf-8"))
    durasi = max((v.media.durasi for v in vmap.videos), default=0.0)
    n = jumlah_klip(durasi)
    if n <= 1:
        return [pertama]

    sudah = ""
    rencana = work / "plan.json"
    if rencana.exists():
        try:
            sudah = _json.loads(rencana.read_text(encoding="utf-8")).get("ringkasan") or ""
        except Exception:  # noqa: BLE001
            sudah = ""

    topik = cari_topik(vmap, profile, n - 1, sudah_dipakai=sudah)
    if not topik:
        return [pertama]

    hasil = [pertama]
    for i, t in enumerate(topik, start=2):
        keluar = output.with_name(f"{output.stem}-{i}{output.suffix}")
        log.info("=== klip %d dari %d: %s", i, len(topik) + 1, t[:90])
        try:
            # Kegagalan satu klip TIDAK menggagalkan sisanya. Klip pertama sudah
            # jadi dan sudah bernilai; membuang semuanya karena klip keempat
            # gagal berarti pengguna tidak mendapat apa pun.
            k = run(
                sources, profile, keluar,
                brief=t, job_id=job_id, sufiks=f"_{i}",
                on_progress=on_progress, **kw,
            )
            if k:
                hasil.append(k)
        except Exception:  # noqa: BLE001
            log.exception("klip %d gagal — dilewati", i)

    log.info("%d klip dihasilkan dari satu rekaman", len(hasil))
    return hasil


def run(
    sources: str | Path | list[str | Path],
    profile: ConceptProfile,
    output: str | Path,
    *,
    brief: str = "",
    job_id: str | None = None,
    music: str | None = None,
    music_gain_db: float = -20.0,
    renderer_name: str | None = None,
    refresh: bool = False,
    dry_run: bool = False,
    sufiks: str = "",
    on_progress: Callable[[int, str], None] | None = None,
) -> Path | None:
    """Jalankan pipeline penuh. Kembalikan path hasil, atau None kalau dry_run.

    `on_progress(persen, tahap)` dipanggil di setiap batas tahap. Daemon memakainya
    untuk mengisi heartbeat, sehingga UI bisa menampilkan kemajuan yang sebenarnya
    dan bukan sekadar spinner.
    """

    def lapor(persen: int, tahap: str) -> None:
        if on_progress:
            on_progress(persen, tahap)

    daftar = [sources] if isinstance(sources, (str, Path)) else list(sources)
    paths = [Path(x).resolve() for x in daftar]
    if not paths:
        raise ValueError("Tidak ada video mentah yang diberikan.")

    output = Path(output).resolve()
    job_id = job_id or f"{paths[0].stem}_{datetime.now():%Y%m%d_%H%M%S}"
    work = SETTINGS.ensure_work_dir(job_id)

    map_file = work / "map.json"
    # Rencana dan EDL diberi akhiran, petanya TIDAK.
    #
    # Inilah yang membuat beberapa klip dari satu rekaman jadi murah: analisis
    # (transkrip, deteksi adegan, pelabelan) adalah bagian yang makan puluhan
    # menit, dan ia bergantung pada BERKAS-nya saja -- bukan pada topik yang
    # dipilih. Dengan peta yang dipakai bersama dan rencana yang terpisah, klip
    # kedua dan seterusnya hanya membayar perencanaan dan render.
    plan_file = work / f"plan{sufiks}.json"
    edl_file = work / f"edl{sufiks}.json"

    # --- Tahap 1-2: analisis (di-cache) ---
    if map_file.exists() and not refresh:
        log.info("[1/5] memakai peta video dari cache: %s", map_file)
        vmap = ProjectMap.model_validate_json(map_file.read_text(encoding="utf-8"))
    else:
        log.info("[1/5] menganalisis %d video mentah", len(paths))

        # Backend transkrip dipilih dari gaya caption konsep INI, bukan dari
        # satu setelan global. Alasannya ada di `asr.backend_untuk`: caption
        # kata-per-kata hidup atau mati oleh presisi waktu kata, sedangkan
        # caption frasa tidak merasakannya sama sekali — jadi satu jawaban untuk
        # keduanya pasti salah di salah satu sisi.
        from .asr import backend_untuk

        asr_backend = backend_untuk(profile.caption.gaya, profile.caption.ada)
        log.info(
            "backend transkrip: %s (caption %s)",
            asr_backend,
            profile.caption.gaya if profile.caption.ada else "dimatikan",
        )

        videos: list[VideoMap] = []
        for i, path in enumerate(paths):
            # Cache per video: menambah video baru tidak memaksa transkrip ulang
            # video yang sudah pernah dianalisis. Untuk rekaman 1,5 jam, itu
            # menghemat ~22 menit per video setiap kali diulang.
            per_file = work / f"map_{i}.json"
            if per_file.exists() and not refresh:
                log.info("      VIDEO %d: dari cache (%s)", i, path.name)
                videos.append(VideoMap.model_validate_json(per_file.read_text(encoding="utf-8")))
                continue

            # Peran ditentukan posisi, bukan isi: VIDEO 0 adalah sumber suara,
            # sisanya hanya diambil gambarnya. Konsekuensinya besar — Whisper
            # hanya jalan sekali, bukan sekali per file. Untuk satu rekaman
            # pidato ditambah 20 klip B-roll, ini bedanya belasan menit
            # dibanding berjam-jam mentranskrip klip yang suaranya dibuang.
            broll = i > 0
            peran = "B-roll" if broll else "sumber suara"
            if broll:
                lapor(10 + int(35 * i / len(paths)), f"memeriksa klip {i}/{len(paths) - 1}")
            else:
                lapor(10, "transkrip sumber suara")
            log.info("      VIDEO %d [%s]: %s", i, peran, path.name)

            # Cache tingkat BERKAS, di atas cache per job di atasnya. Bahan yang
            # sama dipakai di banyak project, dan tanpa ini tiap project baru
            # mengulang transkrip Whisper dan pelabelan dari nol — dua puluh
            # menit dan sekantong token untuk jawaban yang sudah pernah didapat.
            v = None if refresh else cache_peta.ambil(path, broll=broll)
            if v is None:
                v = build_map(path, broll=broll, asr_backend=asr_backend)
                cache_peta.simpan(path, v, broll=broll)
            _write_json(per_file, v)
            videos.append(v)

        vmap = ProjectMap(videos=videos)
        _write_json(map_file, vmap)

    klip = vmap.videos[1:]
    log.info(
        "      sumber suara %.0f detik + %d klip B-roll (%.0f detik gambar)",
        vmap.videos[0].media.durasi, len(klip), sum(v.media.durasi for v in klip),
    )

    # --- Tahap 3-4: keputusan + validasi (di-cache) ---
    if plan_file.exists() and not refresh:
        log.info("[2/5] memakai rencana potongan dari cache: %s", plan_file)
        plan = CutPlan.model_validate_json(plan_file.read_text(encoding="utf-8"))
    else:
        log.info("[2/5] menyusun rencana potongan")
        lapor(45, "memilih potongan")
        plan = decide(vmap, profile, brief)
        _write_json(plan_file, plan)
    log.info("      %s", plan.ringkasan)

    # Batas dirapikan SETELAH cache rencana ditulis, bukan sebelumnya. Rencana
    # adalah keputusan editorial model; perapian adalah pengolahan sinyal.
    # Menyimpan yang sudah dirapikan akan membuat perapian berjalan berkali-kali
    # di atas hasilnya sendiri setiap kali cache dipakai ulang.
    from .rapikan import rapikan_batas, rapikan_energi, rapikan_kata

    # Dua lapis, dan urutannya penting.
    #
    # Lapis pertama memakai jeda hening dari silencedetect — hanya berguna untuk
    # batas yang kebetulan dekat jeda panjang (>0,45 detik), yaitu minoritas.
    #
    # Lapis kedua mengukur energi audio langsung di sekitar tiap batas. Ia yang
    # menangani mayoritas: timestamp Whisper sistematis menaruh batas SEBELUM
    # ekor kata habis, sehingga potongan memenggal kata di tengah peluruhannya.
    # Diukur pada satu job nyata, level di batas turun dari -36 dB ke -60 dB.
    # Urutan: keluar dari tengah kata DULU, baru dua perapian halus di atasnya.
    rapikan_kata(plan.cuts, vmap.videos[0].words)
    rapikan_batas(plan.cuts, vmap.videos[0].silences, vmap.videos[0].words)
    rapikan_energi(plan.cuts, vmap.videos[0].media.path, vmap.videos[0].words)

    # --- Tahap 5: bangun EDL ---
    # Bentuk EDL dan renderer ditentukan oleh format konsep, bukan oleh setelan
    # terpisah. Keduanya harus cocok — OverlayEDL tidak bisa dirender renderer
    # satu jalur dan sebaliknya — jadi mereka dipilih di satu tempat yang sama.
    log.info("[3/5] menyusun EDL")
    ada_klip = len(vmap.videos) > 1

    if profile.format == "auto":
        # Konsep lama tidak menyimpan format. Yang menentukan adalah bahannya:
        # klip B-roll yang diunggah berarti klip itu memang ingin dipakai.
        pakai_overlay = ada_klip
        log.info(
            "format konsep 'auto' -> %s (%d klip B-roll diunggah)",
            "overlay" if pakai_overlay else "satu-jalur", len(vmap.videos) - 1,
        )
    else:
        pakai_overlay = profile.format == "overlay" and ada_klip
        if profile.format == "overlay" and not ada_klip:
            log.warning(
                "konsep berformat overlay tapi tidak ada klip B-roll yang diunggah "
                "— jatuh ke format satu jalur"
            )
        elif profile.format == "satu-jalur" and ada_klip:
            # Jangan diam-diam. Pengguna mengunggah klip lalu tidak melihatnya
            # muncul; ia berhak tahu kenapa, dan bagaimana mengubahnya.
            log.warning(
                "%d klip B-roll diunggah tapi konsep '%s' berformat satu-jalur, "
                "jadi klipnya TIDAK DIPAKAI. Kirim ulang video contoh untuk "
                "membuat konsep berformat overlay.",
                len(vmap.videos) - 1, profile.nama,
            )

    if pakai_overlay:
        from .overlay import build_overlay_edl

        edl = build_overlay_edl(plan, vmap, profile, concept_id=profile.nama)
        renderer_name = renderer_name or "overlay"
        for i, s in enumerate(edl.video, 1):
            log.info("      %2d. t=%6.2f (%4.1fs) <- %s @ %.2f",
                     i, s.t, s.durasi, Path(s.src).name, s.in_)
    else:
        edl = build_edl(
            plan, vmap, profile,
            concept_id=profile.nama,
            music=music,
            music_gain_db=music_gain_db,
        )
        for i, c in enumerate(edl.cuts, 1):
            log.info("      %2d. [%-8s] vid%d %6.2f-%6.2f (%4.1fs)  %s",
                     i, c.role.value, c.sumber, c.in_, c.out, c.durasi, c.alasan)

    # Perataan eksposur sebelum EDL ditulis, supaya keputusannya ikut tersimpan
    # di edl.json dan bisa diperiksa — sama seperti keputusan potongan lainnya.
    from .warna import ratakan_edl

    lapor(66, "meratakan warna")
    n_warna = ratakan_edl(edl)
    if n_warna:
        log.info("[4/5] warna: %d potongan diratakan eksposurnya", n_warna)

    _write_json(edl_file, edl)
    log.info(
        "      format %s, %.1fs, %d caption",
        profile.format if pakai_overlay else "satu-jalur",
        edl.total_duration, len(edl.captions),
    )

    if dry_run:
        log.info("[4/5] dry run — berhenti sebelum render. EDL: %s", edl_file)
        return None

    # --- Tahap 6: render ---
    renderer = get_renderer(renderer_name)
    log.info("[4/5] renderer: %s", renderer.name)
    masalah = renderer.preflight()
    if masalah:
        raise RuntimeError("Preflight gagal:\n  - " + "\n  - ".join(masalah))

    # Hasil render dipakai ulang kalau sudah ada DAN lebih baru dari EDL-nya.
    #
    # Ini yang membuat percobaan ulang jadi murah. Kalau unggahan hasil gagal,
    # job tidak pernah ditandai selesai dan server membagikannya lagi; tanpa
    # pemeriksaan ini, agent merender ulang 80 detik hanya untuk menghasilkan
    # berkas yang isinya sama persis.
    #
    # Syarat "lebih baru dari EDL" penting: EDL adalah satu-satunya masukan
    # render, jadi selama ia tidak berubah, hasilnya pasti sama. Kalau EDL
    # diperbarui, hasil lama otomatis dianggap basi.
    if (
        not refresh
        and output.exists()
        and output.stat().st_size > 0
        and edl_file.exists()
        and output.stat().st_mtime >= edl_file.stat().st_mtime
    ):
        log.info("[5/5] hasil render sudah ada dan masih sesuai EDL — dipakai ulang")
        hasil = output
        lapor(90, "render selesai")
    else:
        log.info("[5/5] render")
        lapor(70, "render")
        hasil = renderer.build(edl, work, output)
        lapor(90, "render selesai")

    # Periksa HASILNYA, bukan rencananya.
    #
    # Seluruh perapian batas bekerja pada timestamp yang menunjuk ke rekaman
    # sumber. Yang didengar orang adalah berkas ini, dan di antara keduanya
    # masih ada renderer, fade, dan pembulatan ke grid frame. Tiap kali ada
    # laporan "ada suara bocor di detik sekian", pemeriksaannya selalu berakhir
    # di sini — jadi lebih baik dijalankan sendiri, setiap kali.
    from .periksa_hasil import laporkan

    laporkan(hasil, edl)

    ringkasan = {
        "job_id": job_id,
        "sources": [str(x) for x in paths],
        "output": str(hasil),
        "concept": profile.nama,
        "renderer": renderer.name,
        "durasi": round(edl.total_duration, 2),
        # Dua bentuk EDL menyimpan potongan di tempat berbeda: EDL biasa di
        # `cuts`, OverlayEDL di `audio.cuts` karena jalur gambarnya terpisah.
        "jumlah_potongan": len(edl.audio.cuts) if pakai_overlay else len(edl.cuts),
        "jumlah_slot_gambar": len(edl.video) if pakai_overlay else None,
        "jumlah_caption": len(edl.captions),
        "ringkasan": plan.ringkasan,
    }
    (work / "hasil.json").write_text(
        json.dumps(ringkasan, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return hasil
