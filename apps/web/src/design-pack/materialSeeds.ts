import { createContext } from "react";

export { materialStyle } from "../components/buttonMaterial";

export const MaterialSeed = createContext<number | null>(null);
export const maxSeed = 0x7fffffff;
export const seedStorageKey = "iris-design-pack-material-seed-v1";

export function validSeed(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= maxSeed;
}

export function readMaterialSeed(): number | null {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(seedStorageKey) ?? "null");
    return validSeed(value) ? value : null;
  } catch { return null; }
}

export function materialSeeds(base: number): number[] {
  return Array.from({ length: 6 }, (_, index) => (base + index * 7919) % (maxSeed + 1));
}
