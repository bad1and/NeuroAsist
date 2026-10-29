import { expect, it } from "vitest";
import { createWelcomePortraitMesh } from "./welcome-portrait-rig";

it("pins the entire seat and supporting hand band to their original pixels", () => {
  const mesh = createWelcomePortraitMesh();
  let pinned = 0;
  for (let i = 0; i < mesh.length; i += 5) {
    const y = mesh[i + 1];
    if (y >= .59 && y <= .635) {
      expect(Array.from(mesh.slice(i + 2, i + 5))).toEqual([0, 0, 0]);
      pinned++;
    }
  }
  expect(pinned).toBeGreaterThan(100);
});

it("gives the torso and both feet separate movement without moving the hair beside the legs", () => {
  const mesh = createWelcomePortraitMesh();
  const point = (x: number, y: number) => {
    for (let i = 0; i < mesh.length; i += 5) {
      if (mesh[i] === x && mesh[i + 1] === y) return Array.from(mesh.slice(i + 2, i + 5));
    }
    throw new Error("Mesh point missing");
  };
  expect(point(.5, .125)).toEqual([1, 0, 0]);
  expect(point(.125, .9375)).toEqual([0, 1, 0]);
  expect(point(.375, .9375)).toEqual([0, 0, 1]);
  expect(point(.75, .75)).toEqual([0, 0, 0]);
});
