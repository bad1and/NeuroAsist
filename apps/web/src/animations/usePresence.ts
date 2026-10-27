import { useLayoutEffect, useRef, useState } from "react";
import { animate, isTestEnvironment, prefersReducedMotion } from "./core";

/** Keep an exiting popup mounted, and reverse from its current visual position. */
export function usePresence<T extends HTMLElement>(open: boolean, offset = 4) {
  const ref = useRef<T>(null);
  const [present, setPresent] = useState(open);
  const entered = useRef(false);
  useLayoutEffect(() => { if (open) setPresent(true); }, [open]);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || !present) { entered.current = false; return; }
    if (isTestEnvironment()) { if (!open) setPresent(false); return; }
    const reduced = prefersReducedMotion();
    let active = true;
    if (!entered.current) {
      element.style.opacity = "0";
      element.style.transform = `translateY(${reduced ? 0 : offset}px)`;
      entered.current = true;
    }
    const finish = () => {
      if (!active) return;
      if (!open) { entered.current = false; setPresent(false); }
      else { element.style.removeProperty("transform"); element.style.removeProperty("opacity"); }
    };
    const motion = animate(element, {
      opacity: open ? 1 : 0, translateY: reduced ? 0 : open ? 0 : offset,
      duration: reduced ? 100 : open ? 180 : 110, ease: "outCubic", onComplete: finish,
    });
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const preference = () => { motion.cancel(); finish(); };
    media?.addEventListener("change", preference);
    return () => { active = false; motion.cancel(); media?.removeEventListener("change", preference); };
  }, [open, present, offset]);
  return { ref, present };
}
