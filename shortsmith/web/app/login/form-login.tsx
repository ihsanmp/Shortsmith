"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { galatDari } from "@/lib/galat";

/**
 * Form masuk: akun email, pendaftaran, dan mode tamu.
 *
 * ## Kenapa email diingat perangkat, bukan sesi
 *
 * Yang disimpan di localStorage HANYA email — tidak pernah password. Ia ada
 * supaya perangkat yang sudah pernah dipakai cukup meminta password, sesuai
 * permintaan "satu device cukup sekali isi email". Kalau seseorang bisa membaca
 * localStorage perangkat ini, ia sudah duduk di depan komputernya; email yang
 * terbaca di situ tidak memberinya apa pun yang belum ia punya.
 *
 * ## Pendaftaran terbuka
 *
 * Tidak ada kode undangan. Siapa pun yang membuka halaman ini bisa membuat akun
 * dan langsung punya akses penuh — pilihan sadar pemiliknya, dicatat di sini
 * supaya tidak terbaca sebagai gerbang yang lupa dipasang.
 *
 * ## Kenapa mode tamu ada tombolnya sendiri, bukan pilihan di dalam form
 *
 * Tamu tidak mengisi apa-apa. Menaruhnya sebagai tab ketiga di sebelah "Masuk"
 * dan "Daftar" akan menampilkan form kosong tanpa kolom — dan tab yang isinya
 * hanya satu tombol membuat orang mengira ada yang gagal dimuat.
 */

const KUNCI_EMAIL = "shortsmith-email";

type Mode = "masuk" | "daftar";

function Panah() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="17"
      height="17"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M5 12h13M13 6l6 6-6 6" />
    </svg>
  );
}

export function FormLogin({ onBatal }: { onBatal: () => void }) {
  const params = useSearchParams();
  const [mode, setMode] = useState<Mode>("masuk");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // `null` berarti belum dibaca; string kosong berarti sudah dibaca dan memang
  // tidak ada. Membedakan keduanya mencegah form berkedip dari "isi email" ke
  // "hanya password" sepersekian detik setelah halaman tampil.
  const [emailTersimpan, setEmailTersimpan] = useState<string | null>(null);

  useEffect(() => {
    try {
      const t = localStorage.getItem(KUNCI_EMAIL) ?? "";
      setEmailTersimpan(t);
      setEmail(t);
    } catch {
      // Mode privat memblokir localStorage. Yang hilang hanya kemudahannya —
      // emailnya tinggal diketik.
      setEmailTersimpan("");
    }
  }, []);

  const ingat = mode === "masuk" && !!emailTersimpan;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");

    const emailBersih = (ingat ? emailTersimpan! : email).trim().toLowerCase();

    try {
      const res = await fetch(mode === "daftar" ? "/api/daftar" : "/api/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: emailBersih, password }),
      });
      if (!res.ok) throw new Error(await galatDari(res, "Gagal masuk"));

      try {
        localStorage.setItem(KUNCI_EMAIL, emailBersih);
      } catch {}
      window.location.href = params.get("next") || "/";
    } catch (err) {
      setError((err as Error).message);
      setPassword("");
      setBusy(false);
    }
  }

  async function masukTamu() {
    setBusy(true);
    setError("");
    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ tamu: true }),
      });
      if (!res.ok) throw new Error(await galatDari(res, "Gagal masuk"));
      window.location.href = params.get("next") || "/";
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  // Sebelum localStorage terbaca, formnya tidak dilukis. Yang dihemat bukan
  // waktu — itu satu tick — melainkan kedipan susunan yang berubah tepat saat
  // mata baru mendarat di sana.
  if (emailTersimpan === null) return <div className="hint">Memuat…</div>;

  const kirimMati = busy || !password || (!ingat && !email);

  return (
    <form onSubmit={submit} className="masuk-form">
      <div className="masuk-mode" role="tablist" aria-label="Pilih cara masuk">
        {(["masuk", "daftar"] as const).map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={mode === m}
            className={`masuk-mode-tab${mode === m ? " masuk-mode-aktif" : ""}`}
            onClick={() => {
              setMode(m);
              setError("");
            }}
          >
            {m === "masuk" ? "Masuk" : "Daftar"}
          </button>
        ))}
      </div>

      {ingat ? (
        <p className="masuk-ingat">
          <span className="masuk-ingat-email">{emailTersimpan}</span>
          <button
            type="button"
            className="masuk-ganti"
            disabled={busy}
            onClick={() => {
              try {
                localStorage.removeItem(KUNCI_EMAIL);
              } catch {}
              setEmailTersimpan("");
              setEmail("");
            }}
          >
            bukan kamu?
          </button>
        </p>
      ) : (
        <>
          {/* Label tetap ada, hanya tidak terlihat. Placeholder BUKAN pengganti
              label: ia hilang begitu diketik, dan sebagian pembaca layar tidak
              membacakannya sama sekali. */}
          <label htmlFor="email" className="sr-only">
            Email
          </label>
          <div className="masuk-kolom">
            <input
              id="email"
              type="email"
              value={email}
              required
              autoFocus
              disabled={busy}
              placeholder="email@contoh.com"
              autoComplete="email"
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
        </>
      )}

      <label htmlFor="password" className="sr-only">
        Password
      </label>
      <div className="masuk-kolom">
        <input
          id="password"
          type="password"
          value={password}
          required
          autoFocus={ingat}
          disabled={busy}
          placeholder={mode === "daftar" ? "Password baru (min. 10 karakter)" : "Password"}
          autoComplete={mode === "daftar" ? "new-password" : "current-password"}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button
          className="masuk-kirim"
          type="submit"
          disabled={kirimMati}
          aria-label={busy ? "Memproses" : mode === "daftar" ? "Daftar" : "Masuk"}
        >
          {busy ? <span className="masuk-putar" aria-hidden /> : <Panah />}
        </button>
      </div>

      {mode === "daftar" && (
        <p className="masuk-catatan">
          Password minimal 10 karakter. Ia menjaga akses ke rekaman dan ke agent
          yang berjalan di PC — pilih yang tidak dipakai di tempat lain.
        </p>
      )}

      {/* role=alert supaya pembaca layar mengumumkan kegagalan, bukan hanya
          mengandalkan warna merah yang tak terdengar. */}
      {error && (
        <div className="notice err" role="alert">
          {error}
        </div>
      )}

      <div className="masuk-pisah">
        <span>atau</span>
      </div>

      <button type="button" className="masuk-tamu" disabled={busy} onClick={masukTamu}>
        Masuk sebagai tamu
      </button>
      <p className="masuk-catatan">
        Tamu bisa melihat project dan konsep, tapi tidak bisa mengubah apa pun.
      </p>

      <button className="masuk-kembali" type="button" disabled={busy} onClick={onBatal}>
        Kembali
      </button>
    </form>
  );
}
