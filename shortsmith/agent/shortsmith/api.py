"""Klien HTTP ke job API.

Arah komunikasi selalu keluar: agent yang menghubungi cloud, tidak pernah
sebaliknya. Konsekuensinya tidak perlu buka port, tidak perlu IP publik, tidak
perlu konfigurasi firewall atau tunnel.

Agent tidak pernah memegang kredensial object storage. Semua URL unduh/unggah
datang sudah bertanda tangan dari `/api/jobs/next`.
"""

from __future__ import annotations

import logging
import time
import os
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

# Berapa lama satu potongan data boleh tersendat saat mengunggah, dalam detik.
# Bukan "waktu connect" — lihat penjelasan di Api.upload.
UNGGAH_SENDAT = 120

UNGGAH_PERCOBAAN = 4
UNGGAH_JEDA = 5  # detik, dikalikan nomor percobaan

CHUNK = 1024 * 1024


class ApiError(RuntimeError):
    pass


class JobHilang(ApiError):
    """Job sudah tidak lagi milik agent ini — biasanya karena dianggap terlantar."""


class ApiClient:
    def __init__(self, base_url: str | None = None, agent_key: str | None = None):
        self.base_url = (base_url or os.environ.get("SHORTSMITH_API_URL", "")).rstrip("/")
        self.agent_key = agent_key or os.environ.get("AGENT_KEY", "")
        if not self.base_url:
            raise ApiError("SHORTSMITH_API_URL belum diset.")
        if not self.agent_key:
            raise ApiError("AGENT_KEY belum diset.")

        self.session = requests.Session()
        self.session.headers["X-Agent-Key"] = self.agent_key

    # -- antrean -------------------------------------------------------

    def next_job(self, timeout: int = 30) -> dict[str, Any] | None:
        res = self.session.get(f"{self.base_url}/api/jobs/next", timeout=timeout)
        if res.status_code == 401:
            raise ApiError("X-Agent-Key ditolak server. Periksa AGENT_KEY di kedua sisi.")
        res.raise_for_status()
        return res.json().get("job")

    def heartbeat(self, job_id: str, *, progress: int | None = None, tahap: str = "") -> bool:
        """Kembalikan False kalau job sudah bukan milik kita lagi."""
        payload: dict[str, Any] = {}
        if progress is not None:
            payload["progress"] = max(0, min(100, int(progress)))
        if tahap:
            payload["tahap"] = tahap[:120]

        res = self.session.post(
            f"{self.base_url}/api/jobs/{job_id}/heartbeat", json=payload, timeout=15
        )
        if res.status_code == 409:
            return False
        res.raise_for_status()
        return bool(res.json().get("ok"))

    def report_done(self, job_id: str, **extra: Any) -> dict[str, Any]:
        return self._report(job_id, {"status": "done", **extra})

    def lapor_folder(self, payload: dict[str, Any]) -> bool:
        """Kirim daftar folder bahan ke server.

        Kegagalan di sini tidak pernah menghentikan apa pun: ini cuma kenyamanan
        untuk form, dan agent tetap bisa mengerjakan job tanpanya.
        """
        try:
            res = self.session.post(
                f"{self.base_url}/api/agent/folders", json=payload, timeout=15
            )
            res.raise_for_status()
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("gagal melaporkan folder bahan (%s) — diabaikan", exc)
            return False

    def report_failed(self, job_id: str, error: str) -> dict[str, Any]:
        return self._report(job_id, {"status": "failed", "errorMessage": error[:4000]})

    def _report(self, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        res = self.session.post(
            f"{self.base_url}/api/jobs/{job_id}/status", json=payload, timeout=30
        )
        res.raise_for_status()
        return res.json()

    # -- transfer file -------------------------------------------------

    def download(self, url: str, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        log.info("mengunduh -> %s", target.name)

        # Session tidak dipakai di sini: URL storage tidak boleh menerima
        # header X-Agent-Key kita.
        with requests.get(url, stream=True, timeout=(15, 600)) as res:
            res.raise_for_status()
            total = int(res.headers.get("content-length") or 0)
            sudah = 0
            with open(target, "wb") as fh:
                for chunk in res.iter_content(CHUNK):
                    fh.write(chunk)
                    sudah += len(chunk)
                    if total and sudah % (32 * CHUNK) < CHUNK:
                        log.info("  %.0f%%", sudah / total * 100)

        log.info("terunduh: %s (%.1f MB)", target.name, target.stat().st_size / 1e6)
        return target

    def upload(self, path: Path, url: str, content_type: str = "video/mp4") -> None:
        """Unggah hasil render ke storage, dengan percobaan ulang.

        ## Kenapa angka timeout-nya begini

        Elemen PERTAMA tuple timeout bukan cuma untuk connect. Saat requests
        mengirim body, urllib3 masih memakai socket timeout dari tahap koneksi,
        jadi angka itulah yang membatasi berapa lama satu potongan data boleh
        tersendat di tengah unggahan.

        Terukur di sini: unggahan 14 MB berjalan 73 detik, lalu satu chunk
        tersendat lebih dari 15 detik dan seluruh unggahan mati — padahal
        timeout kedua (1800 detik) belum tersentuh sama sekali. Koneksi rumahan
        yang naik-turun akan selalu menabrak ini.

        ## Kenapa harus diulang di sini, bukan di level job

        Kalau unggahan gagal, job tidak pernah ditandai selesai, dan server
        membagikannya lagi ke agent. Agent lalu MERENDER ULANG dari awal untuk
        mengunggah berkas yang isinya sama — terlihat sebagai job yang berputar
        tanpa henti. Diulang di sini, kegagalan jaringan sementara diselesaikan
        dalam hitungan detik tanpa menyentuh tahap render sama sekali.
        """
        ukuran = path.stat().st_size
        log.info("mengunggah %s (%.1f MB)", path.name, ukuran / 1e6)

        galat: Exception | None = None
        for percobaan in range(1, UNGGAH_PERCOBAAN + 1):
            try:
                with open(path, "rb") as fh:
                    res = requests.put(
                        url,
                        data=fh,
                        headers={
                            "content-type": content_type,
                            "content-length": str(ukuran),
                        },
                        timeout=(UNGGAH_SENDAT, 1800),
                    )
                res.raise_for_status()
                log.info("terunggah.")
                return
            except (requests.RequestException, OSError) as exc:
                galat = exc
                if percobaan < UNGGAH_PERCOBAAN:
                    jeda = UNGGAH_JEDA * percobaan
                    log.warning(
                        "unggahan gagal (percobaan %d/%d: %s) — ulangi dalam %ds",
                        percobaan, UNGGAH_PERCOBAAN, type(exc).__name__, jeda,
                    )
                    time.sleep(jeda)

        raise RuntimeError(
            f"Unggahan {path.name} ({ukuran / 1e6:.1f} MB) gagal setelah "
            f"{UNGGAH_PERCOBAAN} percobaan: {galat}"
        ) from galat
