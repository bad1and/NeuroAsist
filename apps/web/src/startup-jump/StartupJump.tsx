import { useEffect, useRef, useState } from "react";
import { createTimer } from "animejs";
import { animate, prefersReducedMotion } from "../animations";
import { createWorld, HEIGHT, RADIUS, stepWorld, WIDTH, type World } from "./world";
import { createJumpMaterial } from "./material";
import "./StartupJump.css";

type Mode = "idle" | "playing" | "paused" | "over";
export function StartupJump({ available = true, autoStart = false }: { available?: boolean; autoStart?: boolean }) {
  const [mode, setMode] = useState<Mode>(autoStart && available ? "playing" : "idle");
  const rootRef = useRef<HTMLElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const worldRef = useRef<World>(createWorld());
  const keys = useRef(new Set<string>());
  const pointer = useRef(0);

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
    canvas.width = Math.round(WIDTH * dpr);
    canvas.height = Math.round(HEIGHT * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const style = getComputedStyle(canvas);
    const player = createJumpMaterial(RADIUS * 2, RADIUS * 2, 9, dpr, style);
    const draw = (sprite: HTMLCanvasElement, x: number, y: number) => {
      ctx.drawImage(sprite, x - 12, y - 12, sprite.width / dpr, sprite.height / dpr);
    };
    const paint = () => {
      const world = worldRef.current;
      ctx.clearRect(0, 0, WIDTH, HEIGHT);
      ctx.fillStyle = "rgb(255 255 255 / .075)";
      world.platforms.forEach((platform) => {
        ctx.beginPath(); ctx.roundRect(platform.x, platform.y, platform.width, 9, 4.5); ctx.fill();
      });
      ctx.globalAlpha = 1;
      draw(player, world.x - RADIUS, world.y - RADIUS);
    };
    paint();
    if (mode !== "playing" || !available) return;
    let last = performance.now();
    const timer = createTimer({ duration: 1000, loop: true, frameRate: 30, onUpdate: () => {
      const now = performance.now();
      const direction = pointer.current || Number(keys.current.has("ArrowRight") || keys.current.has("d"))
        - Number(keys.current.has("ArrowLeft") || keys.current.has("a"));
      stepWorld(worldRef.current, direction, (now - last) / 1000);
      last = now;
      paint();
      if (worldRef.current.over) { timer.pause(); setMode("over"); }
    } });
    return () => { timer.cancel(); keys.current.clear(); pointer.current = 0; };
  }, [mode, available]);

  useEffect(() => {
    const pause = () => {
      keys.current.clear(); pointer.current = 0;
      setMode((current) => current === "playing" ? "paused" : current);
    };
    const visibility = () => { if (document.hidden) pause(); };
    window.addEventListener("blur", pause);
    document.addEventListener("visibilitychange", visibility);
    return () => { window.removeEventListener("blur", pause); document.removeEventListener("visibilitychange", visibility); };
  }, []);

  const start = () => {
    if (!available) return;
    if (mode !== "paused") worldRef.current = createWorld();
    keys.current.clear(); pointer.current = 0;
    setMode("playing");
    rootRef.current?.focus({ preventScroll: true });
  };
  return <section ref={rootRef} className="startup-jump" tabIndex={0} aria-label="Мини-игра Прыжок"
    aria-describedby="jump-instructions" data-mode={mode}
    onPointerDown={(event) => {
      if (!available) return;
      if (mode !== "playing") start();
      event.currentTarget.setPointerCapture(event.pointerId);
      const bounds = canvasRef.current!.getBoundingClientRect();
      const x = (event.clientX - bounds.left) / bounds.width * WIDTH;
      pointer.current = Math.abs(x - worldRef.current.x) < RADIUS ? 0 : Math.sign(x - worldRef.current.x);
    }}
    onPointerMove={(event) => {
      if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
      const bounds = canvasRef.current!.getBoundingClientRect();
      const x = (event.clientX - bounds.left) / bounds.width * WIDTH;
      pointer.current = Math.abs(x - worldRef.current.x) < RADIUS ? 0 : Math.sign(x - worldRef.current.x);
    }}
    onPointerUp={() => { pointer.current = 0; }} onPointerCancel={() => { pointer.current = 0; }}
    onLostPointerCapture={() => { pointer.current = 0; }}
    onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setMode((current) => current === "playing" ? "paused" : current);
      keys.current.clear(); pointer.current = 0;
    }}
    onKeyDown={(event) => {
      const key = event.code === "KeyA" ? "a" : event.code === "KeyD" ? "d" : event.key;
      if (["ArrowLeft", "ArrowRight", "a", "d"].includes(key)) {
        event.preventDefault(); keys.current.add(key);
      }
      if (event.key === "Escape") setMode((current) => current === "playing" ? "paused" : current);
      if (event.key === " " && event.target === event.currentTarget) { event.preventDefault(); if (mode !== "playing") start(); }
    }}
    onKeyUp={(event) => { keys.current.delete(event.code === "KeyA" ? "a" : event.code === "KeyD" ? "d" : event.key); }}>
    <span id="jump-instructions" className="startup-jump-sr">Нажми на кубик или пробел, чтобы начать. Прыжки автоматические. Управление стрелками, A / D или удержанием пальца слева и справа. Escape — пауза.</span>
    <span className="startup-jump-sr" role="status">{!available ? "Iris готова" : mode === "over" ? "Можно начать снова" : mode === "paused" ? "Игра приостановлена" : ""}</span>
    <div className="startup-jump-field">
      <canvas ref={canvasRef} aria-hidden="true" />
    </div>
  </section>;
}
