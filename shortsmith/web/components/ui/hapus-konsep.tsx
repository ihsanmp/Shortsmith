"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Konfirmasi } from "@/components/ui/konfirmasi";

/**
 * Tombol hapus untuk satu konsep.
 *
 * Komponen client tersendiri karena halaman pustaka konsep dirender di server.
 * Yang perlu interaktif hanya tombol ini, jadi hanya bagian ini yang dikirim
 * sebagai JavaScript — halaman selebihnya tetap statis.
 *
 * Konsep yang masih dipakai project ditolak server dengan 409, dan alasannya
 * ditampilkan apa adanya. Itu bukan kegagalan yang perlu disembunyikan:
 * pengguna berhak tahu bahwa konsepnya masih dipakai, dan berapa banyak.
 */
export function HapusKonsep({
  id,
  nama,
  className = "btn ghost",
}: {
  id: string;
  nama: string;
  /** Kelas tombolnya, supaya pemanggil bisa menyesuaikan bentuk tanpa menyalin
      seluruh logika konfirmasi dan penanganan 409 di bawah ini. */
  className?: string;
}) {
  const router = useRouter();
  const [tanya, setTanya] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function hapus() {
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`/api/concepts/${id}`, { method: "DELETE" });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(d.detail ? `${d.error} ${d.detail}` : (d.error ?? "Gagal menghapus konsep."));
        setTanya(false);
        return;
      }
      // Halaman ini server component, jadi daftarnya hanya berubah setelah
      // server merendernya ulang.
      router.refresh();
    } catch {
      setError("Gagal menghubungi server.");
      setTanya(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        className={className}
        disabled={busy}
        onClick={() => setTanya(true)}
      >
        Hapus
      </button>

      {error && (
        <div className="notice warn" style={{ marginTop: 10, flexBasis: "100%" }}>
          {error}
        </div>
      )}

      <Konfirmasi
        terbuka={tanya}
        judul={`Hapus konsep "${nama}"?`}
        pesan={
          "Video contohnya ikut dihapus dari storage berikut seluruh versinya. " +
          "Video hasil yang sudah jadi TIDAK ikut terhapus. Tindakan ini tidak bisa dibatalkan."
        }
        labelYa="Hapus"
        busy={busy}
        onYa={hapus}
        onBatal={() => setTanya(false)}
      />
    </>
  );
}
