import { useEffect, useRef, type RefObject } from "react";
import { animate, isTestEnvironment } from "../animations/core";
import { NotificationCountdown } from "./NotificationCountdown";
import "./ConfirmationSurface.css";

/** A complete notification contour: brightness breathes, but no time is consumed. */
export function ConfirmationRim({ cardRef, seed, active = true }: {
  cardRef: RefObject<HTMLDivElement | null>; seed: number; active?: boolean;
}) {
  const pathRef = useRef<SVGPathElement>(null);
  const rimRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = rimRef.current;
    if (!element || isTestEnvironment()) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let motion: ReturnType<typeof animate> | null = null;
    const sync = () => {
      motion?.cancel();
      element.style.opacity = ".86";
      if (!active || reducedMotion.matches || document.hidden) return;
      motion = animate(element, {
        opacity: [.78, .92], duration: 2400 + seed % 5 * 80,
        alternate: true, loop: true, ease: "inOutSine", frameRate: 30,
      });
    };
    sync();
    reducedMotion.addEventListener("change", sync);
    document.addEventListener("visibilitychange", sync);
    return () => {
      motion?.cancel();
      reducedMotion.removeEventListener("change", sync);
      document.removeEventListener("visibilitychange", sync);
    };
  }, [active, seed]);
  return <div ref={rimRef} className="confirmation-rim" aria-hidden="true">
    <NotificationCountdown cardRef={cardRef} pathRef={pathRef} seed={seed} />
  </div>;
}
