import { useEffect, useRef } from "react";
import { waapi } from "animejs";
import { isTestEnvironment } from "../animations/core";
import "./LoadingRing.css";

/** A compositor-driven indicator; hidden tabs and reduced motion do no work. */
export function LoadingRing({ label = "Загружаю раздел…", className = "" }: {
  label?: string;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const element = ref.current;
    if (!element || isTestEnvironment()) return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    let motion: ReturnType<typeof waapi.animate> | undefined;
    const update = () => {
      motion?.revert();
      motion = undefined;
      if (!document.hidden && !media.matches) {
        motion = waapi.animate(element, { rotate: [0, 360], duration: 1000, ease: "linear", loop: true });
      }
    };
    update();
    document.addEventListener("visibilitychange", update);
    media.addEventListener("change", update);
    return () => {
      motion?.revert();
      document.removeEventListener("visibilitychange", update);
      media.removeEventListener("change", update);
    };
  }, []);
  return <div className={`section-loading ${className}`} role="status" aria-label={label}>
    <span ref={ref} className="loading-ring" aria-hidden="true" />
  </div>;
}
