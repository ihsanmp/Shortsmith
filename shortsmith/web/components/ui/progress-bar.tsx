"use client";

import type { AriaAttributes } from "react";
import { useId } from "react";
import { motion, useReducedMotion } from "motion/react";

/**
 * Bilah progres dengan gerak pegas, plus keadaan "belum terukur".
 *
 * ## Kenapa tidak memakai kelas Tailwind seperti aslinya
 *
 * Project ini tidak memakai Tailwind — stylingnya token CSS di globals.css.
 * Menyalin kelas Tailwind mentah-mentah akan menghasilkan komponen tanpa gaya
 * sama sekali, dan varian `dark:` di dalamnya justru membuat light mode rusak
 * karena Tailwind-lah yang seharusnya menentukan kapan varian itu aktif.
 *
 * Yang dipertahankan dari komponen aslinya adalah yang membuatnya bagus:
 * transisi pegas, crossfade label, keadaan indeterminate, dan pengumuman
 * aria-live. Warnanya mengikuti token, jadi ia otomatis benar di kedua tema.
 *
 * ## Kenapa `value` boleh null
 *
 * Ada saat sistem bekerja tapi belum tahu sejauh mana: mengukur berkas,
 * menunggu agent menjawab. Memaksa angka 0 di situ berbohong — ia terlihat
 * seperti macet di awal. `null` menyatakan "berjalan, belum terukur", dan
 * bilahnya menampilkan gerak berulang alih-alih angka palsu.
 */

const ISI = { type: "spring", stiffness: 210, damping: 34, mass: 0.9 } as const;
const SILANG = { type: "spring", stiffness: 260, damping: 34, mass: 0.8 } as const;
const SEKETIKA = { duration: 0 } as const;

export type ProgressBarProps = {
  value: number | null;
  max?: number;
  label?: string;
  pendingLabel?: string;
  completeLabel?: string;
  className?: string;
};

export function ProgressBar({
  value,
  max = 100,
  label = "Progres",
  pendingLabel = "Menyiapkan",
  completeLabel = "Selesai",
  className = "",
}: ProgressBarProps) {
  const kurangiGerak = useReducedMotion();
  const labelId = useId();

  const takTerukur = value === null;
  const pecahan =
    value === null || max <= 0 ? 0 : Math.min(1, Math.max(0, value / max));
  const persen = Math.round(pecahan * 100);
  const selesai = !takTerukur && pecahan >= 1;

  // Nilai aria hanya diisi kalau memang terukur. Mengisi aria-valuenow dengan 0
  // saat nilainya belum diketahui akan diumumkan pembaca layar sebagai "0
  // persen" — pernyataan yang salah, bukan sekadar kurang informatif.
  const terukur: AriaAttributes = takTerukur
    ? {}
    : {
        "aria-valuenow": Math.round(pecahan * max * 100) / 100,
        "aria-valuetext": `${persen}%`,
      };

  return (
    <div className={`pb ${className}`}>
      <div className="pb-atas">
        <span id={labelId} className="pb-label">
          {label}
        </span>

        {/* Kedua teks ditumpuk di sel grid yang sama supaya pergantiannya
            crossfade di tempat — kalau diganti biasa, lebarnya melompat dan
            label di kiri ikut bergeser. */}
        <span aria-hidden className="pb-kanan">
          <motion.span
            className="pb-pending"
            initial={false}
            animate={{ opacity: takTerukur ? 1 : 0 }}
            transition={kurangiGerak ? SEKETIKA : SILANG}
          >
            {pendingLabel}
          </motion.span>
          <motion.span
            className="pb-persen"
            initial={false}
            animate={{ opacity: takTerukur ? 0 : 1 }}
            transition={kurangiGerak ? SEKETIKA : SILANG}
          >
            {persen}%
          </motion.span>
        </span>
      </div>

      <div
        role="progressbar"
        aria-labelledby={labelId}
        aria-valuemin={0}
        aria-valuemax={max}
        {...terukur}
        className="pb-rangka"
      >
        <div className="pb-jalur">
          <motion.span
            aria-hidden
            className="pb-isi"
            initial={false}
            animate={{ scaleX: takTerukur ? 0 : pecahan }}
            transition={kurangiGerak ? SEKETIKA : ISI}
          />

          {takTerukur && !kurangiGerak ? (
            <motion.span
              aria-hidden
              className="pb-kilat"
              initial={{ x: "-100%", opacity: 0 }}
              animate={{ x: "250%", opacity: 1 }}
              transition={{
                x: { duration: 1.25, ease: "easeInOut", repeat: Infinity },
                opacity: { duration: 0.18 },
              }}
            />
          ) : null}
        </div>
      </div>

      {/* Hanya perubahan penting yang diumumkan. Mengumumkan tiap persen akan
          membuat pembaca layar bicara tanpa henti selama proses berjalan. */}
      <span aria-live="polite" className="sr-only">
        {selesai ? completeLabel : takTerukur ? pendingLabel : ""}
      </span>
    </div>
  );
}

export default ProgressBar;
