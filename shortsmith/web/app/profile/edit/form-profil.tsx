"use client";

import { useRef, useState } from "react";

/**
 * Form edit profil: foto, username, email, dan password.
 *
 * ## Kenapa dipecah jadi tiga bagian dengan tombol simpan masing-masing
 *
 * Satu tombol simpan untuk semuanya memaksa pengguna mengisi password lama
 * hanya karena ingin mengganti username. Tiga bagian berarti tiap perubahan
 * membawa syaratnya sendiri: nama dan foto bebas, email dan password menuntut
 * bukti kepemilikan.
 *
 * ## Kenapa foto diunggah langsung ke storage
 *
 * Pola yang sudah dipakai seluruh aplikasi ini: server hanya menandatangani
 * URL, byte-nya mengalir langsung dari browser ke bucket. Batas body serverless
 * Vercel sekitar 4.5 MB — foto dari kamera ponsel rutin melewatinya.
 */

const MAKS_FOTO = 5 * 1024 * 1024;
const TIPE_FOTO = ["image/jpeg", "image/png", "image/webp"];

type Kabar = { jenis: "ok" | "err"; teks: string } | null;

function Pesan({ kabar }: { kabar: Kabar }) {
  if (!kabar) return null;
  return (
    <div className={`notice ${kabar.jenis === "ok" ? "info" : "err"}`} role="alert">
      {kabar.teks}
    </div>
  );
}

export function FormProfil({
  username: usernameAwal,
  email: emailAwal,
  avatarUrl,
}: {
  username: string;
  email: string;
  avatarUrl: string | null;
}) {
  const [username, setUsername] = useState(usernameAwal);
  const [email, setEmail] = useState(emailAwal);
  const [passwordLama, setPasswordLama] = useState("");
  const [passwordBaru, setPasswordBaru] = useState("");
  const [emailSandi, setEmailSandi] = useState("");

  // Pratinjau lokal supaya foto terlihat seketika setelah dipilih, tanpa
  // menunggu unggahan selesai. URL-nya dibuang saat komponen hilang — object
  // URL yang tidak dilepas menahan berkasnya di memori.
  const [pratinjau, setPratinjau] = useState<string | null>(null);
  const [sibuk, setSibuk] = useState<"foto" | "nama" | "email" | "sandi" | null>(null);
  const [kabar, setKabar] = useState<Kabar>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  async function kirim(
    bagian: "foto" | "nama" | "email" | "sandi",
    isi: Record<string, unknown>,
    sukses: string,
  ) {
    setSibuk(bagian);
    setKabar(null);
    try {
      const res = await fetch("/api/profil", {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(isi),
      });
      const jawab = await res.json();
      if (!res.ok) throw new Error(jawab.error ?? "Gagal menyimpan");
      setKabar({ jenis: "ok", teks: sukses });
      return true;
    } catch (err) {
      setKabar({ jenis: "err", teks: (err as Error).message });
      return false;
    } finally {
      setSibuk(null);
    }
  }

  async function pilihFoto(berkas: File) {
    if (!TIPE_FOTO.includes(berkas.type)) {
      setKabar({ jenis: "err", teks: "Foto harus JPEG, PNG, atau WebP." });
      return;
    }
    if (berkas.size > MAKS_FOTO) {
      setKabar({ jenis: "err", teks: "Foto maksimal 5 MB." });
      return;
    }

    setSibuk("foto");
    setKabar(null);
    setPratinjau(URL.createObjectURL(berkas));

    try {
      const tokenRes = await fetch("/api/upload-token", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          filename: berkas.name,
          contentType: berkas.type,
          prefix: "avatar",
          ukuranBytes: berkas.size,
        }),
      });
      const token = await tokenRes.json();
      if (!tokenRes.ok) throw new Error(token.error ?? "Gagal menyiapkan unggahan");

      const naik = await fetch(token.uploadUrl, {
        method: "PUT",
        headers: { "content-type": berkas.type },
        body: berkas,
      });
      if (!naik.ok) throw new Error(`Unggahan ditolak storage (${naik.status})`);

      // Baris akun baru ditunjuk ke foto ini SETELAH byte-nya benar-benar
      // sampai. Menyimpan key lebih dulu akan menghasilkan profil yang menunjuk
      // ke berkas yang tidak pernah ada kalau unggahannya putus di tengah.
      await kirim("foto", { avatarKey: token.key }, "Foto profil diperbarui.");
    } catch (err) {
      setKabar({ jenis: "err", teks: (err as Error).message });
      setPratinjau(null);
      setSibuk(null);
    }
  }

  const foto = pratinjau ?? avatarUrl;

  return (
    <div className="profil-edit">
      <Pesan kabar={kabar} />

      <section className="profil-edit-blok">
        <h2 className="profil-edit-judul">Foto profil</h2>
        <div className="profil-edit-foto-baris">
          <button
            type="button"
            className="profil-edit-foto"
            onClick={() => fileRef.current?.click()}
            disabled={sibuk !== null}
            aria-label="Pilih foto profil"
          >
            {foto ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={foto} alt="" />
            ) : (
              <svg viewBox="0 0 128 128" width="100%" height="100%" aria-hidden>
                <rect width="128" height="128" fill="#cbd5e1" />
                <circle cx="64" cy="48" r="24" fill="#f8fafc" />
                <path d="M18 126c4-28 24-46 46-46s42 18 46 46" fill="#f8fafc" />
              </svg>
            )}
            <span className="profil-edit-foto-tirai">
              {sibuk === "foto" ? "Mengunggah…" : "Ganti"}
            </span>
          </button>

          <div>
            <p className="hint">JPEG, PNG, atau WebP. Maksimal 5 MB.</p>
            {avatarUrl && (
              <button
                type="button"
                className="masuk-kembali"
                disabled={sibuk !== null}
                onClick={async () => {
                  if (await kirim("foto", { avatarKey: null }, "Foto profil dihapus.")) {
                    setPratinjau(null);
                  }
                }}
              >
                Hapus foto
              </button>
            )}
          </div>
        </div>

        <input
          ref={fileRef}
          type="file"
          accept={TIPE_FOTO.join(",")}
          className="sr-only"
          onChange={(e) => {
            const f = e.target.files?.[0];
            // Nilainya dikosongkan supaya memilih berkas yang SAMA dua kali
            // tetap memicu change — kalau tidak, percobaan ulang setelah gagal
            // terlihat seperti tombol yang mati.
            e.target.value = "";
            if (f) void pilihFoto(f);
          }}
        />
      </section>

      <section className="profil-edit-blok">
        <h2 className="profil-edit-judul">Username</h2>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            await kirim("nama", { username: username.trim() }, "Username diperbarui.");
          }}
        >
          <div className="masuk-kolom">
            <input
              value={username}
              maxLength={40}
              required
              disabled={sibuk !== null}
              placeholder="user"
              onChange={(e) => setUsername(e.target.value)}
              aria-label="Username"
            />
          </div>
          <button
            className="profil-halaman-tombol profil-edit-simpan"
            type="submit"
            disabled={sibuk !== null || !username.trim() || username.trim() === usernameAwal}
          >
            {sibuk === "nama" ? "Menyimpan…" : "Simpan username"}
          </button>
        </form>
      </section>

      <section className="profil-edit-blok">
        <h2 className="profil-edit-judul">Email</h2>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (await kirim("email", { email: email.trim(), passwordLama: emailSandi }, "Email diperbarui.")) {
              setEmailSandi("");
            }
          }}
        >
          <div className="masuk-kolom">
            <input
              type="email"
              value={email}
              required
              disabled={sibuk !== null}
              onChange={(e) => setEmail(e.target.value)}
              aria-label="Email"
            />
          </div>
          <div className="masuk-kolom">
            <input
              type="password"
              value={emailSandi}
              required
              disabled={sibuk !== null}
              placeholder="Password sekarang"
              autoComplete="current-password"
              onChange={(e) => setEmailSandi(e.target.value)}
              aria-label="Password sekarang"
            />
          </div>
          <p className="hint">
            Email dipakai untuk masuk, jadi menggantinya perlu password sekarang.
          </p>
          <button
            className="profil-halaman-tombol profil-edit-simpan"
            type="submit"
            disabled={sibuk !== null || !emailSandi || email.trim() === emailAwal}
          >
            {sibuk === "email" ? "Menyimpan…" : "Simpan email"}
          </button>
        </form>
      </section>

      <section className="profil-edit-blok">
        <h2 className="profil-edit-judul">Password</h2>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (await kirim("sandi", { passwordLama, passwordBaru }, "Password diperbarui.")) {
              setPasswordLama("");
              setPasswordBaru("");
            }
          }}
        >
          <div className="masuk-kolom">
            <input
              type="password"
              value={passwordLama}
              required
              disabled={sibuk !== null}
              placeholder="Password sekarang"
              autoComplete="current-password"
              onChange={(e) => setPasswordLama(e.target.value)}
              aria-label="Password sekarang"
            />
          </div>
          <div className="masuk-kolom">
            <input
              type="password"
              value={passwordBaru}
              required
              minLength={10}
              disabled={sibuk !== null}
              placeholder="Password baru (min. 10 karakter)"
              autoComplete="new-password"
              onChange={(e) => setPasswordBaru(e.target.value)}
              aria-label="Password baru"
            />
          </div>
          <button
            className="profil-halaman-tombol profil-edit-simpan"
            type="submit"
            disabled={sibuk !== null || !passwordLama || passwordBaru.length < 10}
          >
            {sibuk === "sandi" ? "Menyimpan…" : "Simpan password"}
          </button>
        </form>
      </section>
    </div>
  );
}
