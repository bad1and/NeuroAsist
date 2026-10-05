import { useEffect, useRef, useState } from "react";
import { createTimer } from "animejs";
import { animate, prefersReducedMotion } from "../animations";
import { createWorld, queueDirection, stepWorld, type Direction, type World } from "./world";
import "./StartupSnake.css";

type Mode = "idle" | "playing" | "paused" | "over";

const KEY_DIRECTIONS: Record<string, Direction> = {
  ArrowUp: { x: 0, y: -1 }, KeyW: { x: 0, y: -1 },
  ArrowDown: { x: 0, y: 1 }, KeyS: { x: 0, y: 1 },
  ArrowLeft: { x: -1, y: 0 }, KeyA: { x: -1, y: 0 },
  ArrowRight: { x: 1, y: 0 }, KeyD: { x: 1, y: 0 },
};

export function StartupSnake({ available = true, autoStart = false }: { available?: boolean; autoStart?: boolean }) {
  const [mode, setMode] = useState<Mode>(autoStart && available ? "playing" : "idle");
  const rootRef = useRef<HTMLElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const worldRef = useRef<World>(createWorld());
  const touchStart = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    if (autoStart && available) rootRef.current?.focus({ preventScroll: true });
  }, [autoStart, available]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const entrance = animate(root, { opacity: [0, 1], duration: prefersReducedMotion() ? 120 : 380, ease: "outCubic" });
    return () => { entrance.cancel(); };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.round(336 * dpr);
    canvas.height = Math.round(216 * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const style = getComputedStyle(canvas);
    const token = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
    const accent = token("--rim-light-mid", "#ad89de");
    const highlight = token("--rim-light-start", "#ddc8fa");
    const body = token("--rim-tone", "#695b86");
    const glow = token("--rim-glow", "rgb(157 116 214)");
    const cell = 24;
    const center = ({ x, y }: { x: number; y: number }) => ({ x: x * cell + cell / 2, y: y * cell + cell / 2 });

    const paint = () => {
      const world = worldRef.current;
      ctx.clearRect(0, 0, 336, 216);
      ctx.fillStyle = "rgb(236 238 243 / .16)";
      for (let y = cell / 2; y < 216; y += cell) {
        for (let x = cell / 2; x < 336; x += cell) {
          ctx.beginPath();
          ctx.arc(x, y, 1.05, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      const faded = mode === "paused" || mode === "idle" || !available;
      ctx.globalAlpha = faded ? 0.48 : 1;
      for (let index = world.snake.length - 1; index >= 0; index -= 1) {
        const point = center(world.snake[index]);
        const isHead = index === 0;
        const progress = world.snake.length <= 1 ? 1 : index / (world.snake.length - 1);
        const radius = isHead ? 9 : 7.1 + (1 - progress) * 0.7;
        const gradient = ctx.createLinearGradient(point.x - radius, point.y - radius, point.x + radius, point.y + radius);
        gradient.addColorStop(0, highlight);
        gradient.addColorStop(0.5, accent);
        gradient.addColorStop(1, body);
        ctx.fillStyle = gradient;
        ctx.shadowColor = glow;
        ctx.shadowBlur = isHead ? 7 : 3.5;
        ctx.beginPath();
        ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
        ctx.fill();

        if (isHead) {
          ctx.shadowBlur = 0;
          ctx.fillStyle = "rgb(248 245 255 / .92)";
          const forward = world.direction;
          const side = { x: -forward.y, y: forward.x };
          for (const offset of [-1, 1]) {
            ctx.beginPath();
            ctx.arc(point.x + forward.x * 3.2 + side.x * 3 * offset,
              point.y + forward.y * 3.2 + side.y * 3 * offset, 1.1, 0, Math.PI * 2);
            ctx.fill();
          }
          ctx.strokeStyle = "rgb(248 245 255 / .82)";
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(point.x + forward.x * 5.2 - side.x * 1.4, point.y + forward.y * 5.2 - side.y * 1.4);
          ctx.quadraticCurveTo(point.x + forward.x * 6.2, point.y + forward.y * 6.2,
            point.x + forward.x * 5.2 + side.x * 1.4, point.y + forward.y * 5.2 + side.y * 1.4);
          ctx.stroke();
        }
      }

      const food = center(world.food);
      ctx.globalAlpha = mode === "over" ? 0.72 : 1;
      ctx.fillStyle = highlight;
      ctx.shadowColor = glow;
      ctx.shadowBlur = 8;
      ctx.beginPath();
      ctx.arc(food.x, food.y, 5.6, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.shadowBlur = 0;
    };

    paint();
    if (mode !== "playing" || !available) return;
    let last = performance.now();
    let accumulated = 0;
    let active = true;
    const timer = createTimer({ duration: 1000, loop: true, frameRate: 30, onUpdate: () => {
      if (!active) return;
      const now = performance.now();
      accumulated = Math.min(accumulated + Math.min(now - last, 120), 165);
      last = now;
      while (accumulated >= 165 && !worldRef.current.over) {
        stepWorld(worldRef.current);
        accumulated -= 165;
      }
      paint();
      if (worldRef.current.over) {
        active = false;
        setMode("over");
      }
    } });
    return () => { active = false; timer.cancel(); };
  }, [mode, available]);

  useEffect(() => {
    const pause = () => setMode((current) => current === "playing" ? "paused" : current);
    const visibility = () => { if (document.hidden) pause(); };
    window.addEventListener("blur", pause);
    document.addEventListener("visibilitychange", visibility);
    return () => { window.removeEventListener("blur", pause); document.removeEventListener("visibilitychange", visibility); };
  }, []);

  const start = () => {
    if (!available) return;
    if (mode !== "paused") worldRef.current = createWorld();
    touchStart.current = null;
    setMode("playing");
    rootRef.current?.focus({ preventScroll: true });
  };

  const turn = (direction: Direction) => queueDirection(worldRef.current, direction);
  const status = !available ? "Iris готова" : mode === "over"
    ? `Игра окончена. Счёт: ${worldRef.current.score}. Нажми пробел, чтобы сыграть ещё.`
    : mode === "paused" ? "Игра приостановлена" : "";

  return <section ref={rootRef} className="startup-snake" tabIndex={0} aria-label="Мини-игра Змейка"
    aria-describedby="snake-instructions" data-mode={mode}
    onPointerDown={(event) => {
      rootRef.current?.focus({ preventScroll: true });
      if (mode !== "playing") start();
      if (event.pointerType === "touch") {
        touchStart.current = { x: event.clientX, y: event.clientY };
        event.currentTarget.setPointerCapture?.(event.pointerId);
      }
    }}
    onPointerUp={(event) => {
      const origin = touchStart.current;
      touchStart.current = null;
      if (!origin) return;
      const dx = event.clientX - origin.x;
      const dy = event.clientY - origin.y;
      if (Math.max(Math.abs(dx), Math.abs(dy)) < 14) return;
      turn(Math.abs(dx) > Math.abs(dy) ? { x: Math.sign(dx) as -1 | 1, y: 0 } : { x: 0, y: Math.sign(dy) as -1 | 1 });
    }}
    onPointerCancel={() => { touchStart.current = null; }}
    onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setMode((current) => current === "playing" ? "paused" : current);
    }}
    onKeyDown={(event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setMode((current) => current === "playing" ? "paused" : current === "paused" ? "playing" : current);
        return;
      }
      if (event.code === "Space" || event.key === " ") {
        event.preventDefault();
        if (mode !== "playing") start();
        return;
      }
      const direction = KEY_DIRECTIONS[event.code];
      if (direction) {
        event.preventDefault();
        if (mode === "over") start();
        if (mode !== "playing") setMode("playing");
        turn(direction);
      }
    }}>
    <span id="snake-instructions" className="startup-snake-sr">Управление стрелками или клавишами W, A, S, D. На сенсорном экране веди пальцем в нужную сторону. Пробел — начать или продолжить, Escape — пауза.</span>
    <span className="startup-snake-sr" role="status">{status}</span>
    <div className="startup-snake-field">
      <canvas ref={canvasRef} aria-hidden="true" />
    </div>
  </section>;
}
