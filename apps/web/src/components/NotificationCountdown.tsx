import { useEffect, useId, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { animate, isTestEnvironment, prefersReducedMotion } from "../animations/core";

/** A clockwise CSS squircle perimeter, measured in local (untransformed) pixels. */
function perimeter(width: number, height: number, radius: number) {
  const inset = 1.2, right = width - inset, bottom = height - inset;
  const r = Math.max(0, Math.min(radius - inset, (width - 2 * inset) / 2, (height - 2 * inset) / 2));
  const points = [`M${width / 2} ${inset}`, `L${right - r} ${inset}`];
  const corners = [
    [right - r, inset + r, -Math.PI / 2], [right - r, bottom - r, 0],
    [inset + r, bottom - r, Math.PI / 2], [inset + r, inset + r, Math.PI],
  ];
  corners.forEach(([cx, cy, start]) => {
    for (let index = 0; index <= 48; index++) {
      const angle = start + index / 48 * Math.PI / 2;
      const x = Math.cos(angle), y = Math.sin(angle);
      points.push(`L${(cx + r * Math.sign(x) * Math.sqrt(Math.abs(x))).toFixed(3)} ${(cy + r * Math.sign(y) * Math.sqrt(Math.abs(y))).toFixed(3)}`);
    }
  });
  return `${points.join(" ")} Z`;
}

/** The timeout and perimeter consume the same remaining active time. */
export function useNotificationCountdown({ duration, paused, onComplete, pathRef }:
  { duration: number | null; paused: boolean; onComplete: () => void; pathRef: RefObject<SVGPathElement | null> }) {
  const budget = useRef({ duration, remaining: duration ?? 0 });
  const complete = useRef(onComplete);
  complete.current = onComplete;
  useEffect(() => {
    if (budget.current.duration !== duration) budget.current = { duration, remaining: duration ?? 0 };
    if (duration === null) return;
    const draw = (remaining: number) => {
      if (pathRef.current) pathRef.current.style.strokeDashoffset = String(-100 * (1 - remaining / Math.max(1, duration)));
    };
    draw(budget.current.remaining);
    if (paused) return;
    const started = performance.now();
    const remaining = budget.current.remaining;
    const cursor = { remaining };
    const motion = isTestEnvironment() ? null : animate(cursor, {
      remaining: 0, duration: remaining, ease: "linear",
      frameRate: prefersReducedMotion() ? 4 : 30,
      onRender: () => draw(cursor.remaining),
    });
    const timer = window.setTimeout(() => {
      budget.current.remaining = 0;
      draw(0);
      complete.current();
    }, remaining);
    return () => {
      window.clearTimeout(timer);
      motion?.cancel();
      budget.current.remaining = Math.max(0, remaining - (performance.now() - started));
      draw(budget.current.remaining);
    };
  }, [duration, paused, pathRef]);
}

export function NotificationCountdown({ cardRef, pathRef, seed }:
  { cardRef: RefObject<HTMLDivElement | null>; pathRef: RefObject<SVGPathElement | null>; seed: number }) {
  const id = `notification-rim-${useId().replace(/:/g, "")}`;
  const [geometry, setGeometry] = useState({ width: 410, height: 72, radius: 28 });
  useEffect(() => {
    const card = cardRef.current;
    if (!card) return;
    const measure = () => {
      if (!card.offsetWidth || !card.offsetHeight) return;
      const next = { width: card.offsetWidth, height: card.offsetHeight, radius: parseFloat(getComputedStyle(card).borderTopLeftRadius) || 28 };
      setGeometry(old => old.width === next.width && old.height === next.height && old.radius === next.radius ? old : next);
    };
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(card);
    window.addEventListener("resize", measure);
    return () => { observer?.disconnect(); window.removeEventListener("resize", measure); };
  }, [cardRef]);
  return <svg className="notification-countdown" aria-hidden="true" viewBox={`0 0 ${geometry.width} ${geometry.height}`}>
    <defs>
      <linearGradient id={id} x1={`${24 + seed % 18}%`} y1="0%" x2="85%" y2="100%">
        <stop stopColor="var(--rim-light-start)" /><stop offset=".21" stopColor="var(--rim-light-mid)" />
        <stop offset=".45" stopColor="var(--rim-tone)" /><stop offset=".72" stopColor="var(--rim-light-lower)" />
        <stop offset="1" stopColor="var(--rim-light-end)" />
      </linearGradient>
      <filter id={`${id}-halo`} filterUnits="userSpaceOnUse" x={-12} y={-12}
        width={geometry.width + 24} height={geometry.height + 24} colorInterpolationFilters="sRGB">
        <feDropShadow dx="0" dy="0" stdDeviation="2" floodColor="var(--rim-glow)" floodOpacity=".65" />
        <feDropShadow dx="0" dy="0" stdDeviation="2.7" floodColor="var(--rim-glow-soft)" floodOpacity=".22" />
      </filter>
    </defs>
    <path ref={pathRef} d={perimeter(geometry.width, geometry.height, geometry.radius)} pathLength={100}
      stroke={`url(#${id})`} filter={`url(#${id}-halo)`} strokeDasharray="100 100" strokeDashoffset="0" />
  </svg>;
}

export function NotificationTaskProgress({ progress }: { progress: number }) {
  const fill = useRef<HTMLSpanElement>(null);
  const initialized = useRef(false);
  useLayoutEffect(() => {
    const element = fill.current;
    if (!element) return;
    if (!initialized.current || isTestEnvironment()) {
      element.style.width = `${progress * 100}%`;
      initialized.current = true;
      return;
    }
    const motion = animate(element, { width: `${progress * 100}%`, duration: prefersReducedMotion() ? 120 : 220, ease: "outQuad" });
    return () => { motion.cancel(); };
  }, [progress]);
  return <div className="notification-progress-clip">
    <div className="notification-task-progress" role="progressbar" aria-label="Прогресс"
      aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}><span ref={fill} /></div>
  </div>;
}
