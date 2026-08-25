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
import os
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


def _tanpa_ganda(paths: list[Path]) -> list[Path]:
    """Buang berkas yang muncul dua kali. Urutan yang tersisa tidak berubah.

    ## Kenapa rekaman suara TIDAK boleh ikut jadi klip B-roll

    Peran ditentukan posisi: berkas pertama adalah sumber suara, sisanya diambil
    gambarnya saja. Memilih berkas yang sama untuk keduanya terdengar seperti
    "pakai rekaman itu untuk dua-duanya", tapi yang terjadi bukan itu.

    Wajah pembicara sudah punya jalurnya sendiri, dan jalur itu SINKRON: slot
    pembicara mengambil gambar dari detik yang sama dengan suara yang sedang
    terdengar, jadi gerak bibirnya cocok (lihat `_sumber_pada` di overlay.py).
    Adegan B-roll tidak begitu — ia diambil dari titik mana pun di berkasnya.

    Jadi rekaman suara yang dimasukkan sebagai B-roll menghasilkan satu-satunya
    hal yang dijaga ketat di seluruh modul overlay: orang yang terlihat sedang
    mengucapkan kalimat dari menit 24 sementara yang terdengar menit 2.

    ## Kenapa dibuang, bukan ditolak

    Menolak job berarti pengguna harus mengirim ulang untuk sesuatu yang
    maksudnya sudah jelas. Yang ia maksud adalah "pakai rekaman ini, tiru
    konsepnya" — dan itu persis format satu jalur, yang akan dipilih sendiri
    begitu daftar klipnya kosong.

    Berlaku untuk SEMUA jenis video. Tidak ada jenis yang diuntungkan oleh
    gambar pembicara yang tidak sinkron dengan suaranya.
    """
    terlihat: dict[str, int] = {}
    hasil: list[Path] = []
    for p in paths:
        kunci = os.path.normcase(str(p))
        if kunci in terlihat:
            # Dua sebab yang berbeda, dan pengguna perlu tahu yang MANA. Yang
            # pertama mengubah bentuk videonya (klipnya habis, jadi satu jalur);
            # yang kedua cuma pemborosan yang tidak terlihat di hasil.
            if terlihat[kunci] == 0:
                log.info(
                    "%s dipilih sebagai sumber suara SEKALIGUS klip B-roll — "
                    "salinan klipnya dibuang. Wajah pembicara tetap muncul, "
                    "lewat jalur yang sinkron dengan suaranya.",
                    p.name,
                )
            else:
                log.info("%s dipilih dua kali sebagai klip — salinannya dibuang", p.name)
            continue
        terlihat[kunci] = len(hasil)
        hasil.append(p)
    return hasil


def _lapor_klip(on_klip: Callable[[Path], None] | None, k: Path) -> None:
    """Beri tahu pemanggil bahwa satu klip sudah jadi, TANPA menunggu jawabannya.

    Gunanya menumpangkan unggahan di atas render. Diukur pada job podcast lima
    klip, 1.575 detik::

        unggah 5 hasil     714 detik   45%
        pilih potongan     430 detik   27%
        encode akhir       248 detik   16%
        render potongan    125 detik    8%
        susun EDL           84 detik    5%

    Seluruh 714 detik itu berjalan SETELAH klip terakhir selesai dirender —
    lima unggahan berurutan, satu per satu, sementara CPU menganggur. Padahal
    klip pertama sudah jadi 12 menit sebelumnya dan tidak berubah lagi.

    Kegagalan di sini ditelan. Pemberitahuan ini kenyamanan penjadwalan, bukan
    bagian dari hasil: klip yang gagal diunggah lewat jalur ini tetap ada di
    disk dan tetap dikembalikan `run_banyak`, jadi pemanggil masih punya
    kesempatan mengunggahnya di akhir. Membiarkannya melempar berarti satu
    gangguan jaringan menghentikan render klip berikutnya, dan itu menukar
    sesuatu yang mahal dengan sesuatu yang murah.
    """
    if on_klip is None:
        return
    try:
        on_klip(k)
    except Exception:  # noqa: BLE001
        log.warning("pemberitahuan klip selesai gagal — render diteruskan", exc_info=True)


def siapkan_musik(
    music: str | None, profile: ConceptProfile, gain_db: float
) -> Music | None:
    """Rakit objek Music, atau None kalau tidak ada lagu yang dipilih.

    ## Kenapa fungsi tersendiri

    Dua format EDL membutuhkannya, dan sebelum ini hanya SATU yang punya. Musik
    dibangun di dalam `build_edl`, sementara `build_overlay_edl` dipanggil dari
    tempat lain dan tidak pernah menerimanya — jadi lagu yang dipilih pengguna
    hilang diam-diam di seluruh jenis video yang memakai format overlay, yaitu
    short dan podcast.

    Menaruhnya di satu tempat membuat kelalaian yang sama tidak bisa terulang:
    jalur mana pun yang butuh musik memanggil fungsi ini, bukan menyalin
    langkah-langkahnya.
    """
    sumber = music or profile.music_path
    if not sumber:
        return None

    # Path MUTLAK. Renderer menjalankan ffmpeg dengan cwd di work dir, jadi path
    # relatif -- yang mungkin datang dari `profile.music_path` -- gagal dibuka di
    # sana dengan pesan "No such file or directory" yang menunjuk berkas yang
    # jelas-jelas ada.
    from .suara import pilih_bagian

    jalur = str(Path(sumber).resolve())
    # Bagian lagunya dipilih dari panjang video, bukan selalu dari detik nol.
    # Alasan dan ukurannya ada di pilih_bagian.
    mulai = pilih_bagian(jalur, profile.target_duration())
    log.info("musik: %s @ %.0f dB, mulai %.0f detik", Path(sumber).name, gain_db, mulai)
    return Music(src=jalur, gain_db=gain_db, mulai=mulai)


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
    music_obj = siapkan_musik(music, profile, music_gain_db)

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
    on_klip: Callable[[Path], None] | None = None,
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
        brief=brief, job_id=job_id, on_progress=on_progress, jenis=jenis, **kw,
    )
    if pertama is not None:
        _lapor_klip(on_klip, pertama)
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
                on_progress=on_progress, jenis=jenis, **kw,
            )
            if k:
                hasil.append(k)
                _lapor_klip(on_klip, k)
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
    jenis: str = "short",
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

    # Dibuang SEBELUM job_id dan peta dibentuk, bukan sesudahnya. Berkas ganda
    # yang lolos ke sini akan dianalisis dua kali — transkrip untuk perannya
    # sebagai sumber suara, deteksi adegan untuk perannya sebagai B-roll — dan
    # itu puluhan menit untuk gambar yang justru tidak boleh dipakai.
    paths = _tanpa_ganda(paths)

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

        # Peta lama bisa memuat berkas ganda yang sekarang tidak lagi diterima.
        # Tanpa ini, job yang sudah pernah jalan dan diulang akan membangkitkan
        # kembali bug yang baru saja ditutup — dan justru job seperti itulah yang
        # paling mungkin diulang, karena hasilnya yang tidak sinkron.
        unik = _tanpa_ganda([Path(v.media.path) for v in vmap.videos])
        if len(unik) != len(vmap.videos):
            simpan = {os.path.normcase(str(p)) for p in unik}
            terpakai: set[str] = set()
            sisa: list[VideoMap] = []
            for v in vmap.videos:
                k = os.path.normcase(str(Path(v.media.path)))
                if k in simpan and k not in terpakai:
                    terpakai.add(k)
                    sisa.append(v)
            vmap = ProjectMap(videos=sisa)
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
        plan = decide(vmap, profile, brief, jenis)
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
                "konsep berformat overlay tapi tidak ada klip B-roll yang bisa "
                "dipakai — jatuh ke format satu jalur, mengikuti konsepnya"
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

        edl = build_overlay_edl(
            plan,
            vmap,
            profile,
            concept_id=profile.nama,
            music=siapkan_musik(music, profile, music_gain_db)
        )
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

    # Padanan yang sama untuk suara: potongan dari menit yang berjauhan
    # disambung, dan kenyaringannya melonjak di sambungan. Terukur 4 dari 8
    # sambungan di atas 3 LU pada satu hasil nyata, dengan puncak 9,6 LU.
    from .suara import ratakan_edl as ratakan_suara

    n_suara = ratakan_suara(edl)
    if n_suara:
        log.info("[4/5] suara: %d potongan diratakan kenyaringannya", n_suara)

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
