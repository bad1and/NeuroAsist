import { describe, expect, it } from "vitest";
import { createWorld, HEIGHT, RADIUS, stepWorld, WIDTH } from "./world";

describe("startup jump physics", () => {
  it("lands on a platform only while falling and bounces automatically", () => {
    const world = createWorld();
    world.y = 186; world.velocity = 200;
    stepWorld(world, 0, 1 / 30);
    expect(world.y).toBe(198 - RADIUS);
    expect(world.velocity).toBe(-350);
    world.y = 202; world.velocity = -200;
    stepWorld(world, 0, 1 / 30);
    expect(world.velocity).toBeGreaterThan(-200);
    expect(world.y).toBeLessThan(202);
  });

  it("does not bounce when missing the edge of a platform", () => {
    const world = createWorld();
    world.x = 50; world.y = 186; world.velocity = 200;
    stepWorld(world, 0, 1 / 30);
    expect(world.velocity).toBeGreaterThan(0);
  });

  it("clamps movement and bounds work after a delayed frame", () => {
    const world = createWorld();
    stepWorld(world, 1, 20);
    expect(world.x).toBe(WIDTH / 2 + 7.5);
    world.x = WIDTH - RADIUS;
    stepWorld(world, 1, 1 / 30);
    expect(world.x).toBe(WIDTH - RADIUS);
    world.x = RADIUS;
    stepWorld(world, -1, 1 / 30);
    expect(world.x).toBe(RADIUS);
  });

  it("recycles a bounded number of reachable platforms through a long climb", () => {
    const world = createWorld();
    for (let index = 0; index < 1000; index += 1) {
      world.y = HEIGHT * 0.4 - 5;
      world.velocity = -100;
      stepWorld(world, 0, 1 / 30, () => 0.7);
      expect(world.platforms.length).toBeLessThanOrEqual(7);
      const platforms = [...world.platforms].sort((a, b) => b.y - a.y);
      platforms.slice(1).forEach((platform, i) => {
        expect(platforms[i].y - platform.y).toBeLessThanOrEqual(60);
        expect(Math.abs(platforms[i].x - platform.x)).toBeLessThanOrEqual(78);
      });
    }
    expect(world.climbed).toBeGreaterThan(5000);
  });

  it("ends below the field and freezes a finished world", () => {
    const world = createWorld();
    world.y = HEIGHT + RADIUS + 1; world.velocity = 50;
    stepWorld(world, 0, 1 / 30);
    expect(world.over).toBe(true);
    const finished = structuredClone(world);
    stepWorld(world, 1, 1 / 30);
    expect(world).toEqual(finished);
  });
});
