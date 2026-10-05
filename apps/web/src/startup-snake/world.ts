export const COLUMNS = 14;
export const ROWS = 9;

export type Direction = { x: -1 | 0 | 1; y: -1 | 0 | 1 };
export type Point = { x: number; y: number };
export type World = {
  snake: Point[];
  direction: Direction;
  nextDirection: Direction;
  hasQueuedTurn: boolean;
  food: Point;
  score: number;
  over: boolean;
  won: boolean;
};

const RIGHT: Direction = { x: 1, y: 0 };

export function createWorld(): World {
  return {
    snake: [11, 10, 9, 8, 7, 6].map((x) => ({ x, y: 4 })),
    direction: RIGHT,
    nextDirection: RIGHT,
    hasQueuedTurn: false,
    food: { x: 4, y: 7 },
    score: 0,
    over: false,
    won: false,
  };
}

export function queueDirection(world: World, direction: Direction) {
  if (world.over || world.hasQueuedTurn) return;
  if (direction.x === -world.direction.x && direction.y === -world.direction.y) return;
  world.nextDirection = direction;
  world.hasQueuedTurn = true;
}

export function stepWorld(world: World, random = Math.random) {
  if (world.over) return;
  world.direction = world.nextDirection;
  world.hasQueuedTurn = false;
  const head = world.snake[0];
  const next = {
    x: (head.x + world.direction.x + COLUMNS) % COLUMNS,
    y: head.y + world.direction.y,
  };
  if (next.y < 0 || next.y >= ROWS) {
    world.over = true;
    return;
  }

  const eats = next.x === world.food.x && next.y === world.food.y;
  const occupied = eats ? world.snake : world.snake.slice(0, -1);
  if (occupied.some((point) => point.x === next.x && point.y === next.y)) {
    world.over = true;
    return;
  }

  world.snake.unshift(next);
  if (eats) {
    world.score += 1;
    const occupiedCells = new Set(world.snake.map((point) => `${point.x},${point.y}`));
    const freeCells: Point[] = [];
    for (let y = 0; y < ROWS; y += 1) {
      for (let x = 0; x < COLUMNS; x += 1) {
        if (!occupiedCells.has(`${x},${y}`)) freeCells.push({ x, y });
      }
    }
    if (freeCells.length === 0) {
      world.over = true;
      world.won = true;
      return;
    }
    const index = Math.min(freeCells.length - 1, Math.floor(Math.max(0, random()) * freeCells.length));
    world.food = freeCells[index];
  } else {
    world.snake.pop();
  }
}
