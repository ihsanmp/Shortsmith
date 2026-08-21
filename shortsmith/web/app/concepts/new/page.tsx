"use client";
import { TombolKembali } from "@/components/ui/tombol-kembali";

import { useState } from "react";

import { uploadFile } from "@/lib/upload";
import { galatDari } from "@/lib/galat";

const MIN_SAMPEL = 2;
const MAX_SAMPEL = 4;


export default function NewConceptPage() {
  const [nama, setNama] = useState("");
  const [files, setFiles] = useState<File[]>([]);

  const [progress, setProgress] = useState(0);
  const [tahap, setTahap] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const cukup = files.length >= MIN_SAMPEL && files.length <= MAX_SAMPEL;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!cukup) return;

    setBusy(true);
    setError("");
    try {
      const keys: string[] = [];
      for (const [i, f] of files.entries()) {
        setTahap(`Mengunggah contoh ${i + 1} dari ${files.length}`);
        setProgress(0);
        const asset = await uploadFile(f, "sample", setProgress);
        keys.push(asset.key);
      }

      setTahap("Mendaftarkan job analisis");
      const res = await fetch("/api/concepts", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          nama: nama.trim(),
          sampleKeys: keys,
        }),
      });

      if (!res.ok) throw new Error(await galatDari(res, "Gagal membuat konsep"));
      window.location.href = "/concepts";
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
      setTahap("");
    }
  }

  return (
    <>
      <div className="badge">Konsep baru</div>
      <h1 className="title">Ajari gayanya</h1>
      <p className="subtitle">Sekali di awal, dipakai berulang.</p>

      <form onSubmit={submit} className="panel stack">
        <div>
          <label htmlFor="nama">Nama konsep</label>
          <input
            id="nama"
            type="text"
            required
            value={nama}
            disabled={busy}
            placeholder="mis. vlog-cepat"
            onChange={(e) => setNama(e.target.value)}
          />
        </div>

        <div>
          <label htmlFor="samples">Video contoh (2&ndash;4, yang sudah jadi)</label>
          <input
            id="samples"
            type="file"
            accept="video/*"
            multiple
            required
            disabled={busy}
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
          />
          <p className="hint" style={{ marginTop: 6 }}>
            Minimal dua. Satu video adalah sampel n=1 — kalau ritmenya kebetulan tidak
            mewakili gaya aslimu, seluruh konsep jadi miring dan sulit dilacak
            penyebabnya. Dengan beberapa video, deviasinya sendiri jadi informasi.
          </p>
          {files.length > 0 && (
            <p className="hint" style={{ marginTop: 6 }}>
              {files.length} file dipilih
              {!cukup && (
                <strong style={{ color: "#991b1b" }}> &mdash; harus 2 sampai 4</strong>
              )}
            </p>
          )}
        </div>

        {busy && (
          <div>
            <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
              <span className="hint">{tahap}</span>
              <span className="hint">{progress}%</span>
            </div>
            <div className="bar">
              <div style={{ width: `${progress}%` }} />
            </div>
          </div>
        )}

        {error && <div className="notice err">{error}</div>}

        <div className="row" style={{ justifyContent: "space-between" }}>
          <TombolKembali href="/concepts" label="Kembali ke konsep" />
          <button className="pill pill-aksi" type="submit" disabled={busy || !cukup || !nama.trim()}>
            {busy ? "Memproses..." : "Buat konsep"}
          </button>
        </div>
      </form>
    </>
  );
}
