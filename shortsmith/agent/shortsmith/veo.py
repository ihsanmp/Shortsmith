"""Menghasilkan klip video lewat Veo di Gemini API.

## Kedudukannya di pipeline

PENAMBAL, bukan pengganti. Bahan rekaman pengguna tetap sumber utama; klip yang
dihasilkan di sini cuma mengisi kekurangan. Alasannya bukan selera:

  - Untuk short dan podcast, yang dijual adalah orang yang bicara. Wajah dan
    suaranya tidak bisa dihasilkan model, dan mencoba menggantinya menghasilkan
    video tentang orang lain.
  - Bahan asli gratis dan sudah ada di disk. Tiap klip yang dihasilkan di sini
    menagih akun Google pengguna.

Yang benar-benar tertolong adalah AMV dan cinematic — dua jenis yang menurut
ukuran contoh pengguna memang tanpa ucapan sama sekali.

## Yang harus diketahui sebelum memakainya

Veo membatasi keluarannya pada dua rasio saja, 16:9 dan 9:16, sedangkan
Shortsmith menerima rasio apa pun — salah satu contoh AMV yang dikirim pengguna
justru 3:4. Jadi rasio di sini dipilih yang TERDEKAT, dan sisanya diserahkan ke
crop yang memang sudah dilakukan renderer untuk semua bahan lain. Bukan
kompromi baru: bahan rekaman pun tidak pernah datang dalam rasio keluaran.

Panjangnya juga dibatasi 4, 6, atau 8 detik. Itu ternyata cukup: shot cinematic
pada contoh yang diukur rata-rata 1,9-2,1 detik dan AMV 0,33 detik, jadi satu
klip 8 detik memuat sekitar empat shot cinematic atau dua puluhan shot AMV.

## Kunci API

Dibaca dari environment GEMINI_API_KEY, dan TIDAK pernah ikut ke log — baik saat
sukses maupun saat gagal. Ia tagihan pengguna; membocorkannya ke berkas log yang
lalu dikirim saat melapor bug adalah cara paling mudah kehilangan uang.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

BASE = "https://generativelanguage.googleapis.com/v1beta"

# Bisa ditimpa lewat env: nama model Veo berganti cukup sering, dan agent yang
# menyandera nama model di dalam kode akan mati sendiri saat namanya berubah.
MODEL = os.environ.get("VEO_MODEL", "veo-3.1-fast-generate-preview")

# Satu-satunya rasio yang diterima Veo.
RASIO = ("16:9", "9:16")

# Satu-satunya panjang yang diterima Veo, dalam detik.
DURASI = (4, 6, 8)

# Berapa lama menunggu satu klip selesai dibuat. Veo memakai operasi
# jangka-panjang: permintaan langsung kembali, hasilnya baru ada beberapa menit
# kemudian.
TUNGGU_MAKS = 600
JEDA_POLL = 10


class VeoError(RuntimeError):
    """Gagal menghasilkan klip. Selalu tanpa memuat kunci API di pesannya."""


def _kunci() -> str:
    kunci = os.environ.get("GEMINI_API_KEY", "").strip()
    if not kunci:
        raise VeoError(
            "GEMINI_API_KEY belum diisi. Taruh di agent/.env sebagai "
            "GEMINI_API_KEY=... — ambil kuncinya di https://aistudio.google.com/apikey"
        )
    return kunci


def rasio_terdekat(rasio: str) -> str:
    """Petakan rasio apa pun ke salah satu dari dua yang diterima Veo.

    Pembandingnya lebar dibagi tinggi, bukan pencocokan string: '3:4' tidak sama
    dengan '9:16' sebagai teks, tapi keduanya tegak dan 9:16 adalah pilihan yang
    benar untuknya.
    """
    try:
        w, h = (float(x) for x in rasio.replace("x", ":").split(":")[:2])
        nilai = w / h
    except (ValueError, ZeroDivisionError):
        return "16:9"
    return "16:9" if nilai >= 1.0 else "9:16"


def _durasi_terdekat(detik: float) -> int:
    return min(DURASI, key=lambda d: abs(d - detik))


def hasilkan(
    prompt: str,
    target: Path,
    *,
    rasio: str = "16:9",
    durasi: float = 8,
    resolusi: str = "720p",
    negatif: str = "",
) -> Path:
    """Buat satu klip dari `prompt` dan simpan ke `target`.

    Memblokir sampai klipnya jadi — bisa beberapa menit. Melempar `VeoError`
    untuk semua kegagalan, termasuk kehabisan waktu tunggu.
    """
    kunci = _kunci()
    if not prompt.strip():
        raise VeoError("prompt kosong")

    ar = rasio if rasio in RASIO else rasio_terdekat(rasio)
    dur = _durasi_terdekat(durasi)

    parameter: dict = {
        "aspectRatio": ar,
        "resolution": resolusi,
        "durationSeconds": str(dur),
    }
    if negatif.strip():
        parameter["negativePrompt"] = negatif.strip()

    log.info("veo: membuat klip %ds %s (%s)", dur, ar, resolusi)
    log.info("veo: prompt: %s", prompt[:160])

    kepala = {"x-goog-api-key": kunci, "Content-Type": "application/json"}
    try:
        res = requests.post(
            f"{BASE}/models/{MODEL}:predictLongRunning",
            headers=kepala,
            json={"instances": [{"prompt": prompt}], "parameters": parameter},
            timeout=(15, 120),
        )
    except requests.RequestException as exc:
        raise VeoError(f"tidak bisa menghubungi Gemini API: {exc}") from None

    if res.status_code != 200:
        raise VeoError(_pesan_gagal(res))

    operasi = res.json().get("name")
    if not operasi:
        raise VeoError("Gemini API tidak mengembalikan nama operasi")

    uri = _tunggu(operasi, kunci)
    return _unduh(uri, target, kunci)


def _pesan_gagal(res: requests.Response) -> str:
    """Pesan galat yang berguna, tanpa pernah memuat kunci API.

    Badan jawaban Google memuat pesan yang jelas (kuota habis, model tidak ada,
    wilayah tidak didukung); membuang isinya dan cuma menyebut kode status
    memaksa pengguna menebak. Yang dibuang justru header kita sendiri.
    """
    try:
        galat = res.json().get("error", {})
        pesan = galat.get("message") or res.text[:300]
        status = galat.get("status", "")
    except ValueError:
        pesan, status = res.text[:300], ""
    return f"Gemini API menolak (HTTP {res.status_code} {status}): {pesan}"


def _tunggu(operasi: str, kunci: str) -> str:
    """Poll operasi sampai selesai; kembalikan URI videonya."""
    batas = time.monotonic() + TUNGGU_MAKS
    while True:
        if time.monotonic() > batas:
            raise VeoError(
                f"klip belum selesai setelah {TUNGGU_MAKS // 60} menit. "
                "Operasinya mungkin masih jalan di sisi Google."
            )
        time.sleep(JEDA_POLL)
        try:
            res = requests.get(
                f"{BASE}/{operasi}",
                headers={"x-goog-api-key": kunci},
                timeout=(15, 60),
            )
        except requests.RequestException as exc:
            log.warning("veo: gagal memeriksa status (%s) — dicoba lagi", exc)
            continue

        if res.status_code != 200:
            raise VeoError(_pesan_gagal(res))

        data = res.json()
        if not data.get("done"):
            log.info("veo: masih dibuat...")
            continue

        # Operasi yang SELESAI masih bisa selesai dengan kegagalan. Tanpa
        # memeriksa ini, kegagalan model terbaca sebagai "tidak ada video" dan
        # dilaporkan sebagai jawaban yang bentuknya aneh.
        if data.get("error"):
            raise VeoError(f"Veo gagal membuat klip: {data['error'].get('message')}")

        contoh = (
            data.get("response", {})
            .get("generateVideoResponse", {})
            .get("generatedSamples", [])
        )
        if not contoh:
            # Paling sering: prompt ditolak penyaring keamanan. Jawabannya
            # memang kosong, bukan error — jadi harus dijelaskan di sini.
            raise VeoError(
                "Veo selesai tanpa menghasilkan video. Prompt-nya kemungkinan "
                "ditolak penyaring konten."
            )
        return contoh[0]["video"]["uri"]


def _unduh(uri: str, target: Path, kunci: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(
            uri, headers={"x-goog-api-key": kunci}, stream=True, timeout=(15, 600)
        ) as res:
            if res.status_code != 200:
                raise VeoError(_pesan_gagal(res))
            with open(target, "wb") as fh:
                for potong in res.iter_content(1024 * 1024):
                    fh.write(potong)
    except requests.RequestException as exc:
        raise VeoError(f"gagal mengunduh klip: {exc}") from None

    ukuran = target.stat().st_size
    if ukuran == 0:
        target.unlink(missing_ok=True)
        raise VeoError("klip yang diunduh kosong")
    log.info("veo: selesai -> %s (%.1f MB)", target.name, ukuran / 1e6)
    return target
