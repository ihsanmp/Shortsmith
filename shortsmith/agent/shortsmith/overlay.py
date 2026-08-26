"""Penyusunan OverlayEDL: satu jalur suara, satu jalur gambar, terpisah.

## Bedanya dengan EDL biasa

Di EDL biasa satu potongan membawa suara DAN gambarnya sendiri, lalu potongan
disambung berurutan. Konsekuensinya panjang shot punya batas bawah alami: tiap
potongan harus memuat satu frasa utuh, jadi tidak bisa lebih pendek dari kalimat
terpendek yang masih masuk akal — sekitar dua detik.

Di sini keduanya lepas. Suara mengalir terus di jalurnya sendiri, sementara
gambar berganti mengikuti ritme konsep tanpa peduli kalimatnya sampai mana.
Itulah satu-satunya cara mencapai shot 1,25 detik yang terukur di video contoh,
dan tidak ada parameter di format satu jalur yang bisa menjembataninya.

## Penyusun klip versi pertama

Pencocokan gambar dengan MAKNA kalimat butuh pustaka klip yang sudah dilabeli
dan satu tahap penalaran lagi (identitas `pelabel` dan `penata`). Yang di sini
sengaja mekanis: bergilir antar klip, dan maju terus di dalam tiap klip supaya
tidak mengulang potongan yang sama. Hasilnya bentuk yang benar dengan gambar
yang belum tentu nyambung — dan bentuk yang benar itu prasyarat, bukan hiasan.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime
from pathlib import Path

from .captions import derive_captions
from .config import SETTINGS
from .models import (
    EDL,
    Adegan,
    AudioSpine,
    ConceptProfile,
    Music,
    Cut,
    CutPlan,
    OverlayEDL,
    PlannedCut,
    ProjectMap,
    VideoMap,
    Word,
    VideoSlot,
    resolution_for,
)
from .penata import tata
from .rhythm import generate_slots
from .wajah import lacak, periksa_adegan

log = logging.getLogger(__name__)

# Sisihkan sedikit dari ujung tiap klip. Awal klip sering berisi fade-in atau
# frame hitam, dan ujungnya sering terpotong di tengah gerakan.
TEPI = 0.25

# Di atas ini, satu "adegan" pasti bukan adegan melainkan seluruh berkas yang
# deteksi adegannya tidak menemukan potongan apa pun. Lihat pemakaiannya di
# susun_broll.
ADEGAN_PANJANG = 30.0

# Di bawah jumlah ini, penyaringan tokoh lebih merugikan daripada menolong —
# lihat _saring_tokoh.
MIN_ADEGAN_TERSISA = 8

# Sekelompok wajah harus muncul minimal sebanyak ini untuk dianggap tokoh
# pendukung. Di bawahnya itu orang yang kebetulan lewat, bukan bagian cerita.
MIN_PENDUKUNG = 3


# Cadangan saja. Angka sebenarnya datang dari `profile.porsi_pembicara`, yang
# DIUKUR dari video contoh (lihat gaya_visual.py).
#
# Nilainya sengaja 0.0: kalau karena suatu hal pengukuran tidak sampai ke sini,
# hasilnya montase B-roll murni — bukan wajah pembicara yang muncul di 60%
# durasi tanpa pernah diminta. Bawaan yang salah harus condong ke yang paling
# tidak mengejutkan.
PORSI_PEMBICARA = 0.0


def _jalur(
    src: str, awal: float, panjang: float, crop: str,
    rujukan: list[list[float]] | None = None,
) -> list[list[float]]:
    """Jalur wajah untuk satu slot, siap disimpan di VideoSlot.

    Dipanggil per slot dan bukan per adegan: satu adegan bisa dipakai sebagian
    saja, dan yang perlu diikuti bingkai adalah gerakan di potongan yang benar-
    benar tampil, bukan rata-rata seluruh adegan.
    """
    titik = lacak(src, mulai=awal, panjang=panjang, crop=crop, rujukan=rujukan)
    return [[round(t, 3), round(x, 4), round(y, 4), round(a, 3)] for t, x, y, a in titik] if titik else []


def _sumber_pada(t: float, cuts: list[PlannedCut]) -> float | None:
    """Waktu di rekaman asli yang sedang terdengar pada detik `t` di timeline.

    Ini yang membuat wajah pembicara boleh muncul: gambar diambil dari detik
    yang SAMA dengan suaranya, jadi gerak bibirnya cocok. Mengambil detik
    sembarang dari rekaman yang sama akan langsung terlihat salah.
    """
    jalan = 0.0
    for c in cuts:
        if jalan <= t < jalan + c.durasi:
            return c.in_ + (t - jalan)
        jalan += c.durasi
    return None


def _nomor_potongan(t: float, cuts: list[PlannedCut]) -> int | None:
    """Potongan suara ke berapa yang sedang berbunyi pada detik `t`."""
    jalan = 0.0
    for i, c in enumerate(cuts):
        if jalan <= t < jalan + c.durasi:
            return i
        jalan += c.durasi
    return None


def _muat_sepotong(mulai: float, panjang: float, cuts: list[PlannedCut]) -> bool:
    """Apakah slot ini berada seluruhnya di dalam SATU potongan suara.

    Suara disusun dari potongan yang diambil dari tempat berjauhan di rekaman.
    Di batas antar potongan, suaranya melompat — misalnya dari detik 145 ke
    detik 38. Gambar pembicara tidak ikut melompat: ia diekstrak sebagai satu
    rentang menerus dari titik mulainya.

    Jadi slot pembicara yang menyeberangi batas potongan pasti tidak sinkron
    setelah batas itu, sepanjang sisa slotnya. Terukur pada satu hasil: slot
    10,57-13,94 detik menyeberang di 12,24, dan sesudahnya wajahnya masih
    mengucapkan kalimat dari menit 2:24 sementara yang terdengar detik 38.

    Memeriksa titik MULAI saja tidak menangkap ini — itulah kenapa penjagaan
    sebelumnya lolos.
    """
    awal = _nomor_potongan(mulai, cuts)
    akhir = _nomor_potongan(mulai + max(0.0, panjang - 1e-3), cuts)
    return awal is not None and awal == akhir


def susun_broll(
    total: float,
    profile: ConceptProfile,
    adegan: list[Adegan],
    *,
    seed: int | None = None,
    pembicara: tuple[str, list[PlannedCut], str] | None = None,
    porsi_pembicara: float = PORSI_PEMBICARA,
    kata: list[Word] | None = None,
    rujukan: list[list[float]] | None = None,
) -> list[VideoSlot]:
    """Isi timeline sepanjang `total` detik dengan potongan dari `adegan`.

    Satuan pemilihan adalah ADEGAN, bukan file. Satu video kompilasi berisi 30
    adegan memberi 30 pilihan berbeda, bukan satu. Ini yang membuat pengguna
    tidak perlu memotong-motong bahannya sendiri sebelum mengunggah.

    `pembicara` berisi (path, potongan_suara). Kalau diisi, sebagian slot
    menampilkan pembicara pada detik yang sinkron dengan suaranya.
    """
    if not adegan:
        raise ValueError("Tidak ada adegan B-roll untuk disusun.")

    # Ritme dikunci ke kisi frame SEBELUM klip dipilih, bukan sesudahnya.
    #
    # Dulu penyejajaran dilakukan di akhir, setelah semua slot terbentuk. Itu
    # membuat setiap keputusan diambil atas waktu yang kemudian berubah. Akibat
    # nyatanya: satu slot pembicara lolos pemeriksaan "utuh di dalam satu
    # potongan suara" pada t=27,70, lalu penyejajaran menggesernya ke t=27,13 —
    # mundur melewati batas potongan di 27,67 — dan wajahnya jadi tidak sinkron
    # di sisa slot.
    #
    # Diperiksa atas waktu final, pemeriksaan itu berarti apa adanya.
    rentang = _kunci_ke_frame(generate_slots(total, profile, seed=seed), SETTINGS.fps)
    rng = random.Random(seed)

    # Penataan berdasarkan makna kalimat. Mengembalikan peta slot -> adegan yang
    # bisa TIDAK LENGKAP; slot yang tidak tercakup jatuh ke tumpukan kartu di
    # bawah, jadi jawaban setengah pun tetap memperbaiki sebagian.
    pilihan: dict[int, int] = {}
    if kata and pembicara is not None:
        pilihan = tata(rentang, adegan, pembicara[1], kata, tepi=TEPI)

    # Kunci identitas adalah (file, waktu mulai) — dua adegan dari file yang sama
    # adalah dua pilihan berbeda, dan itulah inti perubahan ini.
    kunci = [(a.src, a.start) for a in adegan]
    durasi = {k: a.durasi for k, a in zip(kunci, adegan)}
    mulai_adegan = {k: a.start for k, a in zip(kunci, adegan)}
    crop_adegan = {k: a.crop for k, a in zip(kunci, adegan)}
    peta_fokus = {k: (a.fokus_x, a.fokus_y, a.arah) for k, a in zip(kunci, adegan)}

    # Kursor per adegan supaya tiap pengambilan maju, bukan mengulang bagian
    # yang sama. Titik awalnya diacak agar dua project dengan bahan yang sama
    # tidak menghasilkan urutan gambar yang identik.
    kursor = {
        k: a.start + TEPI + rng.random() * max(0.0, a.durasi - 2 * TEPI)
        for k, a in zip(kunci, adegan)
    }

    perlu_broll = len(rentang) - round(len(rentang) * (porsi_pembicara if pembicara else 0))
    if perlu_broll > len(adegan):
        # Dikatakan terus terang, dengan angka yang bisa ditindaklanjuti.
        # Menyembunyikan ini akan membuat pengguna mengira kodenya yang malas,
        # padahal bahannya yang kurang.
        log.warning(
            "%d slot B-roll tapi hanya %d adegan tersedia — sebagian adegan "
            "muncul lebih dari sekali. Tambah ragam bahannya untuk menghindarinya.",
            perlu_broll, len(adegan),
        )

    # Slot mana yang menampilkan pembicara. Disebar merata, bukan diacak:
    # pengelompokan acak bisa meninggalkan 10 detik tanpa wajah sama sekali,
    # lalu memunculkannya beruntun — dan itu terlihat seperti kesalahan.
    slot_pembicara: set[int] = set()
    if pembicara is not None and porsi_pembicara > 0:
        jumlah = min(len(rentang), round(len(rentang) * porsi_pembicara))
        if jumlah:
            langkah = len(rentang) / jumlah
            slot_pembicara = {int(i * langkah) for i in range(jumlah)}

    # Adegan yang sudah dipesan penata dikeluarkan dari tumpukan, supaya tidak
    # terbagikan dua kali lewat jalur yang berbeda.
    dipesan = {kunci[i] for i in pilihan.values()}
    sisa_kunci = [k for k in kunci if k not in dipesan] or list(kunci)

    slots: list[VideoSlot] = []
    tumpukan: list[tuple[str, float]] = []
    terakhir: tuple[str, float] | None = None

    for putaran, (mulai, panjang) in enumerate(rentang):
        if putaran in slot_pembicara:
            src_p, cuts_p, crop_p = pembicara  # type: ignore[misc]
            awal_p = _sumber_pada(mulai, cuts_p)
            # Slot yang menyeberang batas potongan suara tidak mungkin sinkron
            # di sisa durasinya — lihat _muat_sepotong. Slot itu diserahkan ke
            # B-roll, bukan dipaksakan menampilkan wajah yang meleset.
            if awal_p is not None and not _muat_sepotong(mulai, panjang, cuts_p):
                awal_p = None
            if awal_p is not None:
                # Wajah pembicara dicari di detik yang benar-benar dipakai, bukan
                # sekali untuk seluruh rekaman: dalam 27 menit bicara, orangnya
                # bergeser, bersandar, dan berpindah kursi.
                fokus_p = periksa_adegan(
                    src_p, mulai=awal_p, panjang=panjang, crop=crop_p
                )
                slots.append(
                    VideoSlot(
                        t=round(mulai, 3),
                        durasi=round(panjang, 3),
                        src=src_p,
                        **{"in": round(awal_p, 3)},
                        crop=crop_p,
                        fokus_x=fokus_p.fokus_x if fokus_p else None,
                        fokus_y=fokus_p.fokus_y if fokus_p else None,
                        arah=fokus_p.arah if fokus_p else 0.0,
                        jalur=_jalur(src_p, awal_p, panjang, crop_p, rujukan),
                        alasan="pembicara (sinkron dengan suara)",
                    )
                )
                # Sengaja TIDAK mengubah `terakhir`: pembicara bukan bagian dari
                # tumpukan klip, jadi ia tidak boleh ikut menggeser giliran.
                continue


        if putaran in pilihan:
            k = kunci[pilihan[putaran]]
            alasan_pilih = "dipilih penata dari makna kalimat"
        else:
            k = None
            alasan_pilih = ""

        # Model "tumpukan kartu": semua klip dikocok, dibagikan satu per slot,
        # dan tidak ada yang muncul lagi sampai seluruh klip lain habis terpakai.
        # Ini memberi jarak MAKSIMUM antar kemunculan — jauh lebih baik daripada
        # bergilir A-B-A-B, yang membuat dua klip terasa seperti berkedip.
        if k is None:
            if not tumpukan:
                tumpukan = list(sisa_kunci)
                rng.shuffle(tumpukan)
                # Jangan sampai kartu terakhir tumpukan lama bersambung langsung
                # dengan kartu pertama tumpukan baru.
                if len(tumpukan) > 1 and tumpukan[0] == terakhir:
                    tumpukan.append(tumpukan.pop(0))

            # Kartu pertama yang CUKUP PANJANG untuk slot ini, bukan sekadar
            # kartu pertama. Adegan yang lebih pendek dari slotnya akan
            # menyeberang ke adegan berikutnya di tengah slot, dan satu slot
            # berisi dua gambar tak berhubungan terlihat seperti kesalahan
            # render. Terukur di satu hasil: slot 1,80 detik diisi adegan 0,83
            # detik, dan gambarnya berganti di tengah.
            butuh = panjang + TEPI
            pas = next(
                (i for i, kk in enumerate(tumpukan) if durasi[kk] >= butuh), None
            )
            if pas is None:
                # Tidak ada yang muat di tumpukan. Ambil yang TERPANJANG dari
                # seluruh pilihan — masih bisa menyeberang, tapi sesedikit
                # mungkin, dan lebih baik daripada mengambil yang paling pendek.
                k = max(kunci, key=lambda kk: durasi[kk])
                if k in tumpukan:
                    tumpukan.remove(k)
            else:
                k = tumpukan.pop(pas)

        terakhir = k
        src, _ = k

        # Batas atas dan bawah dikurung DI DALAM adegan itu saja. Melewatinya
        # berarti slot berisi dua gambar berbeda — persis masalah yang dipecahkan
        # oleh pemecahan adegan.
        awal_adegan = mulai_adegan[k]
        batas = max(awal_adegan, awal_adegan + durasi[k] - panjang - TEPI)

        awal = kursor[k]
        if awal > batas:
            awal = awal_adegan + TEPI if batas >= awal_adegan + TEPI else awal_adegan
        kursor[k] = awal + panjang

        # Gambar dari REKAMAN SUARA wajib diambil pada detik yang sedang
        # terdengar, berapa pun jalur yang memilihnya.
        #
        # Rekaman suara sering ikut dikirim sebagai klip B-roll juga. Karena
        # rekaman satu-take tidak punya potongan adegan, seluruh durasinya jadi
        # satu adegan, dan penyusun boleh mengambil detik mana pun darinya.
        # Begitu yang terambil wajah orangnya, mulutnya terlihat mengucapkan
        # kalimat yang berbeda dari yang terdengar. Terukur pada satu hasil:
        # gambar dari detik 335 dipasang di atas suara dari detik 1609.
        #
        # Ini tidak bisa diperbaiki di tahap render dan tidak bisa disamarkan —
        # penonton langsung melihatnya. Jadi dipaksa sinkron di sini.
        if pembicara is not None and src == pembicara[0]:
            sinkron = _sumber_pada(mulai, pembicara[1])
            if sinkron is not None and not _muat_sepotong(mulai, panjang, pembicara[1]):
                sinkron = None
            if sinkron is None:
                # Tidak ada suara yang sedang berjalan di titik ini, jadi tidak
                # ada detik yang "benar" untuk ditampilkan. Lebih baik lewati
                # klip ini daripada menampilkan wajah yang jelas tidak sinkron.
                kursor[k] = awal
                tumpukan.insert(0, k)
                k = max(
                    (kk for kk in kunci if kk[0] != pembicara[0]),
                    key=lambda kk: durasi[kk],
                    default=k,
                )
                src, _ = k
                awal_adegan = mulai_adegan[k]
                batas = max(awal_adegan, awal_adegan + durasi[k] - panjang - TEPI)
                awal = min(max(kursor[k], awal_adegan), batas)
            else:
                awal = batas = sinkron

        fx, fy, arah = peta_fokus[k]
        # Adegan sepanjang ini bukan adegan sungguhan — itu berkas yang deteksi
        # adegannya tidak menemukan potongan sama sekali (rekaman satu-take),
        # sehingga seluruh berkas menjadi satu "adegan". Satu titik fokus tidak
        # mewakili puluhan menit gambar, jadi dicari ulang di detik yang dipakai.
        if durasi[k] > ADEGAN_PANJANG:
            ulang = periksa_adegan(
                src, mulai=min(awal, batas), panjang=panjang, crop=crop_adegan[k]
            )
            fx, fy, arah = (
                (ulang.fokus_x, ulang.fokus_y, ulang.arah) if ulang else (None, None, 0.0)
            )

        slots.append(
            VideoSlot(
                t=round(mulai, 3),
                durasi=round(panjang, 3),
                src=src,
                **{"in": round(min(awal, batas), 3)},
                crop=crop_adegan[k],
                fokus_x=fx,
                fokus_y=fy,
                arah=arah,
                jalur=_jalur(src, min(awal, batas), panjang, crop_adegan[k], rujukan),
                alasan=alasan_pilih or f"adegan @{awal_adegan:.1f}s, putaran {putaran // len(kunci) + 1}",
            )
        )

    return slots


def _kunci_ke_frame(
    rentang: list[tuple[float, float]], fps: int
) -> list[tuple[float, float]]:
    """Kunci batas tiap slot ke kisi frame, sebelum klipnya dipilih.

    Yang dibulatkan adalah BATAS kumulatifnya, bukan durasi tiap slot sendiri-
    sendiri. Membulatkan durasi satu per satu tetap menumpuk galat; membulatkan
    batasnya membuat tiap galat dikoreksi lagi di slot berikutnya, sehingga
    total selisihnya tidak pernah lebih dari satu frame.
    """
    if not rentang or fps <= 0:
        return rentang

    def ke_frame(t: float) -> float:
        return round(t * fps) / fps

    hasil: list[tuple[float, float]] = []
    jalan = ke_frame(rentang[0][0])
    for mulai, panjang in rentang:
        akhir = ke_frame(mulai + panjang)
        if akhir <= jalan:
            akhir = jalan + 1.0 / fps
        hasil.append((round(jalan, 4), round(akhir - jalan, 4)))
        jalan = akhir
    return hasil


def _sejajarkan_frame(slots: list[VideoSlot], fps: int) -> None:
    """Kunci tiap batas slot ke kisi frame, di tempat.

    ## Kenapa ini menentukan sinkronnya caption

    Slot dihasilkan dengan durasi pecahan bebas (mis. 1,4823 detik), tapi ffmpeg
    meng-encode jalur gambar pada fps tetap — jadi tiap segmen dibulatkan ke
    jumlah frame utuh. Selisih pembulatan per segmen kecil, tapi ia MENUMPUK.

    Diukur pada satu render nyata: 40 slot menghasilkan jalur gambar 48,533
    detik sementara jalur suara 48,971 detik — meleset 0,438 detik. Caption
    dibakar ke jalur gambar, sedangkan posisinya dihitung dari garis waktu
    suara, sehingga ia tampak makin tertinggal menjelang akhir video.

    Yang dikunci adalah BATAS kumulatifnya, bukan durasi tiap slot sendiri-
    sendiri. Membulatkan durasi satu per satu tetap menumpuk galat; membulatkan
    batasnya membuat tiap galat dikoreksi lagi di slot berikutnya, sehingga
    total selisihnya tidak pernah lebih dari satu frame.
    """
    if not slots or fps <= 0:
        return

    def ke_frame(t: float) -> float:
        return round(t * fps) / fps

    jalan = ke_frame(slots[0].t)
    for s in slots:
        akhir = ke_frame(s.t + s.durasi)
        if akhir <= jalan:
            akhir = jalan + 1.0 / fps
        s.t = round(jalan, 4)
        s.durasi = round(akhir - jalan, 4)
        jalan = akhir


def _identitas_terbesar(adegan: list[Adegan]) -> list[Adegan]:
    """Kelompok adegan yang menampilkan satu orang yang sama, yang terbanyak.

    Pengelompokannya serakah: tiap adegan masuk ke kelompok pertama yang wajahnya
    cocok, atau memulai kelompok baru. Cukup untuk keperluan di sini — yang
    dicari hanya kelompok TERBESAR, dan kelompok besar tidak berubah peringkat
    karena beberapa anggota di pinggirnya jatuh ke kelompok tetangga.

    Kelompok yang terlalu kecil dikembalikan kosong: orang yang cuma lewat dua
    kali bukan tokoh pendukung, dan memasukkannya justru menambah wajah asing.
    """
    from .wajah import AMBANG_SAMA, mirip

    kelompok: list[list[Adegan]] = []
    for a in adegan:
        if not a.sidik:
            continue
        for k in kelompok:
            if mirip(a.sidik, k[0].sidik) >= AMBANG_SAMA:
                k.append(a)
                break
        else:
            kelompok.append([a])

    if not kelompok:
        return []
    terbesar = max(kelompok, key=len)
    return terbesar if len(terbesar) >= MIN_PENDUKUNG else []


def _saring_tokoh(adegan: list[Adegan], suara: VideoMap, kanal: str = "") -> list[Adegan]:
    """Buang adegan yang menampilkan ORANG LAIN, bukan tokoh video ini.

    Satu video shorts menceritakan satu orang. Klip yang menampilkan wajah asing
    memutus cerita itu seketika — penonton membaca perpindahan wajah sebagai
    ganti subjek, bukan sebagai selingan.

    Yang dibuang HANYA adegan yang wajahnya jelas milik orang lain. Adegan tanpa
    wajah (pemandangan, tangan, detail objek) tetap dipakai: ia tidak menampilkan
    siapa pun, jadi tidak mungkin menampilkan orang yang salah.

    Diukur pada bahan pengguna, dari 135 adegan: 19 menampilkan tokoh utama, 46
    menampilkan orang lain, sisanya tanpa wajah — jadi penyaringan ini membuang
    sepertiga bahan dan menyisakan 89, masih jauh lebih banyak dari jumlah slot.

    ## Kenapa memori tidak lagi menang begitu saja

    Sebelum ini, tokoh yang diingat dipakai TANPA diperiksa, dengan alasan tokoh
    adalah properti kanal. Alasannya benar; pelaksanaannya tidak — memorinya satu
    untuk seluruh mesin, jadi wajah dari video pertama yang pernah dikenali
    dipakai untuk semua video sesudahnya, termasuk yang orangnya lain.

    Terbaca di log produksi, 20 kali pada satu job::

        tokoh utama dari memori: Berani Ambil Aksi
        tokoh pendukung dari memori: ... (0 adegan cocok)
        hanya 1 adegan menampilkan tokoh yang sama (dari 150)

    Bahannya podcast dengan narasumber yang sama sekali berbeda. Sistemnya gagal
    dengan aman — penyaringan dilewati saat sisanya terlalu sedikit, jadi
    hasilnya tidak rusak — tapi fiturnya tidak pernah sekali pun bekerja.

    Sekarang rujukannya selalu diturunkan ulang dari rekaman suara project ini
    (enam frame, murah), dan memori hanya dipakai kalau ia memang orang yang
    sama. Kalau sama, keduanya digabung: memori membawa pose yang tidak
    tertangkap enam sampel hari ini, dan itulah gunanya menyimpan.
    """
    from . import tokoh as memori
    from .wajah import bisa_kenal, orang_sama, rujukan_tokoh

    if not bisa_kenal():
        return adegan

    diingat = memori.muat(kanal)
    ingat_utama = diingat.get("utama")

    # Rekaman suara adalah rujukan yang paling bisa dipercaya untuk "siapa video
    # ini": orangnya di sana sepanjang durasi, dan memang suaranya yang dipakai.
    turunan = rujukan_tokoh(
        suara.media.path, suara.media.durasi, crop=suara.media.crop
    )

    if turunan and ingat_utama and orang_sama(turunan[0], ingat_utama.sidik):
        rujukan = ingat_utama.sidik + turunan
        log.info(
            "tokoh utama cocok dengan memori: %s (%d pose diingat + %d dari bahan ini)",
            ingat_utama.catatan or "tanpa catatan", len(ingat_utama.sidik), len(turunan),
        )
    elif turunan:
        rujukan = turunan
        if ingat_utama:
            log.info(
                "tokoh utama di bahan ini bukan yang diingat (%s) — memori diperbarui",
                ingat_utama.catatan or "tanpa catatan",
            )
            # Tokoh pendukung ikut dibuang, bukan cuma yang utama.
            #
            # Keduanya dicatat dari bahan yang sama. Kalau ternyata tokoh
            # utamanya orang lain, catatan pendukungnya berasal dari video yang
            # lain juga — dan ia bisa tetap "cocok" di sini hanya karena orang
            # itu kebetulan ikut muncul sebagai wajah asing. Terbukti saat
            # diuji: tanpa pembuangan ini, kelima adegan wajah asing justru
            # LOLOS sebagai tokoh pendukung.
            diingat.pop("pendukung", None)
        memori.catat("utama", rujukan, Path(suara.media.path).stem, kanal)
    elif ingat_utama:
        # Wajah pembicara tidak terbaca sama sekali, jadi tidak ada yang bisa
        # dibandingkan. Memori dipakai apa adanya — itu satu-satunya yang ada,
        # dan penyaringan yang terlalu ketat ditangkap penjaga di bawah.
        rujukan = ingat_utama.sidik
        log.info(
            "wajah pembicara tidak terbaca — memakai tokoh dari memori: %s",
            ingat_utama.catatan or "tanpa catatan",
        )
    else:
        rujukan = []

    if not rujukan:
        log.warning(
            "wajah pembicara tidak terbaca dari %s — penyaringan tokoh dilewati, "
            "klip bisa menampilkan orang lain",
            Path(suara.media.path).name,
        )
        return adegan

    utama = [a for a in adegan if a.sidik is None or orang_sama(a.sidik, rujukan)]
    lain = [a for a in adegan if a not in utama]

    # Tokoh pendukung: SATU identitas, yang paling sering muncul di antara wajah
    # bukan-tokoh-utama.
    #
    # Meloloskan semua yang bukan tokoh utama bukan berarti "pakai orang kedua" —
    # diukur pada bahan pengguna, 52 adegan itu berisi 23 orang BERBEDA. Yang
    # masuk akan jadi rombongan orang asing bergantian, persis yang penyaringan
    # ini dibuat untuk cegah. Yang benar-benar tokoh kedua hanya satu kelompok
    # besar (17 adegan); sisanya ekor panjang orang yang lewat sekali.
    #
    # Yang diingat diperiksa dulu, tidak langsung dipakai. Tokoh pendukung tidak
    # punya penurunan mandiri seperti tokoh utama punya rekaman suara, jadi satu-
    # satunya cara mengetahui catatannya masih berlaku adalah menghitung berapa
    # adegan yang benar-benar cocok. Nol berarti orangnya tidak ada di bahan ini,
    # dan memakainya berarti tidak memakai tokoh pendukung sama sekali.
    ingat_pendukung = diingat.get("pendukung")
    pendukung: list[Adegan] = []
    if ingat_pendukung:
        pendukung = [
            a for a in lain if a.sidik and orang_sama(a.sidik, ingat_pendukung.sidik)
        ]
        if len(pendukung) < MIN_PENDUKUNG:
            log.info(
                "tokoh pendukung yang diingat (%s) hampir tidak muncul di bahan ini "
                "(%d adegan) — dicari ulang dari bahan",
                ingat_pendukung.catatan or "tanpa catatan", len(pendukung),
            )
            pendukung, ingat_pendukung = [], None
        else:
            log.info(
                "tokoh pendukung dari memori: %s (%d adegan cocok)",
                ingat_pendukung.catatan or "tanpa catatan", len(pendukung),
            )

    if not ingat_pendukung:
        pendukung = _identitas_terbesar(lain)
        if pendukung:
            memori.catat(
                "pendukung",
                [a.sidik for a in pendukung if a.sidik],
                pendukung[0].label or "",
                kanal,
            )

    simpan = utama + pendukung
    dibuang = len(adegan) - len(simpan)
    if pendukung:
        log.info("tokoh pendukung dipakai: %d adegan", len(pendukung))

    # Kalau penyaringan menyisakan terlalu sedikit, bahannya yang tidak cocok —
    # dan memaksakannya menghasilkan gambar yang sama berulang-ulang, yang lebih
    # buruk daripada sesekali menampilkan orang lain. Dikatakan terus terang.
    if len(simpan) < MIN_ADEGAN_TERSISA:
        # Sarannya menyebut SIAPA yang dicari. Versi lama cuma bilang "tambah
        # klip yang menampilkan orangnya", dan saat rujukannya sendiri yang
        # salah — orang dari video lain — saran itu menyuruh pengguna mengejar
        # sesuatu yang tidak akan pernah menolong.
        log.warning(
            "hanya %d adegan menampilkan %s (dari %d) — terlalu sedikit untuk "
            "menyusun timeline, jadi penyaringan dilewati. Tambah klip yang "
            "menampilkan orang itu; kalau yang dicari memang bukan dia, hapus "
            "tokoh.json supaya dikenali ulang.",
            len(simpan), Path(suara.media.path).stem, len(adegan),
        )
        return adegan

    log.info(
        "penyaringan tokoh: %d adegan dipakai, %d dibuang karena menampilkan orang lain",
        len(simpan), dibuang,
    )
    return simpan


def build_overlay_edl(
    plan: CutPlan,
    vmap: ProjectMap,
    profile: ConceptProfile,
    *,
    concept_id: str,
    seed: int | None = None,
    music: Music | None = None,
    rujukan: list[list[float]] | None = None,
) -> OverlayEDL:
    """Rakit OverlayEDL dari rencana potongan suara + klip yang tersedia."""
    suara = vmap.videos[0]

    # Seluruh potongan suara datang dari VIDEO 0 — sudah dipaksakan validator di
    # decide.py, jadi di sini cukup dipakai apa adanya.
    cuts = []
    for c in plan.cuts:
        f = periksa_adegan(
            suara.media.path, mulai=c.in_, panjang=c.durasi, crop=suara.media.crop
        )
        cuts.append(
            Cut(
                src=suara.media.path,
                crop=suara.media.crop,
                fokus_x=f.fokus_x if f else None,
                fokus_y=f.fokus_y if f else None,
                arah=f.arah if f else 0.0,
                **c.model_dump(by_alias=True),
            )
        )
    total = sum(c.durasi for c in cuts)

    # Adegan dari SEMUA file B-roll digabung jadi satu kumpulan. Dari sudut
    # pandang penyusun, tidak penting sebuah adegan datang dari file mana —
    # yang penting ia satu gambar utuh yang berbeda dari yang lain.
    adegan: list[Adegan] = []
    for v in vmap.videos[1:]:
        if v.adegan:
            for a in v.adegan:
                # Crop per adegan lebih tepat dan menang. Yang tingkat berkas
                # hanya dipakai kalau adegannya belum punya (peta lama, atau
                # deteksi per adegan tidak menemukan apa-apa di situ).
                adegan.append(
                    a if a.crop else a.model_copy(update={"crop": v.media.crop})
                )
        else:
            # File tanpa hasil deteksi (mis. rekaman satu-take) tetap dipakai
            # sebagai satu adegan utuh, bukan dibuang.
            adegan.append(
                Adegan(src=v.media.path, start=0.0, end=v.media.durasi, crop=v.media.crop)
            )

    if not adegan:
        raise ValueError(
            "Format overlay butuh minimal satu klip B-roll, tapi hanya ada video suara. "
            "Unggah klip di kolom 'Klip B-roll', atau pakai konsep format satu jalur."
        )

    adegan = _saring_tokoh(adegan, suara, concept_id)

    slots = susun_broll(
        total,
        profile,
        adegan,
        seed=seed,
        pembicara=(suara.media.path, plan.cuts, suara.media.crop),
        kata=suara.words,
        # Angkanya datang dari konsep, bukan dari konstanta di modul ini.
        # Ganti video contoh -> ganti gaya, tanpa menyentuh kode.
        porsi_pembicara=profile.porsi_pembicara,
        rujukan=rujukan,
    )

    _sejajarkan_frame(slots, SETTINGS.fps)

    # Caption tetap diturunkan dari kata-kata VIDEO 0: yang terdengar dan yang
    # tertulis harus sama, tidak peduli gambar apa yang sedang tampil.
    captions = derive_captions(cuts, suara.words, profile.caption)

    resolusi = resolution_for(profile.aspect_ratio)
    log.info(
        "overlay: audio %.1fs dari %d potongan, video %d slot dari %d adegan "
        "(%d file), rasio %s (%dx%d)",
        total, len(cuts), len(slots), len(adegan), len(vmap.videos) - 1,
        profile.aspect_ratio, resolusi.width, resolusi.height,
    )

    edl = OverlayEDL(
        timeline_name=f"short_{datetime.now():%Y%m%d_%H%M%S}",
        concept_id=concept_id,
        resolution=resolusi,
        fps=SETTINGS.fps,
        audio=AudioSpine(src=suara.media.path, cuts=plan.cuts),
        video=slots,
        captions=captions,
        caption_style=profile.caption,
        # Dulu di sini tertulis `music=None` dengan alasan "musik ditambahkan
        # manual setelah render". Itu benar sampai form punya pemilih lagu --
        # sejak itu, baris ini diam-diam membuang berkas yang sengaja dipilih
        # pengguna, dan tidak ada yang memperbaruinya.
        #
        # Yang membuatnya sulit terlihat: daemon MENCATAT "lagu: <nama>" di log
        # sebelum menyerahkannya, jadi log tampak meyakinkan sementara hasilnya
        # sunyi.
        music=music,
    )

    celah = edl.celah()
    if celah:
        # Celah berarti ada detik yang tidak tertutup gambar apa pun — layar
        # hitam di tengah video. Lebih baik ketahuan di sini daripada setelah
        # ditonton.
        raise ValueError(f"Timeline video berlubang di {celah}. Penyusunan slot gagal.")

    return edl


def edl_biasa(
    plan: CutPlan, vmap: ProjectMap, profile: ConceptProfile, *, concept_id: str
) -> EDL:
    """Jalur lama, dipisah ke sini supaya pipeline hanya punya satu percabangan."""
    from .pipeline import build_edl

    return build_edl(plan, vmap, profile, concept_id=concept_id)
