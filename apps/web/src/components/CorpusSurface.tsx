import { useId, useLayoutEffect, useRef, useState } from "react";

// Lower-right quarter of the existing apple-squircle-square (60% smoothing).
function smoothEnd(x: number, y: number, r: number) {
  const p = (a: number, b: number) => `${x + a * r} ${y + b * r}`;
  return `C${p(1, .2034)} ${p(1, .3216)} ${p(.9468, .5156)} C${p(.9142, .619)} ${p(.864, .7108)} ${p(.7874, .7874)} C${p(.7108, .864)} ${p(.619, .9142)} ${p(.5156, .9468)} C${p(.3216, 1)} ${p(.2034, 1)} ${p(0, 1)}`;
}

export function corpusOutline(w: number, h: number, side: number, top: number, inner: number) {
  const r = Math.min(top / 2, w / 2, h / 2);
  const end = `M0 0 H${w} V${top - r} ${smoothEnd(w - r, top - r, r)}`;
  if (!side) return `${end} H0 Z`;
  const c = Math.min(inner, w - side, Math.max(0, h - top - r));
  return `${end} H${side + c} ${c ? `A${c} ${c} 0 0 0 ${side} ${top + c}` : ""} V${h - r} ${smoothEnd(side - r, h - r, r)} H0 Z`;
}

// Light follows only the workspace-facing edge, never the outer window perimeter.
function corpusInnerEdge(w: number, h: number, side: number, top: number, inner: number) {
  const r = Math.min(top / 2, w / 2, h / 2);
  const end = `M${w} ${top - r} ${smoothEnd(w - r, top - r, r)}`;
  if (!side) return `${end} H0`;
  const c = Math.min(inner, w - side, Math.max(0, h - top - r));
  return `${end} H${side + c} ${c ? `A${c} ${c} 0 0 0 ${side} ${top + c}` : ""} V${h - r} ${smoothEnd(side - r, h - r, r)}`;
}

/** One silhouette for the material, bevel and cast shadow, including both ends. */
export function CorpusSurface() {
  const ref = useRef<SVGSVGElement>(null);
  const id = `corpus-${useId().replace(/:/g, "")}`;
  const [box, setBox] = useState({ w: 0, h: 0, side: 0, top: 0, inner: 0 });
  useLayoutEffect(() => {
    const shell = ref.current?.parentElement;
    const content = shell?.querySelector<HTMLElement>(":scope > .app-content");
    if (!shell || !content) return;
    const measure = () => {
      const s = shell.getBoundingClientRect(), c = content.getBoundingClientRect();
      const next = { w: s.width, h: s.height, side: c.left - s.left, top: c.top - s.top, inner: parseFloat(getComputedStyle(content).borderTopLeftRadius) || 0 };
      setBox(prev => Object.keys(next).every(k => prev[k as keyof typeof next] === next[k as keyof typeof next]) ? prev : next);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(shell);
    observer.observe(content);
    return () => observer.disconnect();
  }, []);
  const { w, h, side, top, inner } = box;
  return <svg ref={ref} className="corpus-surface" width={w} height={h} aria-hidden="true" focusable="false">
    <defs>
      <clipPath id={`${id}-clip`}><path d={corpusOutline(w, h, side, top, inner)} /></clipPath>
      <linearGradient id={`${id}-light`} gradientUnits="userSpaceOnUse" x1="0" y1="0" x2={side || w * .2} y2={h}>
        <stop offset="0" stopColor="white" stopOpacity=".55" />
        <stop offset=".22" stopColor="white" stopOpacity=".8" />
        <stop offset=".55" stopColor="white" stopOpacity=".12" />
        <stop offset=".8" stopColor="white" stopOpacity=".35" />
        <stop offset="1" stopColor="white" stopOpacity=".06" />
      </linearGradient>
      <filter id={`${id}-bevel`} x="-10%" y="-10%" width="120%" height="120%">
        <feGaussianBlur stdDeviation="14" />
      </filter>
    </defs>
    <g clipPath={`url(#${id}-clip)`}>
      <foreignObject width={w} height={h}>
        <div className="corpus-surface-material" />
      </foreignObject>
      <path className="corpus-surface-rim" d={corpusInnerEdge(w, h, side, top, inner)} fill="none" stroke={`url(#${id}-light)`} strokeWidth="36" filter={`url(#${id}-bevel)`} />
    </g>
  </svg>;
}
