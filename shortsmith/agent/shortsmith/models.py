"""Skema data: concept profile, peta video, dan EDL.

EDL adalah kontrak antara lapisan keputusan (LLM) dan lapisan eksekusi (renderer).
Renderer apa pun yang bisa mengonsumsi EDL bisa dipasang tanpa menyentuh apa pun di atasnya.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Role(str, Enum):
    hook = "hook"
    konteks = "konteks"
    isi = "isi"
    cta = "cta"


# --------------------------------------------------------------------------
# Concept profile
# --------------------------------------------------------------------------


class MetricStat(BaseModel):
    """Rata-rata dan deviasi satu metrik gaya editing, diekstrak dari video contoh."""

    mean: float
    std: float = 0.0


class CaptionStyle(BaseModel):
    ada: bool = True
    # Bawaan mengikuti gaya clipper di video contoh: satu kata di tengah layar,
    # huruf besar semua. Diukur dari contoh kedua yang dikirim user — di sana
    # setiap caption hanya memuat satu kata ("TELEN", "PECUNDANG", "GUA"),
    # ditaruh di tengah, bukan di bawah.
    posisi: str = "tengah"  # tengah-bawah | tengah | atas
    gaya: str = "kata-per-kata"  # frasa | kata-per-kata
    huruf_besar: bool = True
    font: str = "Arial"
    ukuran: int = 64
    warna: str = "&H00FFFFFF"  # format ASS: &HAABBGGRR
    outline_warna: str = "&H00000000"
    outline: int = 3
    max_kata: int = 4  # jumlah kata per potongan caption saat gaya = "frasa"


class ManualFields(BaseModel):
    """Satu-satunya hal yang tidak terbaca dari video dan boleh diisi manual.

    Dulu di sini ada lima isian: gaya bahasa, brand voice, call to action,
    target audiens, dan daftar larangan. Semuanya wajib dilewati setiap kali
    membuat konsep, dan semuanya berakhir sebagai beberapa baris teks di prompt
    keputusan — pengaruhnya kecil, sementara biayanya dibayar penuh oleh
    pengguna di setiap konsep baru.

    Yang benar-benar mengubah hasil cuma satu: mau bicara soal apa. Isian lain
    sudah terbaca dari video contoh (ritme, rasio, gaya caption, porsi
    pembicara), jadi memintanya lagi cuma menduakan sumber kebenaran.

    Kosong berarti bebas — editor memilih bagian paling kuat dari rekaman.
    """

    fokus: str = ""


class ConceptProfile(BaseModel):
    nama: str
    versi: int = 1
    metrik: dict[str, MetricStat] = Field(default_factory=dict)

    # "satu-jalur" = gambar terikat pada suara, satu potongan membawa keduanya.
    # "overlay"    = suara dari satu rekaman, gambar dari klip lain di atasnya.
    # "auto"       = belum diketahui; diputuskan dari bahan saat render.
    #
    # Bawaannya "auto", BUKAN "satu-jalur". Konsep yang dibuat sebelum deteksi
    # format ada tidak punya field ini, dan default diam-diam "satu-jalur"
    # membuat seluruh klip B-roll diunduh, dipecah jadi ratusan adegan, lalu
    # dibuang tanpa satu pun peringatan. Keluaran yang salah tanpa keluhan
    # adalah kegagalan paling mahal, karena baru ketahuan setelah ditonton.
    #
    # Dengan "auto", kehadiran klip B-roll yang jadi penentu — dan itu memang
    # sinyal niat pengguna yang paling jujur: orang tidak mengunggah klip kalau
    # tidak ingin klipnya dipakai.
    format: str = "auto"

    # Bagian durasi yang menampilkan rekaman suaranya sendiri (pembicara),
    # sisanya B-roll. DIUKUR dari video contoh, bukan angka tetap di kode —
    # lihat gaya_visual.py. Dua contoh yang dikirim pengguna terukur 0.00 dan
    # 0.57, dan keduanya benar untuk gayanya masing-masing.
    porsi_pembicara: float = 0.0

    aspect_ratio: str = "auto"
    caption: CaptionStyle = Field(default_factory=CaptionStyle)
    struktur: list[Role] = Field(default_factory=lambda: [Role.hook, Role.isi, Role.cta])
    manual: ManualFields = Field(default_factory=ManualFields)
    music_path: str | None = None

    def target_duration(self, fallback: float = 45.0) -> float:
        stat = self.metrik.get("durasi_total")
        return stat.mean if stat else fallback

    def target_penggal(self) -> float | None:
        """Berapa penggal suara yang diharapkan — BUKAN jumlah pergantian gambar."""
        stat = self.metrik.get("penggal_suara")
        return stat.mean if stat and stat.mean > 0 else None

    def target_cuts(self) -> float | None:
        stat = self.metrik.get("jumlah_cut")
        return stat.mean if stat else None


# --------------------------------------------------------------------------
# Peta video mentah (output tahap analisis)
# --------------------------------------------------------------------------


class MediaInfo(BaseModel):
    path: str
    durasi: float
    width: int
    height: int
    fps: float
    punya_audio: bool
    codec_video: str = ""
    vfr: bool = False

    # Rect isi gambar sebenarnya, format "w:h:x:y" untuk filter crop ffmpeg.
    # Kosong berarti berkasnya bersih. Diisi untuk klip B-roll, yang sering
    # membawa letterbox sinematik terbakar di dalam gambarnya.
    crop: str = ""


class Word(BaseModel):
    start: float
    end: float
    text: str


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class SilenceGap(BaseModel):
    start: float
    end: float

    @property
    def durasi(self) -> float:
        return self.end - self.start


class Adegan(BaseModel):
    """Satu adegan utuh di dalam sebuah file B-roll.

    Satu file kompilasi bisa memuat puluhan adegan berbeda. Memperlakukan file
    itu sebagai SATU klip akan membuat potongan 1,25 detik jatuh sembarangan —
    kadang di tengah perpindahan adegan, sehingga satu slot berisi dua gambar
    yang tidak berhubungan. Memecahnya lebih dulu membuat tiap slot selalu
    berisi satu adegan utuh.
    """

    src: str
    start: float
    end: float
    # Rect isi gambar berkas asalnya; ikut dibawa supaya renderer tidak perlu
    # membuka peta video lagi.
    crop: str = ""
    # Titik wajah sebagai pecahan dari isi gambar. None = tidak ada wajah,
    # yang berarti "pakai crop tengah" — bukan kegagalan.
    fokus_x: float | None = None
    fokus_y: float | None = None
    # Sidik identitas wajah itu, untuk memastikan klipnya menampilkan tokoh
    # yang sama dengan pembicara. None = tidak ada wajah untuk dikenali.
    sidik: list[float] | None = None
    # Arah pandang wajahnya, dipakai untuk menyisakan ruang pandang. Lihat kaidah.py.
    arah: float = 0.0
    # Label isi gambar, diisi pelabel.py. Dipakai penata untuk mencocokkan
    # gambar dengan makna kalimat. Kosong = belum/gagal dilabeli.
    label: str = ""

    @property
    def durasi(self) -> float:
        return self.end - self.start


class VideoMap(BaseModel):
    """Semua yang diketahui tentang satu video mentah, sebelum ada keputusan editing."""

    media: MediaInfo
    segments: list[TranscriptSegment] = Field(default_factory=list)
    words: list[Word] = Field(default_factory=list)
    silences: list[SilenceGap] = Field(default_factory=list)
    adegan: list[Adegan] = Field(default_factory=list)

    def transcript_text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments)


class ProjectMap(BaseModel):
    """Kumpulan peta untuk satu project yang punya beberapa video mentah.

    Tiap video dianalisis terpisah dan punya garis waktunya sendiri — tidak
    disambung jadi satu, karena menyambungnya akan membuat timestamp semu yang
    tidak cocok dengan file mana pun saat render.

    Yang menyatukan keduanya adalah indeks: LLM memilih `sumber: 2, in: 41.5`,
    lalu indeks itu diterjemahkan kembali ke path file yang benar.
    """

    videos: list[VideoMap] = Field(min_length=1)

    @property
    def total_durasi(self) -> float:
        return sum(v.media.durasi for v in self.videos)

    def get(self, index: int) -> VideoMap | None:
        return self.videos[index] if 0 <= index < len(self.videos) else None


# --------------------------------------------------------------------------
# Keluaran LLM: rencana potongan (bukan EDL penuh)
#
# LLM hanya memilih rentang waktu. Caption diturunkan secara deterministik dari
# timestamp Whisper, supaya teksnya tidak pernah mengada-ada dan waktunya presisi.
# --------------------------------------------------------------------------


class PlannedCut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sumber: int = Field(
        default=0,
        ge=0,
        description="Nomor video mentah yang dipakai (lihat daftar VIDEO di prompt)",
    )
    in_: float = Field(alias="in", ge=0, description="Detik mulai di video mentah")
    out: float = Field(ge=0, description="Detik selesai di video mentah")
    role: Role
    alasan: str = Field(description="Kenapa potongan ini dipilih")
    zoom: float = Field(default=1.0, ge=1.0, le=1.6, description="Punch-in; 1.0 = tanpa zoom")

    @model_validator(mode="after")
    def _cek_urutan(self) -> PlannedCut:
        if self.out <= self.in_:
            raise ValueError(f"out ({self.out}) harus lebih besar dari in ({self.in_})")
        return self

    @property
    def durasi(self) -> float:
        return self.out - self.in_


class CutPlan(BaseModel):
    """Persis inilah yang diminta dari LLM — tidak lebih."""

    cuts: list[PlannedCut] = Field(min_length=1)
    ringkasan: str = Field(description="Satu kalimat: cerita apa yang dirangkai potongan ini")


# --------------------------------------------------------------------------
# EDL — kontrak ke renderer
# --------------------------------------------------------------------------


class Cut(PlannedCut):
    src: str = Field(description="Path file sumber")
    # Lihat VideoSlot.crop dan VideoSlot.fokus_x — alasannya sama persis.
    crop: str = ""
    fokus_x: float | None = None
    fokus_y: float | None = None
    arah: float = 0.0
    jalur: list[list[float]] = Field(default_factory=list)


class Caption(BaseModel):
    t: float = Field(ge=0, description="Detik mulai, relatif terhadap timeline OUTPUT")
    durasi: float = Field(gt=0)
    text: str


class Music(BaseModel):
    src: str
    gain_db: float = -20.0
    fade_out: float = 1.5


class Resolution(BaseModel):
    width: int = 1080
    height: int = 1920


# Rasio yang didukung, beserta resolusi keluarannya.
#
# Sisi pendek dipatok 1080 untuk semua rasio potret dan persegi: itu resolusi
# yang diterima semua platform short video tanpa diperkecil lagi, dan menaikkannya
# hanya menambah ukuran file tanpa menambah ketajaman yang terlihat di ponsel.
RASIO: dict[str, Resolution] = {
    "9:16": Resolution(width=1080, height=1920),   # TikTok, Reels, Shorts
    "4:5": Resolution(width=1080, height=1350),    # feed Instagram potret
    "3:4": Resolution(width=1080, height=1440),    # rasio video contoh @pejuangclipper8
    "1:1": Resolution(width=1080, height=1080),    # persegi
    "16:9": Resolution(width=1920, height=1080),   # lanskap
}

RASIO_DEFAULT = "9:16"


def resolution_for(aspect: str | None) -> Resolution:
    """Ubah string rasio jadi resolusi keluaran. Tidak dikenal -> default 9:16."""
    return RASIO.get((aspect or "").strip(), RASIO[RASIO_DEFAULT])


def rasio_terdekat(width: int, height: int) -> str:
    """Tebak rasio dari dimensi asli, dibulatkan ke pilihan terdekat.

    Dipakai saat mengekstrak concept profile: rasio output diambil dari video
    contoh, bukan diasumsikan 9:16.
    """
    if not height:
        return RASIO_DEFAULT
    r = width / height
    return min(RASIO, key=lambda k: abs(RASIO[k].width / RASIO[k].height - r))


# --------------------------------------------------------------------------
# Pustaka B-roll
#
# Format "audio spine + overlay" memisahkan suara dari gambar: satu pidato
# berjalan terus, puluhan klip visual dari sumber lain ditumpuk di atasnya.
# Klip-klip itu dipakai berulang lintas video, jadi hasil analisisnya disimpan
# sekali dan dipakai selamanya — sama seperti concept profile.
# --------------------------------------------------------------------------


class BrollClip(BaseModel):
    src: str
    durasi: float
    width: int = 0
    height: int = 0
    punya_audio: bool = False

    # Diisi sekali oleh analisis visual, lalu dipakai berkali-kali.
    deskripsi: str = Field(default="", description="Apa yang terlihat di klip ini")
    tag: list[str] = Field(default_factory=list, description="Kata kunci pencarian cepat")
    checksum: str = Field(default="", description="Untuk mendeteksi file berubah")

    @property
    def siap(self) -> bool:
        return bool(self.deskripsi)


class ClipLibrary(BaseModel):
    clips: list[BrollClip] = Field(default_factory=list)
    versi: int = 1

    def by_src(self, src: str) -> BrollClip | None:
        return next((c for c in self.clips if c.src == src), None)

    @property
    def siap(self) -> list[BrollClip]:
        return [c for c in self.clips if c.siap]


# --------------------------------------------------------------------------
# EDL untuk format overlay
# --------------------------------------------------------------------------


class AudioSpine(BaseModel):
    """Tulang punggung suara: potongan pidato yang dirangkai jadi satu alur."""

    src: str
    cuts: list[PlannedCut] = Field(min_length=1)

    @property
    def durasi(self) -> float:
        return sum(c.durasi for c in self.cuts)


class VideoSlot(BaseModel):
    """Satu klip B-roll yang menempati rentang waktu tertentu di timeline output.

    `t` adalah posisi di timeline HASIL, sedangkan `in_`/`out` menunjuk ke dalam
    file klipnya sendiri. Keduanya tidak berhubungan — itulah inti pemisahan
    audio dan video di format ini.
    """

    model_config = ConfigDict(populate_by_name=True)

    t: float = Field(ge=0, description="Detik mulai di timeline output")
    durasi: float = Field(gt=0, description="Berapa lama slot ini tampil")
    src: str = Field(description="File klip B-roll")
    in_: float = Field(default=0.0, alias="in", ge=0, description="Detik mulai di dalam klip")
    # Bilah hitam yang terbakar di berkas sumber, dibuang sebelum crop rasio.
    # Tanpa ini, memotong ke 9:16 akan MEMBAWA SERTA bilahnya.
    crop: str = ""
    # Ke mana jendela 9:16 diarahkan. Kosong = tengah frame (perilaku lama).
    fokus_x: float | None = None
    fokus_y: float | None = None
    arah: float = 0.0
    # Jalur wajah selama slot: [[detik_relatif, fx, fy], ...]. Kosong atau satu
    # titik berarti bingkai diam. Lihat wajah.lacak dan AMBANG_GERAK di sana.
    jalur: list[list[float]] = Field(default_factory=list)
    zoom: float = Field(default=1.0, ge=1.0, le=1.6)
    alasan: str = ""

    @property
    def t_akhir(self) -> float:
        return self.t + self.durasi


class OverlayEDL(BaseModel):
    """EDL untuk format audio spine + B-roll.

    Bedanya dengan EDL biasa: di sana satu potongan membawa audio dan videonya
    sekaligus; di sini audio dan video berjalan di jalur terpisah.
    """

    timeline_name: str
    concept_id: str
    resolution: Resolution = Field(default_factory=Resolution)
    fps: int = 30
    audio: AudioSpine
    video: list[VideoSlot] = Field(min_length=1)
    music: Music | None = None
    captions: list[Caption] = Field(default_factory=list)
    caption_style: CaptionStyle = Field(default_factory=CaptionStyle)

    @property
    def total_duration(self) -> float:
        return self.audio.durasi

    def celah(self) -> list[tuple[float, float]]:
        """Rentang timeline yang belum tertutup klip mana pun."""
        kosong: list[tuple[float, float]] = []
        cursor = 0.0
        for slot in sorted(self.video, key=lambda s: s.t):
            if slot.t > cursor + 0.04:
                kosong.append((cursor, slot.t))
            cursor = max(cursor, slot.t_akhir)
        if cursor < self.total_duration - 0.04:
            kosong.append((cursor, self.total_duration))
        return kosong


class EDL(BaseModel):
    timeline_name: str
    concept_id: str
    target_duration: float
    resolution: Resolution = Field(default_factory=Resolution)
    fps: int = 30
    cuts: list[Cut] = Field(min_length=1)
    captions: list[Caption] = Field(default_factory=list)
    music: Music | None = None
    caption_style: CaptionStyle = Field(default_factory=CaptionStyle)

    @property
    def total_duration(self) -> float:
        return sum(c.durasi for c in self.cuts)
