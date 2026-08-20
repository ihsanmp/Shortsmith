"""Kaidah editing yang dipegang agent saat membingkai ulang gambar.

Ini bukan kumpulan angka acak. Tiap kaidah di sini adalah aturan yang dipakai
editor sungguhan, diterjemahkan jadi sesuatu yang bisa dihitung dari data yang
sudah kita punya (posisi wajah dan arah pandangnya).

## Kenapa modul ini ada

Renderer sebelumnya memotong 9:16 dari TENGAH frame. Itu bukan keputusan
editing — itu ketiadaan keputusan. Sinematografer membingkai untuk 16:9, dan
"tengah" hampir tidak pernah jadi tempat subjeknya berada.

Contoh terukur dari bahan pengguna, satu shot dua orang bermain catur:

    subjek utama       : x = 0.26 (seperempat kiri), menghadap ke kanan
    crop tengah        : papan catur, subjeknya hilang di luar bingkai
    crop dengan kaidah : subjek di 40% kiri, ruang pandang terbuka ke kanan

## Kaidah yang diterapkan

**Ruang pandang (look-room / nose room).** Orang yang menghadap ke kanan diberi
ruang kosong di kanannya. Menempelkan wajah ke tepi yang ia hadapi membuat
bingkai terasa sesak dan seolah ia menabrak dinding; ruang di depan pandangan
membuat komposisinya bernapas dan mengarahkan mata penonton ke arah yang sama.

**Ruang kepala (headroom).** Mata ditaruh di sekitar sepertiga atas, bukan di
tengah bingkai. Wajah yang persis di tengah menyisakan ruang kosong berlebihan
di atas kepala dan memotong badan terlalu tinggi.

Kedua kaidah hanya berlaku sejauh gambarnya memungkinkan. Kalau jendela crop
sudah selebar sumbernya, tidak ada ruang untuk digeser dan kaidahnya diam —
itu benar, bukan kegagalan.
"""

from __future__ import annotations

# Di mana wajah ditaruh secara mendatar, sebagai pecahan lebar bingkai.
#
# Menghadap kanan -> wajah agak ke kiri, ruang kosong terbuka di kanan.
# Menghadap kamera -> tengah.
TARGET_MENGHADAP_KANAN = 0.40
TARGET_MENGHADAP_KIRI = 0.60
TARGET_TENGAH = 0.50

# Di bawah nilai ini, arah pandang dianggap lurus ke kamera. Wajah menghadap
# kamera yang digeser ke samping terlihat seperti salah bingkai, bukan seperti
# komposisi yang disengaja — jadi ambangnya sengaja tidak terlalu sensitif.
AMBANG_ARAH = 0.15

# Ketinggian target wajah, sebagai pecahan tinggi bingkai. Sepertiga atas.
TARGET_TINGGI = 0.38


def arah_pandang(mata_kanan_x: float, mata_kiri_x: float, hidung_x: float) -> float:
    """Ke mana wajah menghadap, dari -1 (kiri penuh) sampai +1 (kanan penuh).

    Diukur dari pergeseran hidung terhadap titik tengah kedua mata, dinormalkan
    oleh jarak antar mata supaya tidak bergantung pada ukuran wajah di frame.
    Saat kepala menoleh, hidung bergeser ke arah tolehan lebih dulu dan lebih
    jauh daripada matanya — itulah yang dipakai di sini.
    """
    jarak = abs(mata_kiri_x - mata_kanan_x)
    if jarak <= 0:
        return 0.0
    tengah = (mata_kanan_x + mata_kiri_x) / 2.0
    return max(-1.0, min(1.0, (hidung_x - tengah) / jarak))


def target_mendatar(arah: float) -> float:
    """Posisi mendatar yang dituju untuk wajah, mengikuti kaidah ruang pandang."""
    if arah > AMBANG_ARAH:
        return TARGET_MENGHADAP_KANAN
    if arah < -AMBANG_ARAH:
        return TARGET_MENGHADAP_KIRI
    return TARGET_TENGAH


def target_tegak() -> float:
    """Posisi tegak yang dituju untuk wajah, mengikuti kaidah ruang kepala."""
    return TARGET_TINGGI
