import { useLayoutEffect, useRef } from "react";
import { animate, isTestEnvironment, prefersReducedMotion } from "../animations/core";
import type { StartupProgressState } from "../startup";
import "./StartupProgress.css";

export function StartupProgress({ progress }: { progress: StartupProgressState }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const previousValue = useRef(0);
  const value = progress.failed ? previousValue.current : progress.value;

  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const segments = [...root.querySelectorAll<HTMLElement>(".startup-progress-segment")];
    const target = value ?? 0;
    const from = previousValue.current;
    previousValue.current = target;
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    let motions: ReturnType<typeof animate>[] = [];
    const paint = (fraction: number) => {
      segments.forEach((segment, index) => {
        const portion = Math.max(0, Math.min(1, fraction * segments.length - index));
        segment.dataset.fill = portion === 0 ? "empty" : portion === 1 ? "full" : "partial";
        segment.style.setProperty("--startup-segment-portion", String(portion));
        segment.querySelector<HTMLElement>(".startup-progress-fill")!.style.width = `${portion * 100}%`;
        segment.querySelector<HTMLElement>(".startup-progress-remainder")!.style.left = `${portion * 100}%`;
      });
    };
    const start = () => {
      motions.forEach(motion => motion.cancel());
      motions = [];
      paint(target);
      root.style.setProperty("--startup-sweep-progress", "0");
      if (prefersReducedMotion() || isTestEnvironment() || progress.failed) return;
      if (value !== null) {
        const position = { fraction: from };
        paint(from);
        motions.push(animate(position, { fraction: target, duration: 620, ease: "outCubic",
          onUpdate: () => paint(position.fraction), onComplete: () => paint(target) }));
      }
      if (!progress.complete) {
        // All surfaces share one moving light field, clipped by their own shape.
        const sweep = { progress: -0.34 };
        root.style.setProperty("--startup-sweep-progress", String(sweep.progress));
        motions.push(animate(sweep, { progress: 1.19, duration: 2400, ease: "inOutSine", loop: true,
          onUpdate: () => root.style.setProperty("--startup-sweep-progress", String(sweep.progress)) }));
      }
    };
    start();
    media?.addEventListener("change", start);
    return () => { motions.forEach(motion => motion.cancel()); media?.removeEventListener("change", start); };
  }, [value, progress.failed, progress.complete]);

  return <div ref={rootRef} className="startup-progress" data-mode={progress.failed ? "failed" : progress.complete ? "complete" : value === null ? "indeterminate" : "loading"}
    role="progressbar" aria-label="Подготовка Iris" aria-valuemin={0} aria-valuemax={progress.components.length}
    aria-valuenow={value === null || progress.failed ? undefined : progress.complete ? progress.components.length : progress.settled}
    aria-valuetext={progress.detail}>
    {[0, 1, 2].map(index => <div key={index} className="startup-progress-segment" aria-hidden="true">
      <div className="startup-progress-remainder"><span className="startup-progress-sweep" /></div>
      <div className="startup-progress-fill"><span className="startup-progress-texture" /><span className="startup-progress-sweep" /></div>
    </div>)}
  </div>;
}
