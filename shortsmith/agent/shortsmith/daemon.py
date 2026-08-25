"""Daemon: agent berubah dari script terminal menjadi proses yang polling terus.

Loop-nya sederhana dan sengaja begitu:

    ambil job -> kerjakan (sambil kirim heartbeat) -> laporkan -> ulangi

Heartbeat berjalan di thread terpisah setiap 30 detik. Kalau server berhenti
menerimanya lebih dari 5 menit, job otomatis dikembalikan ke antrean — itu yang
menangani PC mati mendadak, listrik padam, atau agent crash.

Sebaliknya, kalau server menjawab heartbeat dengan "job ini bukan milikmu lagi",
thread heartbeat mengibarkan bendera dan job dibatalkan. Tanpa itu, satu job bisa
dirender dua kali: sekali oleh agent yang dikira mati, sekali oleh yang mengambil
alih.
"""

from __future__ import annotations

import logging
import signal
import threading
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .api import ApiClient, ApiError
from .config import SETTINGS
from .jenis import gain_musik, terapkan_jenis
from .models import CaptionStyle, ConceptProfile, ManualFields
from .probe import probe

log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30
POLL_KOSONG = 10  # jeda saat antrean kosong
POLL_ERROR = 30  # jeda setelah error jaringan
LAPOR_FOLDER_INTERVAL = 300  # seberapa sering daftar folder dikirim ulang

# Tanda bahwa kuota model habis, bukan bahwa job-nya rusak.
#
# Perbedaannya menentukan: job yang rusak memang pantas dicoba ulang lalu
# ditandai gagal. Kuota yang habis tidak membaik dalam hitungan menit, jadi tiga
# percobaan beruntun cuma menghanguskan jatah percobaan job itu -- dan
# pengguna melihat "gagal permanen" untuk pekerjaan yang sebenarnya baik-baik
# saja dan hanya perlu ditunggu.
#
# Terjadi sungguhan: satu job podcast lima klip menghabiskan kuota sesi, lalu
# gagal permanen dalam beberapa menit tanpa satu pun percobaannya punya peluang.
_POLA_KUOTA = re.compile(
    r"session limit|usage limit|rate.?limit|quota|api_error_status\D{0,4}429|429",
    re.I,
)

# Berapa lama menunggu sebelum mencoba lagi saat kuota habis, dan berapa lama
# menyerah. Sepuluh menit cukup pendek untuk menyambar begitu kuota pulih, dan
# batas tiga jam mencegah daemon menunggu selamanya kalau ternyata kuotanya
# tidak akan pulih hari itu.
KUOTA_JEDA = 600
KUOTA_MAKS = 3 * 3600

# Akhiran berkas yang dianggap bahan.
#
# AUDIO ikut, dan itu bukan kelengkapan iseng: folder `Lagu` berisi mp3 tidak
# akan pernah terlihat di form kalau pemindainya hanya menghitung video —
# foldernya terbaca kosong, lalu disaring keluar karena `berkas.length === 0`.
# Bug yang sama membuat perubahan di folder itu tidak memicu laporan ulang,
# sehingga menaruh lagu baru tidak pernah sampai ke web.
#
# Dipusatkan di sini karena dipakai DUA tempat yang harus selalu sepakat:
# `_sidik_folder` (mendeteksi perubahan) dan `_kumpulkan_folder` (mengirim
# daftarnya). Kalau keduanya beda, ada berkas yang terkirim tapi perubahannya
# tidak terdeteksi — atau sebaliknya.
EKST_VIDEO = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
EKST_AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
EKST_BAHAN = EKST_VIDEO | EKST_AUDIO
MAKS_BERKAS = 100  # batas berkas per folder yang dikirim ke form


class JobDibatalkan(RuntimeError):
    """Job diambil alih pihak lain di tengah jalan."""


class Heartbeat:
    """Kirim heartbeat berkala di latar belakang selama job berjalan."""

    def __init__(self, api: ApiClient, job_id: str):
        self.api = api
        self.job_id = job_id
        self.dibatalkan = threading.Event()
        self._stop = threading.Event()
        self._progress = 0
        self._tahap = ""
        self._thread: threading.Thread | None = None

    def update(self, progress: int, tahap: str) -> None:
        self._progress, self._tahap = progress, tahap
        log.info("[%d%%] %s", progress, tahap)
        if self.dibatalkan.is_set():
            raise JobDibatalkan("Job sudah diambil alih pihak lain.")

    def _loop(self) -> None:
        while not self._stop.wait(HEARTBEAT_INTERVAL):
            try:
                if not self.api.heartbeat(
                    self.job_id, progress=self._progress, tahap=self._tahap
                ):
                    log.warning("server menolak heartbeat — job bukan milik kita lagi")
                    self.dibatalkan.set()
                    return
            except Exception as exc:  # noqa: BLE001 — jaringan boleh gagal sementara
                log.warning("heartbeat gagal (%s) — dicoba lagi", exc)

    def __enter__(self) -> Heartbeat:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)


def _profile_from_json(data: dict[str, Any] | None, nama: str = "konsep") -> ConceptProfile:
    if not data:
        return ConceptProfile(nama=nama)
    return ConceptProfile.model_validate(data)


class Daemon:
    def __init__(self, api: ApiClient | None = None):
        self.api = api or ApiClient()
        self.berhenti = threading.Event()

    def stop(self, *_args: object) -> None:
        log.info("sinyal berhenti diterima — menyelesaikan job berjalan lalu keluar")
        self.berhenti.set()

    # -- loop utama ----------------------------------------------------

    def run_forever(self) -> None:
        from .probe import preflight

        masalah = preflight()
        if masalah:
            raise RuntimeError("Preflight gagal:\n  - " + "\n  - ".join(masalah))

        log.info("daemon jalan — API: %s", self.api.base_url)
        self._lapor_folder()
        terakhir_lapor = time.time()
        sidik_folder = self._sidik_folder()
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

        while not self.berhenti.is_set():
            try:
                job = self.api.next_job()
            except ApiError as exc:
                log.error("%s", exc)
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("gagal menghubungi API (%s) — coba lagi %ds", exc, POLL_ERROR)
                self.berhenti.wait(POLL_ERROR)
                continue

            # Perubahan isi folder dilaporkan SEGERA, bukan menunggu giliran
            # berikutnya.
            #
            # Laporan berkala saja tidak cukup: pengguna menaruh berkas lalu
            # langsung membuka form, dan selama lima menit form menampilkan
            # daftar lama tanpa memberi tahu bahwa ia sedang basi. Yang terlihat
            # adalah berkas yang "hilang" padahal sudah ada di disk.
            #
            # Memeriksa sidik folder jauh lebih murah daripada mengirimnya:
            # cukup satu kali baca direktori, dan loop ini memang sudah berputar
            # tiap beberapa detik untuk menanyakan job.
            sidik_baru = self._sidik_folder()
            berubah = sidik_baru != sidik_folder
            if berubah or time.time() - terakhir_lapor > LAPOR_FOLDER_INTERVAL:
                if berubah:
                    log.info("isi folder bahan berubah — dilaporkan segera")
                # Sidik dan stempel waktu HANYA diperbarui kalau laporannya
                # sampai. Sebelumnya keduanya diperbarui apa pun hasilnya, jadi
                # satu kegagalan membuat daftar folder di web basi selama lima
                # menit penuh sebelum ada percobaan berikutnya — dan kalau
                # kegagalannya terjadi saat daemon baru dinyalakan, formnya
                # kosong selama itu tanpa ada yang menjelaskan kenapa.
                if self._lapor_folder():
                    sidik_folder = sidik_baru
                    terakhir_lapor = time.time()

            if not job:
                # Antrean render kosong — pakai giliran ini untuk tugas singkat.
                #
                # Sengaja SETELAH job, bukan sebelum: render adalah pekerjaan
                # yang benar-benar diminta pengguna, sedangkan tugas di sini
                # membantu ia menyiapkannya. Menulis prompt sambil membiarkan
                # render menunggu adalah urutan yang terbalik.
                if self._ambil_tugas():
                    continue
                self.berhenti.wait(POLL_KOSONG)
                continue

            self._kerjakan(job)

        log.info("daemon berhenti.")

    def _ambil_tugas(self) -> bool:
        """Kerjakan satu tugas singkat kalau ada. True kalau ada yang dikerjakan."""
        # Utamakan tugas yang sudah ikut terbawa jawaban `next_job` — ia sudah
        # diambil dari antrean, jadi bertanya lagi berarti satu permintaan
        # tambahan untuk sesuatu yang sudah ada di tangan.
        didukung, t = self.api.ambil_tugas_menempel()
        if not didukung:
            # Server belum mengenal jalur gabungan — tanya terpisah seperti dulu.
            try:
                t = self.api.next_tugas()
            except Exception as exc:  # noqa: BLE001
                log.warning("gagal mengambil tugas (%s)", exc)
                return False
        if not t:
            return False

        tugas_id, tipe = t["id"], t["tipe"]
        log.info("=== tugas %s (%s) ===", tugas_id, tipe)
        try:
            if tipe == "prompt":
                hasil = self._tugas_prompt(t["permintaan"])
            elif tipe == "review":
                hasil = self._tugas_review(t["permintaan"])
            else:
                raise ValueError(f"tipe tugas tidak dikenal: {tipe}")
        except Exception as exc:  # noqa: BLE001
            # Dilaporkan, bukan ditelan. Tugas yang gagal diam-diam akan
            # dibebaskan penjaga tugas-basi, diambil lagi, dan gagal lagi —
            # sementara pengguna menunggu jawaban yang tidak pernah datang.
            log.exception("tugas %s gagal", tugas_id)
            self.api.lapor_tugas(tugas_id, error=f"{type(exc).__name__}: {exc}"[:2000])
            return True

        self.api.lapor_tugas(tugas_id, hasil=hasil)
        log.info("tugas %s selesai", tugas_id)
        return True

    def _tugas_prompt(self, p: dict[str, Any]) -> dict[str, Any]:
        from .pemasok import tulis_saja

        prompts = tulis_saja(
            int(p.get("jumlah") or 3),
            jenis=p.get("jenis") or "cinematic",
            tema=p.get("tema") or "",
            durasi=float(p.get("durasi") or 8),
            sudah_ada=list(p.get("sudahAda") or []),
        )
        return {"prompts": prompts}

    def _tugas_review(self, p: dict[str, Any]) -> dict[str, Any]:
        from .penilai import periksa

        kerja = SETTINGS.work_dir / "tugas"
        kerja.mkdir(parents=True, exist_ok=True)

        klip: list[Path] = []
        prompts: dict[str, str] = {}
        for k in p.get("klip") or []:
            berkas = self._unduh(
                {"namaFile": k["nama"], "downloadUrl": k.get("url"), "storageKey": k.get("key", "")},
                kerja,
            )
            klip.append(berkas)
            prompts[berkas.name] = k.get("prompt") or ""

        # Bahan tanpa URL berarti mode folder lokal: ia ada di disk pengguna dan
        # tidak pernah diunggah. Yang tidak ketemu dilewati, bukan menggagalkan
        # seluruh review — pemeriksaan isi tetap bisa jalan tanpa pembanding.
        bahan: list[Path] = []
        for b in p.get("bahan") or []:
            try:
                if b.get("url"):
                    bahan.append(self._unduh(
                        {"namaFile": b["nama"], "downloadUrl": b["url"],
                         "storageKey": b.get("key", "")}, kerja))
                else:
                    bahan.append(self._berkas_lokal({
                        "namaFile": b["nama"],
                        "bahanFolder": b.get("folder") or "",
                    }))
            except Exception as exc:  # noqa: BLE001
                log.warning("bahan pembanding '%s' dilewati: %s", b.get("nama"), exc)

        hasil = periksa(
            klip, bahan, jenis=p.get("jenis") or "cinematic", prompts=prompts,
            kerja=kerja / "frame",
        )
        return {
            "terangBahan": round(hasil.terang_bahan, 1),
            "semuaCocok": hasil.semua_cocok,
            "penilaian": [
                {
                    "nama": x.nama,
                    "cocok": x.cocok,
                    "alasan": x.alasan,
                    "alasanUkur": x.alasan_ukur,
                    "alasanIsi": x.alasan_isi,
                    "promptBaru": x.prompt_baru,
                    "terang": round(x.terang, 1),
                }
                for x in hasil.penilaian
            ],
        }

    def _kerjakan(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        tipe = job["tipe"]
        log.info("=== job %s (%s) ===", job_id, tipe)
        mulai = time.time()

        try:
            batas_kuota = time.time() + KUOTA_MAKS
            while True:
                try:
                    with Heartbeat(self.api, job_id) as hb:
                        if tipe == "render":
                            hasil = self._render(job, hb)
                        elif tipe == "profile_extraction":
                            hasil = self._ekstrak_profil(job, hb)
                        else:
                            raise RuntimeError(f"Tipe job tidak dikenal: {tipe}")
                    break
                except Exception as exc:  # noqa: BLE001
                    # Kuota habis BUKAN kegagalan job. Ditunggu di sini, di
                    # dalam job yang sama, supaya jatah percobaannya utuh dan
                    # pekerjaan yang sudah jalan (transkrip, deteksi adegan,
                    # pelabelan) tidak diulang dari nol.
                    if not _POLA_KUOTA.search(str(exc)) or time.time() > batas_kuota:
                        raise
                    log.warning(
                        "kuota model habis — menunggu %d menit lalu mencoba lagi "
                        "(job ini TIDAK dihitung gagal)",
                        KUOTA_JEDA // 60,
                    )
                    if self.berhenti.wait(KUOTA_JEDA):
                        raise

            res = self.api.report_done(job_id, **hasil)
            log.info("selesai dalam %.0f detik (status server: %s)",
                     time.time() - mulai, res.get("status"))

        except JobDibatalkan as exc:
            log.warning("job dibatalkan: %s", exc)
        except Exception as exc:  # noqa: BLE001 — batas luar daemon
            log.exception("job gagal")
            try:
                res = self.api.report_failed(job_id, f"{type(exc).__name__}: {exc}")
                if res.get("akanDiulang"):
                    log.info("job dikembalikan ke antrean untuk dicoba lagi")
                else:
                    log.info("job ditandai gagal permanen")
            except Exception as lapor:  # noqa: BLE001
                log.error("gagal melaporkan kegagalan: %s", lapor)

    # -- handler per tipe job -----------------------------------------

    def _render(self, job: dict[str, Any], hb: Heartbeat) -> dict[str, Any]:
        from .pipeline import run as run_pipeline

        inputs = job.get("inputs") or []
        if not inputs:
            raise RuntimeError("Job render tidak punya video mentah.")

        work = SETTINGS.ensure_work_dir(job["id"])
        sources = []
        for i, item in enumerate(inputs):
            hb.update(
                int(3 + 10 * i / len(inputs)),
                f"mengunduh video mentah {i + 1}/{len(inputs)}",
            )
            sources.append(self._unduh(item, work))

        profile = _profile_from_json(job.get("profileJson"), job.get("judul") or "konsep")

        # Jenis video menimpa beberapa setelan konsep.
        #
        # Yang ditimpa hanya yang memang bisa ditimpa tanpa mengarang: rasio,
        # dan apakah subtitle dibakar. Gaya potongannya sendiri TIDAK diubah —
        # itu tetap milik konsep, dan menebaknya dari satu label jenis akan
        # menghasilkan editing yang tidak pernah diukur dari contoh mana pun.
        jenis = job.get("jenis") or "short"
        profile = terapkan_jenis(profile, jenis, job.get("rasio") or "auto")

        # Lagu, kalau ada. Diunduh dengan aturan yang sama seperti bahan mentah:
        # berkas lokal dipakai di tempatnya, tanpa disalin.
        musik = None
        item_musik = job.get("musik")
        if item_musik:
            hb.update(14, "menyiapkan lagu")
            musik = str(self._unduh(item_musik, work))
            log.info("lagu: %s", Path(musik).name)

        output = work / "output.mp4"

        def progress(persen: int, tahap: str) -> None:
            hb.update(persen, tahap)

        from .pipeline import run_banyak

        # Unggahan berjalan BERBARENGAN dengan render klip berikutnya.
        #
        # Diukur pada job lima klip yang memakan 1.575 detik, unggahannya 714
        # detik -- 45% -- dan seluruhnya berjalan setelah klip terakhir selesai,
        # sementara CPU menganggur. Klip pertama sudah jadi 12 menit sebelumnya
        # dan isinya tidak berubah lagi; menunggu adalah murni penjadwalan.
        #
        # Satu pekerja saja, bukan lima. Yang ditumpangkan adalah unggahan di
        # atas render (jaringan di atas CPU), dan itu sudah menghabiskan hampir
        # seluruh keuntungannya. Menambah pekerja berarti beberapa unggahan
        # berebut satu jalur naik yang sama, dan tidak ada ukuran yang
        # mendukung bahwa itu menolong.
        hasil_unggah: dict[Path, dict] = {}
        gagal_unggah: list[tuple[Path, int]] = []
        antre = ThreadPoolExecutor(max_workers=1, thread_name_prefix="unggah")
        tugas_unggah: list[tuple[Path, object]] = []
        urut: dict[Path, int] = {}

        def unggah_nanti(k: Path) -> None:
            self._simpan_hasil(k, job)
            i = len(tugas_unggah)
            urut[k] = i
            tugas_unggah.append((k, antre.submit(self._unggah_satu, k, job, i)))

        try:
            klip = run_banyak(
                sources,
                profile,
                output,
                jenis=jenis,
                brief=job.get("brief", ""),
                job_id=job["id"],
                music=musik,
                music_gain_db=gain_musik(jenis),
                on_progress=progress,
                on_klip=unggah_nanti,
            )
            if not klip:
                raise RuntimeError("Pipeline tidak menghasilkan file.")

            hb.update(92, "menyelesaikan unggahan")
            for k, fut in tugas_unggah:
                try:
                    hasil_unggah[k] = fut.result()
                except Exception as exc:  # noqa: BLE001
                    # Klip yang gagal diunggah TIDAK menggagalkan laporan. Klip
                    # lain sudah naik dan sudah bernilai; menggagalkan seluruh
                    # job berarti pengguna kehilangan semuanya, dan job diulang
                    # dari nol termasuk transkrip satu jam itu.
                    log.warning("%s gagal diunggah (%s) — dicoba lagi nanti", k.name, exc)
                    gagal_unggah.append((k, urut[k]))
        finally:
            antre.shutdown(wait=True)

        # Klip yang lolos jalur latar dipakai apa adanya; yang gagal dicoba
        # sekali lagi di sini, berurutan. Gangguan jaringan sesaat saat render
        # sedang berjalan tidak boleh berarti klipnya hilang untuk selamanya.
        for k, i in gagal_unggah:
            try:
                hasil_unggah[k] = self._unggah_satu(k, job, i)
                log.info("%s berhasil diunggah pada percobaan kedua", k.name)
            except Exception as exc:  # noqa: BLE001
                log.warning("%s tetap gagal diunggah (%s)", k.name, exc)

        naik = [k for k in klip if k in hasil_unggah]
        if not naik:
            raise RuntimeError("Tidak ada satu pun klip yang berhasil diunggah.")

        ringkas = dict(hasil_unggah[naik[0]])
        tambahan = [hasil_unggah[k] for k in naik[1:]]

        if tambahan:
            ringkas["klipTambahan"] = tambahan
            log.info("%d klip diunggah (1 utama + %d tambahan)", len(tambahan) + 1, len(tambahan))
        return ringkas

    def _lapor_folder(self) -> bool:
        payload = self._kumpulkan_folder()
        # Hanya dilaporkan berhasil kalau memang berhasil. Log yang mengklaim
        # sukses padahal gagal membuat masalah tersembunyi justru di tempat
        # pertama yang orang periksa.
        if self.api.lapor_folder(payload):
            log.info(
                "folder bahan dilaporkan: %d folder di %s",
                len(payload["folders"]), payload["root"],
            )
            return True
        return False

    def _unggah_satu(self, k: Path, job: dict[str, Any], indeks: int) -> dict:
        """Unggah satu klip dan kembalikan ringkasannya untuk laporan job.

        Slotnya ditentukan `indeks`, bukan oleh urutan kedatangan di thread:
        klip PERTAMA memakai slot yang sudah disertakan job, sisanya meminta
        slot sendiri. Saat job dibagikan, belum ada yang tahu berapa klip yang
        akan lahir darinya.

        Permintaan slot ikut dikerjakan DI SINI, di dalam pekerja, bukan di
        pemanggilnya. Kalau ia dipanggil di thread render, kegagalannya jatuh ke
        penelan galat di `_lapor_klip` — dan klip itu akan hilang diam-diam
        tanpa pernah masuk daftar yang dicoba ulang.
        """
        if indeks == 0:
            slot = job["output"]
        else:
            slot = self.api.slot_output(job["id"])
        self.api.upload(k, slot["uploadUrl"])
        info = probe(k)
        return {
            "outputKey": slot["key"],
            "namaFile": k.name,
            "ukuranBytes": k.stat().st_size,
            "durasi": round(info.durasi, 3),
        }

    def _simpan_hasil(self, berkas: Path, job: dict[str, Any]) -> Path | None:
        """Salin hasil render ke folder hasil dengan nama yang bisa dibaca.

        Kegagalan di sini tidak pernah menggagalkan job: unggahan ke storage
        tetap jalan, dan itu yang dipakai halaman project.
        """
        import re
        import shutil
        from datetime import datetime

        try:
            folder = SETTINGS.hasil_dir.resolve()
            folder.mkdir(parents=True, exist_ok=True)

            judul = (job.get("judul") or "hasil").rsplit(".", 1)[0]
            aman = re.sub(r"[^\w\- ]+", "_", judul).strip()[:80] or "hasil"
            nama = f"{aman} {datetime.now():%Y-%m-%d %H%M}{berkas.suffix}"

            tujuan = folder / nama
            shutil.copyfile(berkas, tujuan)
            log.info("hasil disimpan: %s", tujuan)
            return tujuan
        except OSError as exc:  # noqa: BLE001
            log.warning("gagal menyimpan salinan hasil (%s) — diabaikan", exc)
            return None

    def _sidik_folder(self) -> tuple:
        """Ringkasan isi folder bahan, untuk mendeteksi perubahan dengan murah.

        Memuat nama, ukuran, dan waktu ubah tiap berkas video. Ukuran saja tidak
        cukup — berkas yang diganti dengan berkas lain berukuran sama akan lolos,
        dan itu justru yang terjadi saat pengguna menimpa hasil rekaman.
        """
        root = SETTINGS.bahan_dir.resolve()
        if not root.is_dir():
            return ()
        isi = []
        try:
            for d in sorted(root.iterdir()):
                if not d.is_dir():
                    continue
                for f in sorted(d.iterdir()):
                    if f.is_file() and f.suffix.lower() in EKST_BAHAN:
                        st = f.stat()
                        isi.append((d.name, f.name, st.st_size, st.st_mtime_ns))
        except OSError:
            # Folder yang sedang disalin bisa hilang di tengah pembacaan. Itu
            # bukan alasan menjatuhkan daemon; pemeriksaan berikutnya menangkapnya.
            return ()
        return tuple(isi)

    def _kumpulkan_folder(self) -> dict[str, Any]:
        """Daftar folder bahan beserta jumlah videonya, untuk ditampilkan di form.

        Hanya satu tingkat ke bawah. Menelusuri seluruh pohon folder di disk
        pengguna akan lambat dan menghasilkan daftar yang terlalu panjang untuk
        dipilih — dan bahan video jarang ditumpuk lebih dalam dari itu.
        """
        root = SETTINGS.bahan_dir.resolve()
        folders: list[dict[str, Any]] = []

        if not root.is_dir():
            return {"root": str(root), "folders": folders}

        # Nama dan ukuran berkas ikut dikirim, bukan cuma jumlahnya.
        #
        # Tanpa ini, form terpaksa memakai file picker browser hanya untuk
        # mendapatkan nama dan ukuran — tombol "Choose File" yang tidak
        # mengunggah apa pun, dan membuka peluang pengguna memilih berkas dari
        # folder lain yang namanya kebetulan sama.
        def isi(d: Path) -> list[dict[str, Any]]:
            try:
                return sorted(
                    (
                        {"nama": f.name, "ukuranBytes": f.stat().st_size}
                        for f in d.iterdir()
                        if f.is_file() and f.suffix.lower() in EKST_BAHAN
                    ),
                    key=lambda x: x["nama"].lower(),
                )[:MAKS_BERKAS]
            except OSError:
                return []

        def catat(path: str, d: Path) -> None:
            berkas = isi(d)
            # Dihitung terpisah, bukan `len(berkas)` untuk keduanya. Sejak audio
            # ikut terdaftar, satu angka bernama "jumlahVideo" yang sebenarnya
            # menghitung mp3 juga adalah nama yang berbohong — dan form memakai
            # angka itu untuk memberi tahu pengguna apa yang ada di foldernya.
            video = sum(
                1 for b in berkas if Path(b["nama"]).suffix.lower() in EKST_VIDEO
            )
            folders.append({
                "path": path,
                "jumlahVideo": video,
                "jumlahAudio": len(berkas) - video,
                "berkas": berkas,
            })

        catat("", root)
        try:
            for sub in sorted(p for p in root.iterdir() if p.is_dir()):
                catat(sub.name, sub)
        except OSError as exc:
            log.warning("gagal membaca folder bahan (%s)", exc)

        return {"root": str(root), "folders": folders[:200]}

    def _berkas_lokal(self, item: dict[str, Any]) -> Path:
        """Cari berkas di folder bahan dan pakai DI TEMPATNYA, tanpa menyalin.

        Menyalin ke work dir akan menggandakan berkas 388 MB tanpa alasan —
        ffmpeg dan Whisper membacanya dari mana pun dengan sama baiknya.
        """
        nama = item.get("namaFile", "")

        # Payload ini datang dari jaringan. Tanpa penjagaan, nama seperti
        # "../../Windows/System32/x" akan menunjuk ke luar folder bahan.
        if not nama or "/" in nama or "\\" in nama or nama in {".", ".."}:
            raise RuntimeError(
                f"Nama berkas lokal tidak sah: {nama!r}. "
                "Nama tidak boleh memuat pemisah folder."
            )

        sub = (item.get("bahanFolder") or "").strip()
        if ".." in sub or sub.startswith(("/", "\\")) or ":" in sub:
            raise RuntimeError(f"Folder bahan tidak sah: {sub!r}")

        folder = (SETTINGS.bahan_dir / sub).resolve() if sub else SETTINGS.bahan_dir.resolve()
        akar = SETTINGS.bahan_dir.resolve()
        if not folder.is_relative_to(akar):
            raise RuntimeError(f"Folder bahan keluar dari akar: {sub!r}")

        berkas = (folder / nama).resolve()
        if not berkas.is_relative_to(akar):
            raise RuntimeError(f"Nama berkas lokal keluar dari folder bahan: {nama!r}")

        if not berkas.is_file():
            # Daftar isi folder ikut disertakan. "Berkas tidak ditemukan" tanpa
            # menunjukkan apa yang ADA memaksa pengguna menebak, dan penyebab
            # tersering di sini cuma beda satu karakter di nama.
            if folder.is_dir():
                isi = sorted(p.name for p in folder.iterdir() if p.is_file())
                daftar = "\n  - ".join(isi[:15]) or "(folder kosong)"
                lanjut = f"\n  ... dan {len(isi) - 15} lagi" if len(isi) > 15 else ""
            else:
                daftar = "(folder belum ada)"
                lanjut = ""
            raise RuntimeError(
                f"Berkas '{nama}' tidak ada di folder bahan.\n"
                f"Folder yang dicari: {folder}\n"
                f"Isi folder:\n  - {daftar}{lanjut}"
            )

        diminta = item.get("ukuranBytes")
        nyata = berkas.stat().st_size
        if diminta and abs(int(diminta) - nyata) > 0:
            # Nama sama tapi isi berbeda adalah kegagalan paling mungkin di sini,
            # dan tanpa pemeriksaan ini ia lolos diam-diam sampai hasilnya salah.
            raise RuntimeError(
                f"Ukuran '{nama}' tidak cocok. Yang dipilih di browser "
                f"{int(diminta) / 1e6:.1f} MB, yang ada di folder bahan "
                f"{nyata / 1e6:.1f} MB. Kemungkinan berkasnya berbeda."
            )

        log.info("dari folder lokal: %s (%.1f MB, tanpa unduh)", nama, nyata / 1e6)
        return berkas

    def _unduh(self, item: dict[str, Any], work: Path) -> Path:
        """Ambil dari cache kalau sudah pernah diunduh, kalau tidak unduh baru.

        Job yang gagal diulang tiga kali. Tanpa cache, tiap pengulangan
        mengunduh ulang seluruh bahan — dan itulah yang menghabiskan kuota
        harian Backblaze sampai unduhan berikutnya ditolak 403.
        """
        from .cache_unduh import ambil, simpan

        if item.get("lokal"):
            return self._berkas_lokal(item)

        tujuan = work / item["namaFile"]
        kunci = item.get("storageKey", "")

        if ambil(kunci, tujuan):
            return tujuan

        hasil = self.api.download(item["downloadUrl"], tujuan)
        simpan(kunci, hasil)
        return hasil

    def _ekstrak_profil(self, job: dict[str, Any], hb: Heartbeat) -> dict[str, Any]:
        from .profile import extract_profile

        inputs = job.get("inputs") or []
        if not inputs:
            raise RuntimeError("Job ekstraksi konsep tidak punya video contoh.")
        if len(inputs) == 1:
            log.warning("hanya 1 video contoh — deviasi ritme tidak bisa diukur")

        work = SETTINGS.ensure_work_dir(job["id"])
        paths: list[str] = []
        for i, item in enumerate(inputs):
            hb.update(
                int(10 + 50 * i / len(inputs)),
                f"mengunduh contoh {i + 1}/{len(inputs)}",
            )
            paths.append(str(self._unduh(item, work)))

        hb.update(65, "menganalisis gaya editing")
        mentah = job.get("profileJson")
        awal = _profile_from_json(mentah, job.get("nama") or "konsep")

        profile = extract_profile(
            paths,
            nama=job.get("nama") or awal.nama,
            manual=awal.manual or ManualFields(),
            # None dikirim kalau konsep belum pernah menyimpan gaya caption,
            # supaya ekstraksi MEMBACANYA dari video contoh. Mengirim objek
            # bawaan di sini akan tampak seperti pilihan eksplisit user, dan
            # cabang pembelajaran tidak akan pernah jalan.
            caption=CaptionStyle.model_validate(mentah["caption"])
            if isinstance(mentah, dict) and isinstance(mentah.get("caption"), dict)
            else None,
            struktur=awal.struktur,
            aspect_ratio=awal.aspect_ratio,
        )

        hb.update(95, "mengirim profil")
        return {"profileJson": profile.model_dump(mode="json")}


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    Daemon().run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
