export const WIDTH = 336;
export const HEIGHT = 216;
export const RADIUS = 12;
const GRAVITY = 760;
const JUMP = 350;
const SPEED = 225;

export type Platform = { x: number; y: number; width: number };
export type World = {
  x: number; y: number; velocity: number; climbed: number; platforms: Platform[]; over: boolean;
};

export function createWorld(): World {
  return { x: WIDTH / 2, y: 198 - RADIUS, velocity: -JUMP, climbed: 0, over: false,
    platforms: [
      { x: 128, y: 198, width: 80 }, { x: 203, y: 145, width: 64 },
      { x: 131, y: 92, width: 60 }, { x: 209, y: 39, width: 60 },
      { x: 139, y: -14, width: 60 }, { x: 69, y: -67, width: 60 },
    ] };
}

// Fixed, small steps prevent tunnelling. Long frames never trigger catch-up work.
export function stepWorld(world: World, direction: number, elapsed: number, random = Math.random) {
  if (world.over) return;
  const dt = Math.max(0, Math.min(elapsed, 1 / 30));
  const previousFoot = world.y + RADIUS;
  world.x = Math.max(RADIUS, Math.min(WIDTH - RADIUS, world.x + direction * SPEED * dt));
  world.velocity += GRAVITY * dt;
  world.y += world.velocity * dt;
  if (world.velocity > 0) {
    const landing = world.platforms.find((platform) => previousFoot <= platform.y
      && world.y + RADIUS >= platform.y
      && world.x + RADIUS > platform.x && world.x - RADIUS < platform.x + platform.width);
    if (landing) { world.y = landing.y - RADIUS; world.velocity = -JUMP; }
  }
  const camera = Math.max(0, HEIGHT * 0.4 - world.y);
  if (camera) {
    world.y += camera;
    world.climbed += camera;
    world.platforms.forEach((platform) => { platform.y += camera; });
  }
  world.platforms = world.platforms.filter((platform) => platform.y < HEIGHT + 12);
  let top = world.platforms.reduce((a, b) => a.y < b.y ? a : b);
  while (top.y > -55) {
    const next = { x: Math.max(20, Math.min(WIDTH - 80, top.x + (random() < 0.5 ? -1 : 1) * (48 + random() * 30))),
      y: top.y - (50 + random() * 10), width: 60 };
    world.platforms.push(next);
    top = next;
  }
  world.over = world.y - RADIUS > HEIGHT;
}
