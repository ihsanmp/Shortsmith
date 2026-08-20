"use client";

import dynamic from "next/dynamic";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import type { SequenceItem } from "@/components/ui/magic-dust-shader";
import { BIRU } from "@/components/ui/shiny-text";
import { FormLogin } from "./form-login";

/**
 * Three.js + react-three-fiber sekitar 600 KB. Dimuat dinamis dan tanpa SSR
 * supaya halaman login tetap tampil seketika; partikelnya menyusul belakangan.
 * Kalau bundle-nya gagal dimuat sekalipun, form login tetap berfungsi penuh.
 */
const MagicDust = dynamic(
  () => import("@/components/ui/magic-dust-shader").then((m) => m.MagicDust),
  { ssr: false },
);

const URUTAN: SequenceItem[] = [
  { type: "text", text: "SHORTSMITH" },
  { type: "shape", shape: "torus" },
  { type: "text", text: "CUT" },
  { type: "shape", shape: "sphere" },
  { type: "text", text: "CAPTION" },
  { type: "shape", shape: "box" },
  { type: "text", text: "RENDER" },
];

function useHematGerak() {
  const [hemat, setHemat] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setHemat(mq.matches);
    const ubah = (e: MediaQueryListEvent) => setHemat(e.matches);
    mq.addEventListener("change", ubah);
    return () => mq.removeEventListener("change", ubah);
  }, []);
  return hemat;
}

/**
 * `?mulai=1` membuka form seketika, melewati layar sambutan.
 *
 * Dipakai tombol "Get Started" di navbar. Orang yang menekan tombol bernama
 * "Get Started" sudah menyatakan niatnya; menyodorkan satu tombol lagi bernama
 * "Start Editing" hanya menambah satu klik untuk keputusan yang sudah diambil.
 *
 * Ini query param, bukan rute terpisah, supaya keduanya tetap satu halaman
 * dengan satu form — dan supaya menekan Kembali mengembalikan layar sambutannya
 * tanpa berpindah halaman.
 */
function IsiLogin() {
  const params = useSearchParams();
  const [buka, setBuka] = useState(params.get("mulai") === "1");
  const hematGerak = useHematGerak();

  return (
    <div className="masuk">
      {/* Partikel dimatikan sepenuhnya kalau sistem meminta hemat gerak —
          bukan dipercepat, karena animasinya sendiri yang jadi masalah. */}
      {!hematGerak && (
        <div className="masuk-kanvas" aria-hidden="true">
          <MagicDust
            sequence={URUTAN}
            particleCount={6000}
            /* Sewarna dengan latar dashboard: biru yang sama dipakai judul
               berkilau di sana. Kuning yang sebelumnya dipakai membuat halaman
               pertama dan halaman kedua terasa milik dua produk berbeda. */
            particleColor={BIRU}
            particleSize={0.018}
            fontFamily="Inter, sans-serif"
            holdDuration={2.6}
            scatterRadius={11}
          />
        </div>
      )}

      <div className="masuk-tirai" aria-hidden="true" />

      <div className="masuk-isi">
        <div className="badge">Shortsmith</div>
        <h1 className="masuk-judul">
          Dari rekaman panjang
          <br />
          <span className="masuk-judul-grad">jadi short.</span>
        </h1>

        {!buka ? (
          <>
            <p className="masuk-sub">
              Unggah rekaman, pilih konsep, dan agent di PC-mu yang mengerjakan sisanya.
            </p>
            <button className="btn masuk-mulai" type="button" onClick={() => setBuka(true)}>
              Start Editing
            </button>
          </>
        ) : (
          <FormLogin onBatal={() => setBuka(false)} />
        )}
      </div>
    </div>
  );
}

/**
 * Batas Suspense berada di LUAR isinya.
 *
 * `useSearchParams` menuntutnya, dan kalau batasnya dipasang di dalam — seperti
 * sebelumnya, hanya membungkus form — Next.js akan menganggap SELURUH halaman
 * perlu dirender di klien. Di halaman yang paling dulu dilihat orang, itu
 * ongkos yang salah tempat.
 */
export default function LoginPage() {
  return (
    <Suspense fallback={<div className="masuk" />}>
      <IsiLogin />
    </Suspense>
  );
}
