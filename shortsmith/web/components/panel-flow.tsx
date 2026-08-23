"use client";

import { useState } from "react";

import { uploadFile } from "@/lib/upload";
import { galatDari } from "@/lib/galat";

/**
 * Panel Google Flow di bawah form: Claude menulis prompt, kamu membuat klipnya,
 * Claude memeriksanya.
 *
 * ## Kenapa jumlah kartunya tidak tetap
 *
 * Lima adalah batas, bukan target. Berapa klip yang benar-benar kurang
 * tergantung berapa bahan yang sudah dipilih dan seberapa panjang videonya —
 * kadang satu sudah cukup. Memaksa lima kartu selalu terisi berarti menyuruh
 * pengguna membuat klip yang tidak ia butuhkan, dan tiap klip itu memakan kuota
 * langganan Gemini-nya.
 *
 * ## Kenapa hasil review menempel di kartunya, bukan jadi daftar terpisah
 *
 * Pesan "video 2 kurang sesuai" memaksa pengguna menghitung kartu untuk tahu
 * yang mana. Menempelkan alasannya langsung di kartu tempat klip itu diunggah
 * menghapus perhitungan itu — dan prompt penggantinya muncul persis di tempat
 * prompt lama berdiri, jadi jelas apa yang harus dipakai ulang.
 *
 * ## Kenapa menunggunya lama, dan kenapa itu ditampilkan
 *
 * Yang menjawab adalah Claude di PC pengguna lewat `claude -p` — ikut langganan
 * Claude yang sudah dibayar, jadi nol biaya tambahan. Ongkosnya kecepatan:
 * daemon menyahut tiap 10 detik dan Claude sendiri makan puluhan detik.
 * Panel ini menyebut angkanya di depan supaya menunggu 40 detik terbaca sebagai
 * hal yang normal, bukan sebagai halaman yang menggantung.
 */

export type JenisVideo = "short" | "cinematic" | "podcast";

type Penilaian = {
  nama: string;
  cocok: boolean;
  alasan: string;
  alasanUkur: string;
  alasanIsi: string;
  promptBaru: string;
  terang: number;
};

type HasilReview = {
  terangBahan: number;
  semuaCocok: boolean;
  penilaian: Penilaian[];
};

type Kartu = {
  prompt: string;
  berkas: File | null;
  key: string;
  /** Penilaian terakhir untuk klip di kartu ini. Null = belum diperiksa. */
  nilai: Penilaian | null;
};

/**
 * Jenis video yang panel ini berlaku untuknya.
 *
 * Sengaja sebuah DAFTAR, bukan perbandingan `jenis === "podcast"` yang
 * ditanam di kondisi render: melebarkannya nanti cukup menambah satu kata di
 * sini, dan tidak ada tempat kedua yang harus ikut diingat.
 *
 * Dibatasi ke podcast dulu atas permintaan. Yang lain belum dinilai apakah
 * klip hasil generate memang menolong di sana — untuk short, yang dijual
 * adalah orang yang bicara; untuk cinematic, gayanya justru yang paling sulit
 * ditiru model video.
 */
const JENIS_DIDUKUNG: JenisVideo[] = ["podcast"];

const MAKS = 5;
const JEDA_POLL = 2500;
/** Sekitar tiga menit. Lebih lama dari itu berarti daemonnya memang mati. */
const MAKS_POLL = 72;

async function tungguTugas(id: string): Promise<Record<string, unknown>> {
  for (let i = 0; i < MAKS_POLL; i++) {
    await new Promise((r) => setTimeout(r, JEDA_POLL));
    const res = await fetch(`/api/tugas/${id}`, { cache: "no-store" });
    if (!res.ok) throw new Error(await galatDari(res, "Gagal membaca status tugas"));
    const d = await res.json();
    if (d.status === "done") return (d.hasil ?? {}) as Record<string, unknown>;
    if (d.status === "failed") throw new Error(d.error || "Agent gagal mengerjakan tugas");
  }
  throw new Error(
    "Agent tidak menjawab. Pastikan daemon di PC-mu sedang jalan " +
      "(shortsmith daemon), lalu coba lagi.",
  );
}

export function PanelFlow({
  jenis,
  tema,
  bahan,
  aktif,
}: {
  jenis: JenisVideo;
  tema: string;
  /**
   * Bahan yang sudah dipilih pengguna.
   *
   * `key` hanya terisi kalau berkasnya sudah ada di storage; di form ini
   * biasanya belum, karena unggahan baru terjadi saat tombol Mulai ditekan.
   * `folder` mengisi kekosongan itu untuk mode lokal — agent menemukan
   * berkasnya di disk lewat folder plus nama.
   */
  bahan: { nama: string; key: string; folder: string }[];
  /** Panel disembunyikan sampai ada bahan — tidak ada yang bisa dibandingkan. */
  aktif: boolean;
}) {
  // Bawaannya 0, bukan 3.
  //
  // Langkah ini opsional. Angka bawaan selain nol adalah saran diam-diam bahwa
  // pengguna SEHARUSNYA membuat klip tambahan — dan tiap klip itu memakan kuota
  // langganan Gemini-nya. Kalau ia memang butuh, ia akan memilih sendiri.
  const [jumlah, setJumlah] = useState(0);
  const [kartu, setKartu] = useState<Kartu[]>([]);
  const [sibuk, setSibuk] = useState("");
  const [error, setError] = useState("");
  const [terangBahan, setTerangBahan] = useState(0);

  if (!aktif || !JENIS_DIDUKUNG.includes(jenis)) return null;

  async function mintaPrompt() {
    setError("");
    setSibuk("Claude sedang menulis prompt");
    try {
      const res = await fetch("/api/tugas", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          tipe: "prompt",
          jenis,
          tema,
          jumlah,
          sudahAda: bahan.map((b) => b.nama).slice(0, 40),
        }),
      });
      if (!res.ok) throw new Error(await galatDari(res, "Gagal meminta prompt"));
      const { id } = await res.json();
      const hasil = await tungguTugas(id);
      const prompts = (hasil.prompts ?? []) as string[];
      if (!prompts.length) throw new Error("Claude tidak mengembalikan prompt");
      setKartu(prompts.map((p) => ({ prompt: p, berkas: null, key: "", nilai: null })));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSibuk("");
    }
  }

  async function periksa() {
    const isi = kartu.filter((k) => k.berkas);
    if (!isi.length) {
      setError("Belum ada klip yang diunggah.");
      return;
    }
    setError("");
    try {
      // Diunggah lebih dulu supaya agent bisa mengunduhnya. Klip yang sudah
      // punya key dari pemeriksaan sebelumnya TIDAK diunggah ulang — pengguna
      // yang mengganti satu klip lalu memeriksa lagi tidak boleh membayar
      // ongkos unggah untuk empat klip yang tidak ia sentuh.
      const siap: Kartu[] = [...kartu];
      for (let i = 0; i < siap.length; i++) {
        const k = siap[i];
        if (!k.berkas || k.key) continue;
        setSibuk(`Mengunggah klip ${i + 1}`);
        siap[i] = { ...k, key: (await uploadFile(k.berkas, "raw")).key };
      }
      setKartu(siap);

      setSibuk("Claude sedang memeriksa klip");
      const res = await fetch("/api/tugas", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          tipe: "review",
          jenis,
          klip: siap
            .filter((k) => k.key && k.berkas)
            .map((k) => ({ key: k.key, nama: k.berkas!.name, prompt: k.prompt })),
          bahan: bahan
            .slice(0, 10)
            .map((b) => ({ key: b.key, nama: b.nama, folder: b.folder })),
        }),
      });
      if (!res.ok) throw new Error(await galatDari(res, "Gagal meminta review"));
      const { id } = await res.json();
      const hasil = (await tungguTugas(id)) as unknown as HasilReview;

      setTerangBahan(hasil.terangBahan ?? 0);
      setKartu((lama) =>
        lama.map((k) => {
          if (!k.berkas) return k;
          const n = hasil.penilaian?.find((x) => x.nama === k.berkas!.name) ?? null;
          // Prompt diganti HANYA kalau klipnya ditolak dan ada penggantinya.
          // Menimpa prompt yang klipnya sudah lolos akan membuang teks yang
          // terbukti bekerja.
          const prompt = n && !n.cocok && n.promptBaru ? n.promptBaru : k.prompt;
          return { ...k, nilai: n, prompt };
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSibuk("");
    }
  }

  // Bahan hanya bisa dibandingkan eksposurnya kalau agent bisa membuka
  // berkasnya. Di mode unggah, berkasnya masih di browser dan belum ada di mana
  // pun yang bisa dijangkau agent — jadi yang tersisa penilaian isi saja.
  // Dikatakan di depan, bukan dibiarkan pengguna menyimpulkan sendiri dari
  // hasil review yang terasa lebih dangkal.
  const bisaBanding = bahan.some((b) => b.folder || b.key);
  const ditolak = kartu.filter((k) => k.nilai && !k.nilai.cocok);
  const sudahDinilai = kartu.some((k) => k.nilai);

  return (
    <section className="flowp" aria-label="Klip tambahan lewat Google Flow">
      <div className="flowp-kepala">
        <h2 className="flowp-judul">
          Klip tambahan lewat Google Flow <span className="flowp-opsional">opsional</span>
        </h2>
        <p className="flowp-ket">
          Claude menulis promptnya, kamu membuat klipnya di Flow dengan langganan
          Gemini-mu, lalu Claude memeriksa apakah hasilnya menyatu dengan bahanmu.
          Tiap permintaan dikerjakan Claude di PC-mu, jadi tunggu sekitar 40 detik.
        </p>
        {!bisaBanding ? (
          <p className="flowp-catatan">
            Bahanmu diunggah dari browser, jadi Claude belum bisa membukanya
            untuk membandingkan kecerahan. Yang diperiksa hanya isi gambarnya.
            Pilih bahan lewat <strong>folder PC</strong> kalau kamu ingin
            perbandingan eksposurnya ikut jalan.
          </p>
        ) : null}
      </div>

      {kartu.length === 0 ? (
        <div className="flowp-mulai">
          <label className="flowp-jumlah">
            Berapa klip yang kamu butuhkan?
            <div className="flowp-angka" role="group">
              {Array.from({ length: MAKS + 1 }, (_, i) => i).map((n) => (
                <button
                  key={n}
                  type="button"
                  className={`flowp-pilih ${jumlah === n ? "aktif" : ""}`}
                  aria-pressed={jumlah === n}
                  onClick={() => setJumlah(n)}
                >
                  {n}
                </button>
              ))}
            </div>
          </label>
          <button
            type="button"
            className="btn"
            onClick={mintaPrompt}
            disabled={Boolean(sibuk) || jumlah === 0}
          >
            {sibuk || "Minta prompt dari Claude"}
          </button>

          {/* Nol dijelaskan, bukan cuma dibuat tombolnya mati. Tombol mati
              tanpa keterangan terbaca sebagai kerusakan, bukan sebagai pilihan
              yang memang sedang diambil pengguna. */}
          {jumlah === 0 ? (
            <p className="flowp-nol">
              Langkah ini dilewati. Videomu tetap dibuat dari bahan yang sudah
              kamu pilih.
            </p>
          ) : null}
        </div>
      ) : (
        <>
          <ol className="flowp-daftar">
            {kartu.map((k, i) => (
              <li
                key={i}
                className={`flowp-kartu ${
                  k.nilai ? (k.nilai.cocok ? "lolos" : "tolak") : ""
                }`}
              >
                <div className="flowp-nomor">Klip {i + 1}</div>

                <p className="flowp-prompt">{k.prompt}</p>
                <button
                  type="button"
                  className="btn ghost flowp-salin"
                  onClick={() => navigator.clipboard?.writeText(k.prompt)}
                >
                  Salin prompt
                </button>

                <label className="flowp-unggah">
                  <span>Hasil dari Flow</span>
                  <input
                    type="file"
                    accept="video/*"
                    onChange={(e) => {
                      const f = e.target.files?.[0] ?? null;
                      setKartu((lama) =>
                        lama.map((x, j) =>
                          // Key dan penilaian lama dibuang bersama berkasnya.
                          // Menyisakan key lama berarti review berikutnya
                          // memeriksa klip yang sudah diganti.
                          j === i ? { ...x, berkas: f, key: "", nilai: null } : x,
                        ),
                      );
                    }}
                  />
                  {k.berkas ? (
                    <span className="flowp-nama">{k.berkas.name}</span>
                  ) : null}
                </label>

                {k.nilai ? (
                  k.nilai.cocok ? (
                    <p className="flowp-vonis ok">Cocok dengan bahanmu.</p>
                  ) : (
                    <div className="flowp-vonis buruk">
                      <strong>Klip {i + 1} kurang sesuai.</strong>
                      <p>{k.nilai.alasan}</p>
                      {k.nilai.promptBaru ? (
                        <p className="flowp-ganti">
                          Prompt di atas sudah diganti Claude dengan versi
                          perbaikannya. Buat ulang klip ini di Flow, lalu unggah
                          yang baru.
                        </p>
                      ) : null}
                    </div>
                  )
                ) : null}
              </li>
            ))}
          </ol>

          <div className="flowp-aksi">
            <button
              type="button"
              className="btn"
              onClick={periksa}
              disabled={Boolean(sibuk)}
            >
              {sibuk || "Periksa klip dengan Claude"}
            </button>
            <button
              type="button"
              className="btn ghost"
              onClick={() => {
                setKartu([]);
                setError("");
              }}
              disabled={Boolean(sibuk)}
            >
              Mulai ulang
            </button>
          </div>

          {sudahDinilai ? (
            <p className={`notice ${ditolak.length ? "warn" : "ok"}`} role="status">
              {ditolak.length
                ? `${ditolak.length} dari ${
                    kartu.filter((k) => k.berkas).length
                  } klip kurang sesuai — lihat keterangan di kartunya.`
                : "Semua klip cocok dengan bahanmu."}
              {terangBahan
                ? ` Kecerahan bahanmu ${Math.round(terangBahan)} dari 255.`
                : ""}
            </p>
          ) : null}
        </>
      )}

      {error ? (
        <p className="notice err" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
