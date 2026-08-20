"use client";
import { TombolKembali } from "@/components/ui/tombol-kembali";

import { use, useEffect, useState } from "react";

/**
 * Editor profil sebagai form biasa.
 *
 * Di titik inilah janji "ganti konsep tanpa program ulang" benar-benar terpenuhi:
 * permintaan seperti "sama seperti Vlog cepat tapi 30 detik" diselesaikan dengan
 * duplikat konsep dan ubah satu angka — bukan dengan menyentuh kode.
 */

/** Harus sama persis dengan RASIO di agent/shortsmith/models.py */
const RASIO: { nilai: string; label: string; ukuran: string }[] = [
  { nilai: "9:16", label: "9:16 — TikTok, Reels, Shorts", ukuran: "1080×1920" },
  { nilai: "4:5", label: "4:5 — feed Instagram potret", ukuran: "1080×1350" },
  { nilai: "3:4", label: "3:4 — potret lebar", ukuran: "1080×1440" },
  { nilai: "1:1", label: "1:1 — persegi", ukuran: "1080×1080" },
  { nilai: "16:9", label: "16:9 — lanskap", ukuran: "1920×1080" },
];

type Stat = { mean: number; std?: number };
/**
 * Berapa bagian timeline yang menampilkan rekaman suaranya sendiri, sisanya
 * B-roll. Nilainya diukur otomatis dari video contoh saat konsep dibuat, tapi
 * bisa ditimpa di sini — "beberapa klip" adalah penilaian selera, bukan angka
 * yang punya jawaban benar.
 */
const PORSI = [
  { nilai: 0, label: "Tidak pernah — hanya B-roll" },
  { nilai: 0.2, label: "Sesekali (20%)" },
  { nilai: 0.35, label: "Seimbang (35%)" },
  { nilai: 0.5, label: "Sering (50%)" },
  { nilai: 0.6, label: "Dominan (60%)" },
];

type Profile = {
  nama?: string;
  aspect_ratio?: string;
  porsi_pembicara?: number;
  metrik?: Record<string, Stat>;
  caption?: {
    ada?: boolean;
    posisi?: string;
    gaya?: string;
    max_kata?: number;
    ukuran?: number;
  };
  manual?: {
    fokus?: string;
  };
};

type Concept = {
  id: string;
  nama: string;
  siap: boolean;
  isDefault: boolean;
  profileJson: Profile;
};

/**
 * Gabungkan `error` dengan `detail` dari API.
 *
 * Tanpa ini, kegagalan validasi hanya muncul sebagai "Body tidak valid" —
 * benar, tapi tidak bisa ditindaklanjuti. Detail dari Zod menyebut field mana
 * yang ditolak dan kenapa, dan itulah satu-satunya bagian yang berguna saat
 * sesuatu tiba-tiba berhenti bekerja.
 */
function pesanError(d: { error?: string; detail?: string }, bawaan: string): string {
  const utama = d?.error ?? bawaan;
  return d?.detail ? `${utama} — ${d.detail}` : utama;
}

export default function EditConceptPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [concept, setConcept] = useState<Concept | null>(null);
  const [profile, setProfile] = useState<Profile>({});
  const [nama, setNama] = useState("");
  const [isDefault, setIsDefault] = useState(false);
  const [pesan, setPesan] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch(`/api/concepts/${id}`)
      .then((r) => r.json())
      .then((d: { concept: Concept; error?: string }) => {
        if (d.error) throw new Error(d.error);
        setConcept(d.concept);
        setProfile(d.concept.profileJson ?? {});
        setNama(d.concept.nama);
        setIsDefault(d.concept.isDefault);
      })
      .catch((e) => setError((e as Error).message));
  }, [id]);

  function setMetrik(kunci: string, mean: number) {
    setProfile((p) => ({
      ...p,
      metrik: { ...p.metrik, [kunci]: { ...(p.metrik?.[kunci] ?? {}), mean } },
    }));
  }

  function setCaption(patch: Partial<NonNullable<Profile["caption"]>>) {
    setProfile((p) => ({ ...p, caption: { ...p.caption, ...patch } }));
  }

  function setManual(patch: Partial<NonNullable<Profile["manual"]>>) {
    setProfile((p) => ({ ...p, manual: { ...p.manual, ...patch } }));
  }

  async function simpan(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setPesan("");
    setError("");
    try {
      const res = await fetch(`/api/concepts/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ nama, isDefault, profileJson: { ...profile, nama } }),
      });
      if (!res.ok) throw new Error(pesanError(await res.json(), "Gagal menyimpan"));
      setPesan("Tersimpan.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function duplikat() {
    setBusy(true);
    try {
      const res = await fetch(`/api/concepts/${id}`, { method: "POST" });
      const d = await res.json();
      if (!res.ok) throw new Error(pesanError(d, "Gagal menduplikat"));
      window.location.href = `/concepts/${d.concept.id}/edit`;
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  if (error && !concept) return <div className="notice err">{error}</div>;
  if (!concept) return <div className="empty">Memuat...</div>;

  const durasi = profile.metrik?.durasi_total?.mean ?? 45;
  const cut = profile.metrik?.jumlah_cut?.mean ?? 20;
  const shot = profile.metrik?.avg_shot_length;

  return (
    <>
      <div className="badge">Edit konsep</div>
      <h1 className="title" style={{ fontSize: "2rem" }}>
        {concept.nama}
      </h1>
      <p className="subtitle">
        {concept.siap
          ? "Ubah angkanya langsung — tidak perlu video contoh baru."
          : "Konsep ini masih menunggu analisis agent."}
      </p>

      <form onSubmit={simpan} className="panel stack">
        <div>
          <label htmlFor="nama">Nama</label>
          <input
            id="nama"
            type="text"
            value={nama}
            required
            onChange={(e) => setNama(e.target.value)}
          />
        </div>

        <div>
          <label htmlFor="durasi">
            Panjang khas video contoh: {durasi.toFixed(0)} detik
          </label>
          <input
            id="durasi"
            type="range"
            min={10}
            max={300}
            step={5}
            value={durasi}
            style={{ width: "100%" }}
            onChange={(e) => setMetrik("durasi_total", Number(e.target.value))}
          />
          <p className="hint" style={{ marginTop: 6 }}>
            Gambaran gaya, bukan target yang dikejar. Hasil boleh lebih panjang atau
            lebih pendek — yang menentukan adalah materi rekamannya.
          </p>
        </div>

        <div>
          <label htmlFor="rasio">Rasio video hasil</label>
          <select
            id="rasio"
            value={profile.aspect_ratio ?? "9:16"}
            onChange={(e) => setProfile((p) => ({ ...p, aspect_ratio: e.target.value }))}
          >
            {RASIO.map((r) => (
              <option key={r.nilai} value={r.nilai}>
                {r.label} ({r.ukuran})
              </option>
            ))}
          </select>
          <p className="hint" style={{ marginTop: 6 }}>
            Terisi otomatis dari rasio video contoh saat konsep dibuat. Ubah di sini kalau
            ingin hasilnya berbeda dari contohnya. Gambar sumber dipotong dari tengah.
          </p>
        </div>

        <div>
          <label htmlFor="porsi">Wajah pembicara diselipkan</label>
          <select
            id="porsi"
            value={String(profile.porsi_pembicara ?? 0)}
            onChange={(e) =>
              setProfile((p) => ({ ...p, porsi_pembicara: Number(e.target.value) }))
            }
          >
            {PORSI.map((r) => (
              <option key={r.nilai} value={String(r.nilai)}>
                {r.label}
              </option>
            ))}
          </select>
          <p className="hint" style={{ marginTop: 6 }}>
            Diambil dari rekaman suara, pada detik yang sama dengan suara yang sedang
            terdengar — jadi gerak bibirnya cocok. Hanya berlaku untuk konsep berformat
            overlay. Terukur otomatis dari video contoh saat konsep dibuat.
          </p>
        </div>

        <div>
          <label htmlFor="cut">Perkiraan jumlah potongan</label>
          <input
            id="cut"
            type="number"
            min={1}
            max={200}
            value={cut}
            onChange={(e) => setMetrik("jumlah_cut", Number(e.target.value))}
          />
        </div>

        {shot && (
          <div className="notice info">
            Panjang shot rata-rata <strong>{shot.mean.toFixed(2)}s</strong>, deviasi{" "}
            <strong>{(shot.std ?? 0).toFixed(2)}</strong>. Deviasi rendah berarti ritme
            metronomik, deviasi tinggi berarti ritme dinamis — nilai ini dikirim ke
            model sebagai sinyal ritme. Diukur dari video contoh, jadi tidak diedit
            manual di sini.
          </div>
        )}

        <div>
          <label>
            <input
              type="checkbox"
              checked={profile.caption?.ada ?? true}
              style={{ width: "auto", marginRight: 8 }}
              onChange={(e) => setCaption({ ada: e.target.checked })}
            />
            Pakai caption
          </label>
        </div>

        {(profile.caption?.ada ?? true) && (
          <div className="row" style={{ gap: 16 }}>
            <div style={{ flex: 1, minWidth: 160 }}>
              <label htmlFor="posisi">Posisi</label>
              <select
                id="posisi"
                value={profile.caption?.posisi ?? "tengah"}
                onChange={(e) => setCaption({ posisi: e.target.value })}
              >
                <option value="tengah-bawah">Tengah bawah</option>
                <option value="tengah">Tengah (seperti video contoh)</option>
                <option value="atas">Atas</option>
              </select>
            </div>
            <div style={{ flex: 1, minWidth: 160 }}>
              <label htmlFor="gaya">Gaya</label>
              <select
                id="gaya"
                value={profile.caption?.gaya ?? "kata-per-kata"}
                onChange={(e) => setCaption({ gaya: e.target.value })}
              >
                <option value="frasa">Per frasa</option>
                <option value="kata-per-kata">Kata per kata (seperti video contoh)</option>
              </select>
            </div>
            <div style={{ flex: 1, minWidth: 120 }}>
              <label htmlFor="maxkata">Kata per baris</label>
              <input
                id="maxkata"
                type="number"
                min={1}
                max={10}
                value={profile.caption?.max_kata ?? 4}
                onChange={(e) => setCaption({ max_kata: Number(e.target.value) })}
              />
            </div>
          </div>
        )}

        <div>
          <label>
            <input
              type="checkbox"
              checked={isDefault}
              style={{ width: "auto", marginRight: 8 }}
              onChange={(e) => setIsDefault(e.target.checked)}
            />
            Jadikan konsep default
          </label>
        </div>

        {pesan && <div className="notice info">{pesan}</div>}
        {error && <div className="notice err">{error}</div>}

        {/* Tombol kembali di KIRI, dipisahkan dari kelompok tindakan di kanan.
            Ia jalan keluar, bukan salah satu pilihan yang setara dengan Simpan —
            menempelkannya di deret yang sama membuatnya mudah tertekan saat
            tangan meleset satu tombol. */}
        <div className="row" style={{ justifyContent: "space-between" }}>
          <TombolKembali href="/concepts" label="Kembali ke konsep" />
          <span className="row">
            <button className="pill pill-aksi" type="submit" disabled={busy}>
              {busy ? "Menyimpan..." : "Simpan"}
            </button>
            <button className="btn ghost" type="button" disabled={busy} onClick={duplikat}>
              Duplikat konsep
            </button>
          </span>
        </div>
      </form>
    </>
  );
}
