"use client";

import { useEffect, useRef, useCallback } from "react";

// ─── Tipe ─────────────────────────────────────────────────────────────────────

interface Point {
  x: number;
  y: number;
}

interface Ripple {
  x: number;
  y: number;
  radius: number;
  opacity: number;
  born: number;
}

// ─── Konstanta ────────────────────────────────────────────────────────────────

const CELL_SIZE = 55;
const INFLUENCE_RADIUS = 260;
const MAX_WARP = 24;
const DOT_SPACING = 28;
const LERP_SPEED = 0.08;

const LINE_BASE = { r: 255, g: 255, b: 255, a: 0.13 };
const NODE_BASE_RADIUS = 1.8;
const NODE_ACTIVE_RADIUS = 3.2;

const TAU = Math.PI * 2;

/**
 * Biru #4a9eff dari komponen aslinya diganti gradien hangat milik Shortsmith.
 * Latar disamakan dengan token --bg supaya kanvas menyatu dengan sisa aplikasi,
 * bukan jadi kotak gelap yang warnanya sedikit meleset.
 */
const TEMA = {
  default: {
    bg: "#0b0f14",
    lineActive: { r: 245, g: 195, b: 68, a: 0.9 },
    nodeActive: { r: 245, g: 195, b: 68, a: 1.0 },
    glow: "245,195,68",
    ripple: "181,103,194",
  },
  monochrome: {
    bg: "#000000",
    lineActive: { r: 255, g: 255, b: 255, a: 0.9 },
    nodeActive: { r: 255, g: 255, b: 255, a: 1.0 },
    glow: "255,255,255",
    ripple: "255,255,255",
  },
} as const;

// ─── Bantuan ──────────────────────────────────────────────────────────────────

function lerpN(a: number, b: number, t: number) {
  return a + (b - a) * t;
}

function lerpColor(
  base: { r: number; g: number; b: number; a: number },
  active: { r: number; g: number; b: number; a: number },
  t: number,
): string {
  const r = Math.round(lerpN(base.r, active.r, t));
  const g = Math.round(lerpN(base.g, active.g, t));
  const b = Math.round(lerpN(base.b, active.b, t));
  const a = lerpN(base.a, active.a, t);
  return `rgba(${r},${g},${b},${a.toFixed(3)})`;
}

// ─── Komponen ─────────────────────────────────────────────────────────────────

/**
 * Dipasang sebagai lapisan latar (`position: fixed; z-index: -1`), bukan sebagai
 * pembungkus `children` seperti versi aslinya. Alasannya: kanvas ini mengecat
 * latar solid, dan `.shell` beserta nav sudah mengatur tata letaknya sendiri —
 * membungkus konten akan menaruh nav di bawah kanvas yang tidak tembus pandang.
 */
export default function KineticGrid({
  globalColor = "default",
}: {
  globalColor?: "default" | "monochrome";
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const mouseRef = useRef<Point>({ x: -9999, y: -9999 });
  const targetMouseRef = useRef<Point>({ x: -9999, y: -9999 });
  const ripplesRef = useRef<Ripple[]>([]);
  const rafRef = useRef<number>(0);
  const sizeRef = useRef<{ w: number; h: number }>({ w: 0, h: 0 });
  const dotsRef = useRef<CanvasPattern | null>(null);
  const perluGambarRef = useRef(true);

  // ── Warp ────────────────────────────────────────────────────────────────────

  const getWarpedPoint = useCallback(
    (
      gx: number,
      gy: number,
      col: number,
      row: number,
      mouse: Point,
      ripples: Ripple[],
      cols: number,
      rows: number,
    ): { pt: Point; proximity: number } => {
      // Baris dan kolom tepi dikunci pelan-pelan supaya grid tidak terlihat
      // lepas dari bingkai layar saat kursor mendekati pinggir.
      const edgeMargin = 1.5;
      const colPin = Math.min(col / edgeMargin, (cols - 1 - col) / edgeMargin, 1);
      const rowPin = Math.min(row / edgeMargin, (rows - 1 - row) / edgeMargin, 1);
      const pinFactor = colPin * colPin * rowPin * rowPin;

      const dx = gx - mouse.x;
      const dy = gy - mouse.y;
      const dist = Math.sqrt(dx * dx + dy * dy);

      const proximity = Math.max(0, 1 - dist / INFLUENCE_RADIUS) * pinFactor;

      let rx = 0;
      let ry = 0;
      for (const r of ripples) {
        const rdx = gx - r.x;
        const rdy = gy - r.y;
        const rdist = Math.sqrt(rdx * rdx + rdy * rdy);
        const waveWidth = 55;
        const diff = rdist - r.radius;
        if (Math.abs(diff) < waveWidth) {
          const strength = (1 - Math.abs(diff) / waveWidth) * r.opacity * 18 * pinFactor;
          const angle = Math.atan2(rdy, rdx);
          const sign = diff < 0 ? -1 : 1;
          rx += Math.cos(angle) * strength * sign * -1;
          ry += Math.sin(angle) * strength * sign * -1;
        }
      }

      if (dist < INFLUENCE_RADIUS && dist > 0 && pinFactor > 0) {
        const t = dist / INFLUENCE_RADIUS;
        const eased = t < 0.01 ? 0 : (1 - t) * (1 - t) * Math.min(1, dist / 60);
        const warpAmt = eased * MAX_WARP * pinFactor;
        const angle = Math.atan2(dy, dx);
        return {
          pt: {
            x: gx - Math.cos(angle) * warpAmt + rx,
            y: gy - Math.sin(angle) * warpAmt + ry,
          },
          proximity,
        };
      }

      return { pt: { x: gx + rx, y: gy + ry }, proximity };
    },
    [],
  );

  // ── Gambar ──────────────────────────────────────────────────────────────────

  const draw = useCallback(
    (now: number) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      const { w: W, h: H } = sizeRef.current;
      const mouse = mouseRef.current;
      const ripples = ripplesRef.current;
      const theme = TEMA[globalColor] ?? TEMA.default;

      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = theme.bg;
      ctx.fillRect(0, 0, W, H);

      // Tekstur titik latar. Versi aslinya menggambar ulang tiap titik setiap
      // frame — di layar 1080p itu ribuan panggilan arc() per frame untuk
      // sesuatu yang tidak pernah berubah. Di sini dipakai pattern sekali isi.
      if (dotsRef.current) {
        ctx.fillStyle = dotsRef.current;
        ctx.fillRect(0, 0, W, H);
      }

      for (let i = ripples.length - 1; i >= 0; i--) {
        const r = ripples[i];
        const age = (now - r.born) / 1000;
        r.radius = Math.max(0, age * 400);
        r.opacity = Math.max(0, 1 - age * 1.2);
        if (r.opacity <= 0) ripples.splice(i, 1);
      }

      // ── Grid yang sudah dilengkungkan ─────────────────────────────────────
      const cols = Math.max(2, Math.ceil(W / CELL_SIZE)) + 1;
      const rows = Math.max(2, Math.ceil(H / CELL_SIZE)) + 1;
      const cellW = W / (cols - 1);
      const cellH = H / (rows - 1);

      const pts: Point[][] = [];
      const prox: number[][] = [];

      for (let row = 0; row < rows; row++) {
        pts[row] = [];
        prox[row] = [];
        for (let col = 0; col < cols; col++) {
          const { pt, proximity } = getWarpedPoint(
            col * cellW,
            row * cellH,
            col,
            row,
            mouse,
            ripples,
            cols,
            rows,
          );
          pts[row][col] = pt;
          prox[row][col] = proximity;
        }
      }

      // ── Garis ─────────────────────────────────────────────────────────────
      const drawSeg = (p1: Point, p2: Point, pr1: number, pr2: number) => {
        const avg = (pr1 + pr2) / 2;
        const t = avg * avg * (3 - 2 * avg);
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.strokeStyle = lerpColor(LINE_BASE, theme.lineActive, t);
        ctx.lineWidth = lerpN(0.8, 1.5, t);
        ctx.stroke();
      };

      ctx.lineCap = "butt";

      for (let row = 0; row < rows; row++)
        for (let col = 0; col < cols - 1; col++)
          drawSeg(pts[row][col], pts[row][col + 1], prox[row][col], prox[row][col + 1]);

      for (let col = 0; col < cols; col++)
        for (let row = 0; row < rows - 1; row++)
          drawSeg(pts[row][col], pts[row + 1][col], prox[row][col], prox[row + 1][col]);

      // ── Simpul persilangan ────────────────────────────────────────────────
      for (let row = 0; row < rows; row++) {
        for (let col = 0; col < cols; col++) {
          const p = pts[row][col];
          const pr = prox[row][col];
          const t = pr * pr * (3 - 2 * pr);
          const r = lerpN(NODE_BASE_RADIUS, NODE_ACTIVE_RADIUS, t);

          if (t > 0.3) {
            const glowR = r + lerpN(0, 6, (t - 0.3) / 0.7);
            const grd = ctx.createRadialGradient(p.x, p.y, r * 0.5, p.x, p.y, glowR);
            grd.addColorStop(0, `rgba(${theme.glow},${(t * 0.3).toFixed(3)})`);
            grd.addColorStop(1, `rgba(${theme.glow},0)`);
            ctx.beginPath();
            ctx.arc(p.x, p.y, glowR, 0, TAU);
            ctx.fillStyle = grd;
            ctx.fill();
          }

          ctx.beginPath();
          ctx.arc(p.x, p.y, r, 0, TAU);
          ctx.fillStyle = lerpColor({ r: 255, g: 255, b: 255, a: 0.2 }, theme.nodeActive, t);
          ctx.fill();
        }
      }

      // ── Cincin riak ───────────────────────────────────────────────────────
      for (const r of ripples) {
        ctx.beginPath();
        ctx.arc(r.x, r.y, Math.max(0, r.radius), 0, TAU);
        ctx.strokeStyle = `rgba(${theme.ripple},${(r.opacity * 0.28).toFixed(3)})`;
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    },
    [getWarpedPoint, globalColor],
  );

  // ── Loop animasi ────────────────────────────────────────────────────────────

  const animate = useCallback(
    (now: number) => {
      const m = mouseRef.current;
      const t = targetMouseRef.current;

      m.x = lerpN(m.x, t.x, LERP_SPEED);
      m.y = lerpN(m.y, t.y, LERP_SPEED);

      // Kalau kursor sudah berhenti dan tidak ada riak, gambarnya identik dengan
      // frame sebelumnya. Menggambar ulang 60x per detik untuk hasil yang sama
      // hanya menghabiskan baterai.
      const bergerak = Math.abs(m.x - t.x) > 0.1 || Math.abs(m.y - t.y) > 0.1;
      if (bergerak || ripplesRef.current.length > 0 || perluGambarRef.current) {
        draw(now);
        perluGambarRef.current = false;
      }

      rafRef.current = requestAnimationFrame(animate);
    },
    [draw],
  );

  // ── Pemasangan ──────────────────────────────────────────────────────────────

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // Animasi ini digerakkan kursor dan bereaksi tiap klik — persis jenis gerak
    // yang dimaksud prefers-reduced-motion. Dimatikan total, bukan diperlambat.
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const setSize = () => {
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = window.innerWidth;
      const h = window.innerHeight;

      // Tanpa penskalaan DPR, garis setipis 0.8px akan tampak buram di layar
      // HiDPI — dan grid ini nyaris seluruhnya terdiri dari garis tipis.
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      sizeRef.current = { w, h };

      const tile = document.createElement("canvas");
      tile.width = Math.round(DOT_SPACING * dpr);
      tile.height = Math.round(DOT_SPACING * dpr);
      const tctx = tile.getContext("2d");
      if (tctx) {
        tctx.scale(dpr, dpr);
        tctx.fillStyle = "rgba(255,255,255,0.05)";
        tctx.beginPath();
        tctx.arc(DOT_SPACING / 2, DOT_SPACING / 2, 0.7, 0, TAU);
        tctx.fill();
        const pat = ctx.createPattern(tile, "repeat");
        if (pat) {
          pat.setTransform(new DOMMatrix([1 / dpr, 0, 0, 1 / dpr, 0, 0]));
          dotsRef.current = pat;
        }
      }

      perluGambarRef.current = true;
    };

    setSize();
    rafRef.current = requestAnimationFrame(animate);

    // Tab yang tersembunyi tidak perlu menghitung apa pun.
    const onVisibility = () => {
      cancelAnimationFrame(rafRef.current);
      if (!document.hidden) {
        perluGambarRef.current = true;
        rafRef.current = requestAnimationFrame(animate);
      }
    };

    // Kursor dan klik sengaja TIDAK didengarkan.
    //
    // Grid ini latar belakang, bukan kendali. Reaksinya terhadap kursor
    // menarik perhatian ke tempat yang tidak ada isinya, dan di halaman yang
    // dipakai untuk bekerja itu mengganggu alih-alih menyenangkan. Titik
    // pengaruhnya dikunci di luar layar, sehingga seluruh perhitungan
    // kedekatan menghasilkan nol dan gridnya diam.
    window.addEventListener("resize", setSize);
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      window.removeEventListener("resize", setSize);
      document.removeEventListener("visibilitychange", onVisibility);
      cancelAnimationFrame(rafRef.current);
    };
  }, [animate]);

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="kisi" aria-hidden="true">
      <canvas ref={canvasRef} />
    </div>
  );
}
