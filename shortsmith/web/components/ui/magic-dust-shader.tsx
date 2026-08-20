"use client";

import React, { useRef, useState, useEffect } from "react";
import * as THREE from "three";
import { Canvas, useFrame } from "@react-three/fiber";

export type SequenceItem =
  | { type: "text"; text: string; offset?: [number, number, number] }
  | { type: "shape"; shape: "torus" | "sphere" | "box"; offset?: [number, number, number] };

export interface MagicDustProps {
  /** The sequence of texts and shapes to cycle through */
  sequence?: SequenceItem[];
  /** Number of particles in the system */
  particleCount?: number;
  /** Base color of the particles in HEX */
  particleColor?: string;
  /** Base size of the particles */
  particleSize?: number;
  /** Font family for the text */
  fontFamily?: string;
  /** How long the shape stays visible before deconstructing, in seconds */
  holdDuration?: number;
  /** Multiplier for the construction/deconstruction animation speed */
  animationSpeed?: number;
  /** The radius of the scattered cloud when particles are fully deconstructed */
  scatterRadius?: number;
}

const DEFAULT_SEQUENCE: SequenceItem[] = [
  { type: "text", text: "MAGIC", offset: [0, 0, 0] },
  { type: "shape", shape: "torus", offset: [0, 0, 0] },
  { type: "text", text: "DUST", offset: [0, 0, 0] },
  { type: "shape", shape: "sphere", offset: [0, 0, 0] },
  { type: "text", text: "UI FACTORY", offset: [0, 0, 0] },
  { type: "shape", shape: "box", offset: [0, 0, 0] },
];

function getScatteredPositions(count: number, radius: number) {
  const pos = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    const u = Math.random();
    const v = Math.random();
    const theta = u * 2.0 * Math.PI;
    const phi = Math.acos(2.0 * v - 1.0);
    const r = Math.cbrt(Math.random()) * radius;

    pos[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    pos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
    pos[i * 3 + 2] = r * Math.cos(phi);
  }
  return pos;
}

function getTextPositions(text: string, count: number, size: number, fontFamily: string) {
  if (typeof window === "undefined") return new Float32Array(count * 3);

  const canvas = document.createElement("canvas");
  canvas.width = 1024;
  canvas.height = 1024;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return new Float32Array(count * 3);

  ctx.fillStyle = "black";
  ctx.fillRect(0, 0, 1024, 1024);
  ctx.fillStyle = "white";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";

  let fontSize = 220;
  ctx.font = `900 ${fontSize}px ${fontFamily}`;
  const textWidth = ctx.measureText(text).width;

  if (textWidth > 900) {
    fontSize = Math.floor(fontSize * (900 / textWidth));
    ctx.font = `900 ${fontSize}px ${fontFamily}`;
  }

  ctx.fillText(text, 512, 512);

  const imgData = ctx.getImageData(0, 0, 1024, 1024).data;
  const points: { x: number; y: number }[] = [];

  for (let i = 0; i < 1024 * 1024; i++) {
    const r = imgData[i * 4];
    if (r > 128) {
      const x = i % 1024;
      const y = Math.floor(i / 1024);
      points.push({ x: (x / 1024 - 0.5) * size, y: -(y / 1024 - 0.5) * size });
    }
  }

  const positions = new Float32Array(count * 3);
  if (points.length === 0) return positions;

  for (let i = 0; i < count; i++) {
    const p = points[Math.floor(Math.random() * points.length)];
    positions[i * 3] = p.x + (Math.random() - 0.5) * 0.15;
    positions[i * 3 + 1] = p.y + (Math.random() - 0.5) * 0.15;
    positions[i * 3 + 2] = (Math.random() - 0.5) * 0.2;
  }
  return positions;
}

function getTorusPositions(count: number, scale: number) {
  const pos = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    const u = Math.random() * Math.PI * 2;
    const v = Math.random() * Math.PI * 2;
    const radius = 2.5;
    const tube = 1.0;
    const x = (radius + tube * Math.cos(v)) * Math.cos(u);
    const y = (radius + tube * Math.cos(v)) * Math.sin(u);
    const z = tube * Math.sin(v);
    pos[i * 3] = x * scale + (Math.random() - 0.5) * 0.3;
    pos[i * 3 + 1] = y * scale + (Math.random() - 0.5) * 0.3;
    pos[i * 3 + 2] = z * scale + (Math.random() - 0.5) * 0.3;
  }
  return pos;
}

function getSphereDestinations(count: number, radius: number) {
  const pos = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(Math.random() * 2 - 1);
    pos[i * 3] = radius * Math.sin(phi) * Math.cos(theta) + (Math.random() - 0.5) * 0.2;
    pos[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta) + (Math.random() - 0.5) * 0.2;
    pos[i * 3 + 2] = radius * Math.cos(phi) + (Math.random() - 0.5) * 0.2;
  }
  return pos;
}

function getBoxPositions(count: number, size: number) {
  const pos = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    const face = Math.floor(Math.random() * 6);
    let x = 0,
      y = 0,
      z = 0;
    const u = (Math.random() - 0.5) * size;
    const v = (Math.random() - 0.5) * size;
    const s = size / 2;
    if (face === 0) {
      x = s;
      y = u;
      z = v;
    } else if (face === 1) {
      x = -s;
      y = u;
      z = v;
    } else if (face === 2) {
      x = u;
      y = s;
      z = v;
    } else if (face === 3) {
      x = u;
      y = -s;
      z = v;
    } else if (face === 4) {
      x = u;
      y = v;
      z = s;
    } else {
      x = u;
      y = v;
      z = -s;
    }

    pos[i * 3] = x + (Math.random() - 0.5) * 0.2;
    pos[i * 3 + 1] = y + (Math.random() - 0.5) * 0.2;
    pos[i * 3 + 2] = z + (Math.random() - 0.5) * 0.2;
  }
  return pos;
}

function applyOffset(dest: Float32Array, dx: number, dy: number, dz: number = 0) {
  const out = new Float32Array(dest.length);
  for (let i = 0; i < dest.length; i += 3) {
    out[i] = dest[i] + dx;
    out[i + 1] = dest[i + 1] + dy;
    out[i + 2] = dest[i + 2] + dz;
  }
  return out;
}

function getOrderedDelays(targetPositions: Float32Array, count: number) {
  const delays = new Float32Array(count);
  let minX = Infinity;
  let maxX = -Infinity;

  for (let i = 0; i < count; i++) {
    const x = targetPositions[i * 3];
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
  }
  const range = maxX - minX === 0 ? 1 : maxX - minX;

  for (let i = 0; i < count; i++) {
    const x = targetPositions[i * 3];
    const normalizedX = (x - minX) / range;
    delays[i] = normalizedX * 0.7 + Math.random() * 0.3;
  }
  return delays;
}

const vertexShader = `
attribute vec3 aTarget;
attribute float aDelay;
attribute float aSize;
uniform float uProgress;
uniform float uSize;
varying float vAlpha;

void main() {
    float p = clamp((uProgress - aDelay) * 3.0, 0.0, 1.0);

    float ease = p < 0.5 ? 4.0 * p * p * p : 1.0 - pow(-2.0 * p + 2.0, 3.0) / 2.0;

    vec3 finalPos = mix(position, aTarget, ease);

    vec4 mvPosition = modelViewMatrix * vec4(finalPos, 1.0);
    gl_PointSize = uSize * aSize * (1.0 / -mvPosition.z);
    gl_Position = projectionMatrix * mvPosition;

    vAlpha = smoothstep(0.0, 0.2, p);
}
`;

const fragmentShader = `
uniform vec3 uColor;
varying float vAlpha;

void main() {
    vec2 cxy = 2.0 * gl_PointCoord - 1.0;
    float r = dot(cxy, cxy);
    if (r > 1.0) discard;

    float alpha = 1.0 - smoothstep(0.7, 1.0, r);
    gl_FragColor = vec4(uColor, alpha * vAlpha * 0.5);
}
`;

export function MagicDustCore({
  sequence = DEFAULT_SEQUENCE,
  particleCount = 10000,
  particleColor = "#ffffff",
  particleSize = 0.02,
  fontFamily = "sans-serif",
  holdDuration = 3.0,
  animationSpeed = 1.0,
  scatterRadius = 12,
}: MagicDustProps) {
  const colorObj = useState(() => new THREE.Color(particleColor))[0];

  const [{ origin, targets, sizes }] = useState(() => {
    const origin = getScatteredPositions(particleCount, scatterRadius);

    const sizes = new Float32Array(particleCount);
    for (let i = 0; i < particleCount; i++) {
      sizes[i] = Math.random() * 0.8 + 0.4;
    }

    const targets: { dest: Float32Array; delays: Float32Array; isText: boolean }[] = [];

    for (const item of sequence) {
      let dest: Float32Array;
      let isText = false;

      if (item.type === "text") {
        dest = getTextPositions(item.text, particleCount, 12, fontFamily);
        isText = true;
      } else {
        if (item.shape === "torus") dest = getTorusPositions(particleCount, 2.0);
        else if (item.shape === "sphere") dest = getSphereDestinations(particleCount, 4);
        else dest = getBoxPositions(particleCount, 5);
      }

      if (item.offset) {
        dest = applyOffset(dest, item.offset[0], item.offset[1], item.offset[2]);
      }

      targets.push({ dest, delays: getOrderedDelays(dest, particleCount), isText });
    }

    return { origin, targets, sizes };
  });

  const matRef = useRef<THREE.ShaderMaterial>(null);
  const geoRef = useRef<THREE.BufferGeometry>(null);
  const pointsGroupRef = useRef<THREE.Points>(null);

  const currentProgress = useRef(0);
  const targetProgress = useRef(0);
  const currentTargetIndex = useRef(0);

  const phase = useRef<"CONSTRUCTING" | "HOLDING" | "DECONSTRUCTING">("CONSTRUCTING");
  const timer = useRef(0);

  useFrame((state, delta) => {
    if (phase.current === "CONSTRUCTING") {
      targetProgress.current = Math.min(1.5, targetProgress.current + delta * 0.4 * animationSpeed);
      if (targetProgress.current === 1.5) {
        phase.current = "HOLDING";
        timer.current = 0;
      }
    } else if (phase.current === "HOLDING") {
      timer.current += delta;
      if (timer.current > holdDuration) {
        phase.current = "DECONSTRUCTING";
      }
    } else if (phase.current === "DECONSTRUCTING") {
      targetProgress.current = Math.max(0.0, targetProgress.current - delta * 0.6 * animationSpeed);
      if (targetProgress.current === 0.0) {
        const nextTarget = (currentTargetIndex.current + 1) % targets.length;
        currentTargetIndex.current = nextTarget;

        if (geoRef.current) {
          const targetData = targets[nextTarget];
          const targetAttr = geoRef.current.attributes.aTarget as THREE.BufferAttribute;
          const delayAttr = geoRef.current.attributes.aDelay as THREE.BufferAttribute;

          (targetAttr.array as Float32Array).set(targetData.dest);
          targetAttr.needsUpdate = true;

          (delayAttr.array as Float32Array).set(targetData.delays);
          delayAttr.needsUpdate = true;
        }

        phase.current = "CONSTRUCTING";
      }
    }

    currentProgress.current += (targetProgress.current - currentProgress.current) * 0.1;

    if (matRef.current) {
      matRef.current.uniforms.uProgress.value = currentProgress.current;
      matRef.current.uniforms.uSize.value =
        Math.min(window.innerWidth, window.innerHeight) * particleSize;
    }

    if (pointsGroupRef.current) {
      // Skala mengikuti lebar viewport supaya bentuknya tidak pernah terpotong.
      const maxComponentWidth = 15.0;
      const scale = Math.min(1.0, state.viewport.width / maxComponentWidth);
      pointsGroupRef.current.scale.set(scale, scale, scale);

      const currentTarget = targets[currentTargetIndex.current];
      const currentY = pointsGroupRef.current.rotation.y;

      if (currentTarget.isText) {
        // Teks dikunci menghadap kamera; kalau ikut berputar, ia jadi tidak terbaca.
        const targetY = Math.round(currentY / (Math.PI * 2)) * (Math.PI * 2);
        pointsGroupRef.current.rotation.y += (targetY - currentY) * 0.08;
      } else {
        pointsGroupRef.current.rotation.y += delta * 0.15;
      }

      pointsGroupRef.current.rotation.x = Math.sin(state.clock.elapsedTime * 0.2) * 0.1;
    }
  });

  if (!origin.length || !targets.length) return null;

  return (
    <points ref={pointsGroupRef}>
      <bufferGeometry ref={geoRef}>
        <bufferAttribute attach="attributes-position" args={[origin, 3]} />
        <bufferAttribute attach="attributes-aTarget" args={[targets[0].dest, 3]} />
        <bufferAttribute attach="attributes-aDelay" args={[targets[0].delays, 1]} />
        <bufferAttribute attach="attributes-aSize" args={[sizes, 1]} />
      </bufferGeometry>
      <shaderMaterial
        ref={matRef}
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
        uniforms={{
          uProgress: { value: 0 },
          uSize: { value: 10.0 },
          uColor: { value: colorObj },
        }}
        transparent={true}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}

export function MagicDust(props: MagicDustProps) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    requestAnimationFrame(() => setMounted(true));
  }, []);

  if (!mounted) return null;

  return (
    <Canvas camera={{ position: [0, 0, 9], fov: 45 }} dpr={[1, 2]}>
      <MagicDustCore {...props} />
    </Canvas>
  );
}
