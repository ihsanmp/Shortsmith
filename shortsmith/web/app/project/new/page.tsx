"use client";

import { useEffect, useState } from "react";

import { uploadFile } from "@/lib/upload";
import { ProgressBar } from "@/components/ui/progress-bar";
import { Memuat } from "@/components/ui/memuat";
import { TombolKembali } from "@/components/ui/tombol-kembali";
import { Dropdown } from "@/components/ui/dropdown";

type Concept = { id: string; nama: string; siap: boolean; isDefault: boolean };
type Sumber = "pustaka" | "unggah";
type AsalBahan = "unggah" | "lokal";
type BerkasBahan = { nama: string; ukuranBytes: number };
/** Berkas beserta folder asalnya — dipilih sebagai satu kesatuan. */
type PilihanBahan = BerkasBahan & { folder: string };
type FolderBahan = {
  root: string | null;
  folders: { path: string; jumlahVideo: number; berkas: BerkasBahan[] }[];
  updatedAt: string | null;
};

/** Harus sama dengan RASIO di agent/shortsmith/models.py */
const RASIO = [
  { v: "auto", t: "Ikuti video contoh (disarankan)" },
  { v: "9:16", t: "9:16 — TikTok, Reels, Shorts (1080×1920)" },
  { v: "4:5", t: "4:5 — feed Instagram potret (1080×1350)" },
  { v: "3:4", t: "3:4 — potret lebar (1080×1440)" },
  { v: "1:1", t: "1:1 — persegi (1080×1080)" },
  { v: "16:9", t: "16:9 — lanskap (1920×1080)" },
];

const MAKS_CONTOH = 4;
const MAKS_MENTAH = 10;

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

export default function NewProjectPage() {
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [sumber, setSumber] = useState<Sumber>("pustaka");
  const [conceptId, setConceptId] = useState("");
  const [namaKonsep, setNamaKonsep] = useState("");
  const [brief, setBrief] = useState("");
  const [contoh, setContoh] = useState<File[]>([]);
  const [rasio, setRasio] = useState("auto");


  // Sengaja DUA kolom terpisah, bukan satu kolom multi-file. Browser
  // mengembalikan file sesuai urutan sistem berkas, bukan urutan pengguna
  // memilihnya — jadi satu kolom membuat "file pertama" tak bisa dikendalikan,
  // padahal justru file itulah satu-satunya sumber suara. Memisahkannya membuat
  // urutan yang salah tidak mungkin terjadi.
  const [suara, setSuara] = useState<File | null>(null);
  const [klip, setKlip] = useState<File[]>([]);

  // Bahan mentah bisa datang dari dua tempat. Di mode lokal, file picker
  // tetap dipakai — browser memberi nama dan ukuran, dan itu sudah cukup;
  // path absolutnya memang tidak boleh dibaca halaman web.
  const [asal, setAsal] = useState<AsalBahan>("unggah");
  const [folderInfo, setFolderInfo] = useState<FolderBahan | null>(null);
  // Dua folder terpisah: rekaman suara dan klip B-roll punya peran berbeda,
  // jadi wajar disimpan di tempat berbeda. Satu pilihan untuk keduanya memaksa
  // pengguna menumpuk semuanya di satu folder.

  // Di mode lokal, berkas dipilih dari daftar yang DILAPORKAN agent — bukan
  // dari file picker browser. Picker itu tidak mengunggah apa pun, jadi
  // tombol "Choose File" hanya menyesatkan; dan ia membuka peluang memilih
  // berkas dari folder lain yang namanya kebetulan sama.
  const [pilihSuara, setPilihSuara] = useState<PilihanBahan | null>(null);
  const [pilihKlip, setPilihKlip] = useState<PilihanBahan[]>([]);

  const [progress, setProgress] = useState(0);
  const [tahap, setTahap] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [konsepDimuat, setKonsepDimuat] = useState(false);
  const [konsepGagal, setKonsepGagal] = useState("");

  // Daftar folder datang dari agent, bukan dari browser — halaman web tidak
  // bisa melihat disk. Kalau agent belum pernah melapor, dropdown-nya kosong
  // dan formnya mengatakan kenapa.
  function muatFolder() {
    return fetch("/api/folders")
      .then((r) => (r.ok ? r.json() : null))
      .then(setFolderInfo)
      .catch(() => setFolderInfo(null));
  }

  useEffect(() => {
    // Tiga keadaan yang WAJIB dibedakan: masih dimuat, gagal dimuat, dan
    // benar-benar kosong.
    //
    // Versi sebelumnya menyamakan ketiganya jadi satu tampilan "belum ada
    // konsep tersimpan". Akibatnya, saat pemuatan gagal, pengguna yang sudah
    // punya konsep diberi tahu bahwa konsepnya tidak ada dan diarahkan membuat
    // duplikat — pesan yang bukan cuma tidak membantu, tapi menyesatkan ke
    // tindakan yang salah.
    fetch("/api/concepts")
      .then(async (r) => {
        if (!r.ok) {
          // Status HTTP tidak pernah diperiksa sebelumnya, jadi respons 401
          // atau 500 tetap diurai sebagai JSON sukses dan berakhir sebagai
          // daftar kosong.
          const pesan =
            r.status === 401
              ? "Sesi kamu berakhir. Muat ulang halaman untuk masuk lagi."
              : `Gagal memuat konsep (HTTP ${r.status}).`;
          throw new Error(pesan);
        }
        return r.json() as Promise<{ concepts: Concept[] }>;
      })
      .then((d) => {
        const siap = (d.concepts ?? []).filter((c) => c.siap);
        setConcepts(siap);
        setConceptId(siap.find((c) => c.isDefault)?.id ?? siap[0]?.id ?? "");
        if (siap.length === 0) setSumber("unggah");
      })
      .catch((err: Error) => setKonsepGagal(err.message || "Gagal memuat daftar konsep."))
      .finally(() => setKonsepDimuat(true));

    muatFolder();

    // Daftar folder disegarkan lagi saat tab ini kembali dilihat.
    //
    // Alurnya memang begitu: pengguna menaruh berkas di folder lewat File
    // Explorer, lalu kembali ke tab ini. Tanpa ini, halaman yang sudah terbuka
    // menampilkan daftar dari saat ia dimuat SELAMANYA — berkas yang baru
    // ditaruh terlihat seperti hilang, padahal sudah ada di disk.
    const kembali = () => {
      if (document.visibilityState === "visible") muatFolder();
    };
    document.addEventListener("visibilitychange", kembali);
    window.addEventListener("focus", kembali);
    return () => {
      document.removeEventListener("visibilitychange", kembali);
      window.removeEventListener("focus", kembali);
    };
  }, []);

  // Urutan di sini ADALAH kontraknya: agent memperlakukan indeks 0 sebagai
  // sumber suara dan sisanya sebagai pustaka klip. Lihat pipeline.py.
  // Folder tidak lagi dipilih terpisah. Dulu ada dua tingkat — pilih folder,
  // lalu pilih berkas — dan itu dua langkah untuk satu keputusan. Sekarang
  // berkasnya didaftar langsung, dikelompokkan menurut folder asalnya.
  const kelompok = (folderInfo?.folders ?? []).filter((f) => f.berkas.length > 0);
  const kunci = (b: PilihanBahan) => `${b.folder}/${b.nama}`;

  // Dua mode memberi bentuk data yang berbeda, tapi sisa form hanya perlu tahu
  // nama dan ukuran — jadi keduanya disatukan ke bentuk yang sama di sini.
  const daftarBahan: { nama: string; ukuran: number; folder: string }[] =
    asal === "lokal"
      ? [
          ...(pilihSuara
            ? [{ nama: pilihSuara.nama, ukuran: pilihSuara.ukuranBytes, folder: pilihSuara.folder }]
            : []),
          ...pilihKlip.map((b) => ({
            nama: b.nama,
            ukuran: b.ukuranBytes,
            folder: b.folder,
          })),
        ]
      : (suara ? [suara, ...klip] : []).map((f) => ({
          nama: f.name,
          ukuran: f.size,
          folder: "",
        }));

  /** Hanya dipakai jalur unggah. Mode lokal memakai `daftarBahan`. */
  const mentah = suara ? [suara, ...klip] : [];

  const mentahValid =
    daftarBahan.length >= 1 && daftarBahan.length <= MAKS_MENTAH;
  const totalMB = daftarBahan.reduce((a, f) => a + f.ukuran, 0) / 1e6;
  const adaTerlaluBesar = daftarBahan.some((f) => f.ukuran > 5e9);

  const konsepValid =
    sumber === "pustaka"
      ? Boolean(conceptId)
      : contoh.length >= 1 && contoh.length <= MAKS_CONTOH && namaKonsep.trim().length > 0;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!mentahValid || !konsepValid) return;

    setBusy(true);
    setError("");
    try {
      // Video contoh diunggah lebih dulu supaya kalau gagal, tidak ada
      // project setengah jadi yang tertinggal.
      const sampleKeys: string[] = [];
      if (sumber === "unggah") {
        for (const [i, f] of contoh.entries()) {
          setTahap(`Mengunggah video contoh ${i + 1} dari ${contoh.length}`);
          setProgress(0);
          sampleKeys.push((await uploadFile(f, "sample", setProgress)).key);
        }
      }

      // Diunggah berurutan dan didaftarkan berurutan: rawKeys[0] harus tetap
      // sumber suara sesampainya di agent.
      const rawKeys: {
        key: string;
        namaFile: string;
        ukuranBytes: number;
        lokal: boolean;
        bahanFolder: string;
      }[] = [];

      if (asal === "lokal") {
        // Tidak ada yang diunggah. Nama dan ukuran saja yang dikirim; agent
        // mencari berkasnya di folder bahan miliknya dan memakainya di tempat.
        setTahap("Mendaftarkan bahan lokal");
        // Foldernya sudah melekat di tiap entri, jadi tidak perlu ditebak
        // dari posisinya.
        for (const b of daftarBahan) {
          rawKeys.push({
            key: "",
            namaFile: b.nama,
            ukuranBytes: b.ukuran,
            lokal: true,
            bahanFolder: b.folder,
          });
        }
      } else {
        for (const [i, f] of mentah.entries()) {
          setTahap(
            i === 0
              ? "Mengunggah rekaman suara"
              : `Mengunggah klip ${i} dari ${mentah.length - 1}`,
          );
          setProgress(0);
          const a = await uploadFile(f, "raw", setProgress);
          rawKeys.push({
            key: a.key,
            namaFile: a.namaFile,
            ukuranBytes: a.ukuranBytes,
            lokal: false,
            bahanFolder: "",
          });
        }
      }

      setTahap("Mendaftarkan job");
      const res = await fetch("/api/projects", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          // Judul diambil dari nama file mentah pertama. Dipotong 200 karakter
          // karena itu batas yang divalidasi API — dan sekarang tidak ada lagi
          // kolom judul yang bisa dipakai pengguna untuk memperbaikinya sendiri.
          judul: daftarBahan[0].nama.slice(0, 200),
          brief,
          rawKeys,
          ...(sumber === "pustaka"
            ? { conceptId }
            : { konsepBaru: { nama: namaKonsep.trim(), sampleKeys, aspectRatio: rasio } }),
        }),
      });

      if (!res.ok) throw new Error(pesanError(await res.json(), "Gagal membuat project"));
      const { project } = await res.json();
      window.location.href = `/project/${project.id}`;
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
      setTahap("");
    }
  }

  return (
    <>
      <div className="badge">Project baru</div>
      <h1 className="title">Unggah rekaman</h1>
      <p className="subtitle">Tentukan gayanya, sisanya otomatis.</p>

      <form onSubmit={submit} className="panel stack">
        <div>
          <label>Asal bahan mentah</label>
          <div className="pilihan-grup">
<label className="pilihan pilihan-radio">
              <input
                type="radio"
                name="asal"
                checked={asal === "lokal"}
                disabled={busy}
                onChange={() => setAsal("lokal")}
              />
              <span className="pilihan-tanda" aria-hidden>
                <span className="pilihan-cincin" />
                <span className="pilihan-titik" />
              </span>
              <span className="pilihan-teks">
                <span className="pilihan-judul">Ambil dari folder PC</span>
              </span>
            </label>
<label className="pilihan pilihan-radio">
              <input
                type="radio"
                name="asal"
                checked={asal === "unggah"}
                disabled={busy}
                onChange={() => setAsal("unggah")}
              />
              <span className="pilihan-tanda" aria-hidden>
                <span className="pilihan-cincin" />
                <span className="pilihan-titik" />
              </span>
              <span className="pilihan-teks">
                <span className="pilihan-judul">Unggah ke storage</span>
              </span>
            </label>
          </div>

          {asal === "lokal" ? (
            folderInfo?.root ? (
              <>
                <div
                  className="row"
                  style={{ justifyContent: "space-between", marginBottom: 14, gap: 12 }}
                >
                  <p className="hint mono" style={{ margin: 0 }}>
                    {folderInfo.root}
                  </p>
                  {/* Daftar ini datang dari agent, jadi ia bisa tertinggal dari
                      isi disk yang sebenarnya. Waktunya ditampilkan supaya
                      "berkas belum muncul" bisa dibedakan dari "daftarnya basi",
                      dan tombolnya memberi jalan keluar tanpa memuat ulang. */}
                  <span className="row" style={{ gap: 8, flexShrink: 0 }}>
                    {folderInfo.updatedAt && (
                      <span className="hint">
                        diperbarui{" "}
                        {new Date(folderInfo.updatedAt).toLocaleTimeString("id-ID", {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </span>
                    )}
                    <button
                      type="button"
                      className="btn ghost"
                      disabled={busy}
                      onClick={() => muatFolder()}
                    >
                      Segarkan
                    </button>
                  </span>
                </div>

                <label htmlFor="pilih-suara">Rekaman suara (satu file)</label>
                <Dropdown
                  id="pilih-suara"
                  nilai={pilihSuara ? kunci(pilihSuara) : ""}
                  placeholder="— pilih berkas —"
                  disabled={busy || kelompok.length === 0}
                  opsi={kelompok.flatMap((g) =>
                    g.berkas.map((b) => ({
                      nilai: `${g.path}/${b.nama}`,
                      judul: b.nama,
                      // Ukuran naik ke baris kedua, bukan diselipkan dalam
                      // kurung di judulnya. Di daftar berkas, ukuran adalah
                      // yang dibandingkan antar baris — ia perlu berdiri di
                      // kolomnya sendiri supaya bisa dipindai menurun.
                      ket: `${(b.ukuranBytes / 1e6).toFixed(0)} MB`,
                      grup: g.path || "(folder utama)",
                    })),
                  )}
                  onPilih={(v) => {
                    const semua = kelompok.flatMap((g) =>
                      g.berkas.map((b) => ({ ...b, folder: g.path })),
                    );
                    setPilihSuara(semua.find((b) => kunci(b) === v) ?? null);
                  }}
                />
                <p className="hint" style={{ marginTop: 6 }}>
                  Seluruh audio video hasil diambil dari file ini saja, dan agent memilih
                  satu topik utuh dari dalamnya. Hanya file ini yang ditranskrip.
                </p>

                <label style={{ marginTop: 20 }}>Klip B-roll (boleh banyak, opsional)</label>
                {kelompok.length === 0 ? (
                  <p className="hint">Tidak ada video di folder bahan agent.</p>
                ) : (
                  kelompok.map((g) => (
                    <div key={g.path} style={{ marginBottom: 12 }}>
                      <p className="hint mono" style={{ marginBottom: 4 }}>
                        {g.path || "(folder utama)"}
                      </p>
                      <div className="pilihan-daftar">
                        {g.berkas.map((b) => {
                          const item = { ...b, folder: g.path };
                          const dipilih = pilihKlip.some((x) => kunci(x) === kunci(item));
                          return (
                            <label key={b.nama} className="pilihan">
                              <input
                                type="checkbox"
                                checked={dipilih}
                                disabled={busy}
                                onChange={() =>
                                  setPilihKlip((p) =>
                                    dipilih
                                      ? p.filter((x) => kunci(x) !== kunci(item))
                                      : [...p, item],
                                  )
                                }
                              />
                              {/* Kotak dan centang adalah DUA elemen, bukan satu yang
                                  berubah isi. Saat terpilih, kotaknya benar-benar
                                  hilang dan yang tersisa hanya centangnya — itulah
                                  perbedaan pokok dari checkbox biasa, dan menumpuk
                                  keduanya di satu elemen membuat sisa bingkai masih
                                  terlihat di balik centang. */}
                              <span className="pilihan-tanda" aria-hidden>
                                <span className="pilihan-kotak" />
                                <svg
                                  className="pilihan-centang"
                                  viewBox="0 0 24 24"
                                  fill="none"
                                  stroke="currentColor"
                                  strokeWidth="2.6"
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                >
                                  <path d="M4.5 12.5 9.5 17.5 19.5 6.5" />
                                </svg>
                              </span>
                              <span className="pilihan-teks">
                                <span className="pilihan-judul">{b.nama}</span>
                                <span className="pilihan-ket">
                                  {(b.ukuranBytes / 1e6).toFixed(0)} MB
                                </span>
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  ))
                )}
                <p className="hint" style={{ marginTop: 6 }}>
                  Hanya gambarnya yang dipakai &mdash; suara klip diabaikan, dan klip tidak
                  perlu bersuara sama sekali.
                </p>
              </>
            ) : (
              <div className="notice warn">
                Agent belum melaporkan isi folder bahannya. Pastikan agent sedang
                berjalan, lalu muat ulang halaman ini.
              </div>
            )
          ) : (
            <>
              <label htmlFor="suara">Rekaman suara (satu file)</label>
              <input
                id="suara"
                type="file"
                accept="video/*,audio/*"
                required
                disabled={busy}
                onChange={(e) => setSuara(e.target.files?.[0] ?? null)}
              />
              <p className="hint" style={{ marginTop: 6 }}>
                Seluruh audio video hasil diambil dari file ini saja, dan agent memilih
                satu topik utuh dari dalamnya. Hanya file ini yang ditranskrip.
              </p>
              {suara && (
                <div className="hint" style={{ marginTop: 8 }}>
                  <strong>{suara.name}</strong> &middot; {(suara.size / 1e6).toFixed(0)} MB
                </div>
              )}

              <label htmlFor="klip" style={{ marginTop: 20 }}>
                Klip B-roll (boleh banyak, opsional)
              </label>
              <input
                id="klip"
                type="file"
                accept="video/*"
                multiple
                disabled={busy}
                onChange={(e) => setKlip(Array.from(e.target.files ?? []))}
              />
              <p className="hint" style={{ marginTop: 6 }}>
                Hanya gambarnya yang dipakai — suara klip diabaikan, dan klip tidak
                perlu bersuara sama sekali.
              </p>
            </>
          )}

          {daftarBahan.length > MAKS_MENTAH && (
            <div className="notice err" style={{ marginTop: 10 }}>
              Maksimal {MAKS_MENTAH} file per project (1 rekaman suara +{" "}
              {MAKS_MENTAH - 1} klip). Sekarang {daftarBahan.length}.
            </div>
          )}
          {adaTerlaluBesar && (
            <div className="notice err" style={{ marginTop: 10 }}>
              Ada file di atas 5 GB.
            </div>
          )}
        </div>

        {/* ---------- Konsep ---------- */}
        <div>
          <label>Konsep</label>

          <div className="pilihan-grup">
<label className="pilihan pilihan-radio">
              <input
                type="radio"
                name="sumber"
                checked={sumber === "pustaka"}
                disabled={busy || (konsepDimuat && !konsepGagal && concepts.length === 0)}
                onChange={() => setSumber("pustaka")}
              />
              <span className="pilihan-tanda" aria-hidden>
                <span className="pilihan-cincin" />
                <span className="pilihan-titik" />
              </span>
              <span className="pilihan-teks">
                <span className="pilihan-judul">Pilih dari pustaka</span>
              </span>
            </label>
            <label className="pilihan pilihan-radio">
              <input
                type="radio"
                name="sumber"
                checked={sumber === "unggah"}
                disabled={busy}
                onChange={() => setSumber("unggah")}
              />
              <span className="pilihan-tanda" aria-hidden>
                <span className="pilihan-cincin" />
                <span className="pilihan-titik" />
              </span>
              <span className="pilihan-teks">
                <span className="pilihan-judul">Kirim video contoh</span>
              </span>
            </label>
          </div>

          {sumber === "pustaka" ? (
            !konsepDimuat ? (
              <div className="notice info">Memuat konsep&hellip;</div>
            ) : konsepGagal ? (
              // Kegagalan disebut apa adanya, lengkap dengan cara memulihkan.
              // Menyamarkannya jadi "belum ada konsep" akan membuat pengguna
              // membuat ulang konsep yang sebenarnya masih tersimpan.
              <div className="notice warn">
                {konsepGagal}{" "}
                <button
                  type="button"
                  className="btn ghost"
                  style={{ marginLeft: 8 }}
                  onClick={() => window.location.reload()}
                >
                  Coba lagi
                </button>
              </div>
            ) : concepts.length === 0 ? (
              <div className="notice info">
                Belum ada konsep tersimpan. Pilih <strong>Kirim video contoh</strong> untuk
                membuat yang pertama.
              </div>
            ) : (
              <Dropdown
                nilai={conceptId}
                disabled={busy}
                placeholder="— pilih konsep —"
                opsi={concepts.map((c) => ({ nilai: c.id, judul: c.nama }))}
                onPilih={setConceptId}
              />
            )
          ) : (
            <div className="stack" style={{ gap: 12 }}>
              <div>
                <label htmlFor="namaKonsep">Nama konsep</label>
                <input
                  id="namaKonsep"
                  type="text"
                  value={namaKonsep}
                  disabled={busy}
                  placeholder="mis. clipper-motivasi"
                  onChange={(e) => setNamaKonsep(e.target.value)}
                />
              </div>

              <div>
                <label htmlFor="contoh">Video contoh yang sudah jadi (1&ndash;4)</label>
                <input
                  id="contoh"
                  type="file"
                  accept="video/*"
                  multiple
                  disabled={busy}
                  onChange={(e) => setContoh(Array.from(e.target.files ?? []))}
                />
                {contoh.length > MAKS_CONTOH && (
                  <p className="hint" style={{ color: "#991b1b", marginTop: 6 }}>
                    Maksimal {MAKS_CONTOH} video.
                  </p>
                )}
                {contoh.length === 1 && (
                  <p className="hint" style={{ marginTop: 6 }}>
                    Satu video adalah sampel n=1. Kalau ritmenya kebetulan tidak mewakili
                    gayamu, konsepnya jadi miring. Dua video atau lebih membuat deviasinya
                    ikut terukur, dan deviasi itu sendiri jadi informasi.
                  </p>
                )}
              </div>

              <div>
                <label htmlFor="rasio">Rasio video hasil</label>
                <Dropdown
                  id="rasio"
                  nilai={rasio}
                  disabled={busy}
                  opsi={RASIO.map((r) => ({ nilai: r.v, judul: r.t }))}
                  onPilih={setRasio}
                />
                <p className="hint" style={{ marginTop: 6 }}>
                  Gambar sumber dipotong dari tengah agar pas. Bisa diubah kapan saja
                  lewat halaman Konsep.
                </p>
              </div>

              <div className="notice info">
                Konsep baru dibuat dari video ini dan <strong>tidak akan berubah lagi</strong>.
                Konsep lama tetap utuh. Untuk mengganti gaya, kirim video contoh baru.
              </div>
            </div>
          )}
        </div>

        <div>
          <label htmlFor="brief">Fokus pembahasan (opsional)</label>
          <textarea
            id="brief"
            value={brief}
            disabled={busy}
            placeholder="mis. cara mulai investasi dari nol"
            onChange={(e) => setBrief(e.target.value)}
          />
          <p className="hint" style={{ marginTop: 6 }}>
            Diisi &mdash; hanya bagian rekaman yang membahas topik ini yang dipakai.
            Dikosongkan &mdash; bebas, editor memilih topik terkuat yang ada di video.
          </p>
        </div>

        {daftarBahan.length > 0 && (
          /* Bedanya kedua mode hanya terjadi SETELAH tombol ditekan, dan tanpa
             baris ini pengguna tidak punya cara melihatnya sebelum terlambat. */
          <div className={asal === "lokal" ? "notice ok" : "notice warn"}>
            {asal === "lokal" ? (
              <>
                <strong>Tidak ada yang diunggah.</strong> {totalMB.toFixed(0)} MB dibaca
                langsung dari disk, jadi job langsung berjalan tanpa menunggu.
              </>
            ) : (
              <>
                <strong>{totalMB.toFixed(0)} MB akan diunggah</strong> ke storage sebelum
                job dimulai, lalu diunduh lagi oleh agent. Kalau agent berjalan di PC yang
                sama dengan browser ini, pilih <em>Ambil dari folder PC</em> — hasilnya
                sama tapi tanpa unggahan.
              </>
            )}
          </div>
        )}

        {busy && asal === "unggah" && (
          <div className="proses">
            <Memuat label="" size={46} />
            {/* `progress` 0 berarti unggahan belum melaporkan apa pun, bukan
                benar-benar nol persen. Dikirim sebagai null supaya bilahnya
                menampilkan gerak "sedang bekerja" — angka 0 yang diam terlihat
                seperti macet di awal, dan itu justru saat pengguna paling cemas. */}
            <ProgressBar
              value={progress > 0 ? progress : null}
              label={tahap || "Mengunggah"}
              pendingLabel="Menyiapkan"
              completeLabel="Unggahan selesai"
            />
          </div>
        )}

        {/* Mode lokal tidak mengunggah apa pun, jadi tidak ada persentase yang
            bisa ditampilkan — tapi pembuatan project tetap memakan waktu, dan
            tanpa penanda apa pun tombol yang mati terlihat seperti klik yang
            tidak tersampaikan. */}
        {busy && asal === "lokal" && (
          <div className="proses">
            <Memuat label="" size={46} />
            <span className="hint">{tahap || "Menyiapkan project"}</span>
          </div>
        )}

        {error && <div className="notice err">{error}</div>}

        {/* Tujuannya `/projects`, bukan `/` — daftar project sudah pindah ke
            halaman sendiri, dan tautan lama ini mendarat di dashboard. */}
        <div className="row" style={{ justifyContent: "space-between" }}>
          <TombolKembali href="/projects" label="Kembali ke project" />
          <button className="pill pill-aksi" type="submit" disabled={busy || !mentahValid || adaTerlaluBesar || !konsepValid}>
            {busy ? "Memproses..." : asal === "lokal" ? "Mulai" : "Unggah & mulai"}
          </button>
        </div>
      </form>
    </>
  );
}
