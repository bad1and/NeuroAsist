import { useLayoutEffect, useRef, type RefObject } from "react";
import { animate, isTestEnvironment, prefersReducedMotion } from "./core";
import { animatePageEnter } from "./transitions";
import { installSmoothWheel } from "./scroll";

/** One route entrance owns the surface; nested entrances defer to it. */
export function useInterfaceMotion(ref: RefObject<HTMLElement | null>, view: string, ready: boolean) {
  const positions = useRef(new Map<string, number>());
  useLayoutEffect(() => {
    const root = ref.current;
    if (!root || !ready) return;
    const workspace = root.querySelector<HTMLElement>(".workspace");
    if (workspace) workspace.scrollTop = positions.current.get(view) ?? 0;
    const remember = () => { if (workspace) positions.current.set(view, workspace.scrollTop); };
    workspace?.addEventListener("scroll", remember, { passive: true });
    const entry = workspace ? animatePageEnter(workspace) : null;
    const stopScroll = installSmoothWheel(root.ownerDocument.body);
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const preference = () => { if (media?.matches) entry?.complete(); };
    media?.addEventListener("change", preference);
    return () => {
      entry?.revert(); stopScroll();
      workspace?.removeEventListener("scroll", remember);
      media?.removeEventListener("change", preference);
    };
  }, [ref, view, ready]);
}

/** The drawer keeps its inline position when interrupted; resize restores CSS ownership. */
export function useDrawerMotion(ref: RefObject<HTMLElement | null>, open: boolean) {
  const initialized = useRef(false);
  useLayoutEffect(() => {
    const drawer = ref.current;
    if (!drawer || isTestEnvironment()) return;
    const narrow = window.matchMedia("(max-width: 1023px)");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    let motion: ReturnType<typeof animate> | undefined;
    const restore = () => {
      motion?.cancel();
      drawer.style.removeProperty("opacity");
      if (narrow.matches) {
        drawer.style.transform = open ? "translateX(0%)" : "translateX(-105%)";
        initialized.current = true;
      } else { drawer.style.removeProperty("transform"); initialized.current = false; }
    };
    if (narrow.matches) {
      if (!initialized.current || reduced.matches) {
        drawer.style.transform = open ? "translateX(0%)" : "translateX(-105%)";
        initialized.current = true;
      } else {
        motion = animate(drawer, { translateX: open ? "0%" : "-105%", duration: open ? 220 : 170, ease: "outCubic" });
      }
    } else restore();
    narrow.addEventListener("change", restore);
    reduced.addEventListener("change", restore);
    return () => { motion?.cancel(); narrow.removeEventListener("change", restore); reduced.removeEventListener("change", restore); };
  }, [ref, open]);
}
