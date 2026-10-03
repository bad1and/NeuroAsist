import { describe, expect, it } from "vitest";
import { materialSeeds, materialStyle, maxSeed, validSeed } from "./materialSeeds";

describe("repeatable material seeds", () => {
  it("reproduces lighting from its seed and gives distinct styles for different seeds", () => {
    expect(materialStyle(42)).toEqual(materialStyle(42));
    const styles = materialSeeds(42).map((seed) => JSON.stringify(materialStyle(seed)));
    expect(new Set(styles).size).toBe(6);
    expect(materialStyle(0)).not.toEqual(materialStyle(maxSeed));
  });

  it("keeps seed batches in range, including wraparound", () => {
    expect(materialSeeds(maxSeed).every(validSeed)).toBe(true);
    expect(new Set(materialSeeds(maxSeed)).size).toBe(6);
    for (const value of [-1, 1.5, NaN, Infinity, maxSeed + 1, "42", null]) expect(validSeed(value)).toBe(false);
  });
});
