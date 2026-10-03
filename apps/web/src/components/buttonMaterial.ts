import type { CSSProperties } from "react";

/** Deterministic material only: geometry, semantic colours and interactions stay fixed. */
export function materialStyle(seed: number, variation = 1): CSSProperties {
  let state = seed >>> 0;
  const random = () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let n = Math.imul(state ^ (state >>> 15), state | 1);
    n ^= n + Math.imul(n ^ (n >>> 7), n | 61);
    return ((n ^ (n >>> 14)) >>> 0) / 4294967296;
  };
  const range = (low: number, high: number) => Number(((low + high) / 2 + (random() - .5) * (high - low) * Math.max(0, Math.min(1, variation))).toFixed(3));
  const depth = range(.7, 1.5);
  return {
    "--dp-light-x": `${range(22, 78)}%`,
    "--dp-light-y": `${range(20, 62)}%`,
    "--dp-fill-factor": range(.88, 1),
    "--dp-edge-share": `${range(58, 80)}%`,
    "--dp-bloom-x": `${range(25, 75)}%`,
    "--dp-bloom-width": `${range(25, 52)}%`,
    "--lens-bloom-alpha": range(.14, .3),
    "--lens-inner-edge-blur": `${range(7, 16)}px`,
    "--lens-inner-top-alpha": range(.12, .26),
    "--lens-inner-bottom-alpha": range(.08, .17),
    "--lens-bevel-top": range(.16, .4),
    "--lens-bevel-bottom": range(.24, .48),
    "--lens-bevel-side": range(.12, .28),
    "--dp-noise-position": `${range(0, 128)}px ${range(0, 128)}px`,
    "--lens-depth": `0 ${3 * depth}px 0 -1px rgb(0 0 0 / .35), 0 ${8 * depth}px ${12 * depth}px -3px rgb(0 0 0 / .38), 0 ${18 * depth}px ${26 * depth}px -7px rgb(0 0 0 / .25)`,
  } as CSSProperties;
}

/** A logical action and entity ID always produce the same appearance. */
export function buttonSeed(key: string, base = 42): number {
  let hash = (2166136261 ^ base) >>> 0;
  for (let index = 0; index < key.length; index++) hash = Math.imul(hash ^ key.charCodeAt(index), 16777619) >>> 0;
  hash = Math.imul(hash ^ (hash >>> 16), 0x21f0aaad);
  hash = Math.imul(hash ^ (hash >>> 15), 0x735a2d97);
  return (hash ^ (hash >>> 15)) & 0x7fffffff;
}
