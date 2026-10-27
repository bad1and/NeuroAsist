import { useLayoutEffect, type RefObject } from "react";

/** A spatial mask follows scrolling; the first and last rows stay fully visible. */
export function useScrollEdgeFade(ref: RefObject<HTMLElement | null>) {
  useLayoutEffect(() => {
    const viewport = ref.current;
    if (!viewport) return;
    let frame: number | undefined;
    const measure = () => {
      frame = undefined;
      const height = viewport.clientHeight;
      const range = Math.max(0, viewport.scrollHeight - height);
      const position = Math.max(0, Math.min(range, viewport.scrollTop));
      viewport.style.setProperty("--scroll-fade-top", `${Math.min(32, height / 4, position)}px`);
      viewport.style.setProperty("--scroll-fade-bottom", `${Math.min(40, height / 4, range - position)}px`);
    };
    const schedule = () => { frame ??= requestAnimationFrame(measure); };
    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule);
    const observeContent = () => {
      resize?.disconnect();
      resize?.observe(viewport);
      // A scroll viewport can keep its size while a section or disclosure grows.
      for (const child of viewport.children) resize?.observe(child);
    };
    const mutations = new MutationObserver(() => { observeContent(); schedule(); });
    mutations.observe(viewport, { childList: true });
    viewport.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    observeContent();
    measure();
    return () => {
      mutations.disconnect();
      resize?.disconnect();
      viewport.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (frame !== undefined) cancelAnimationFrame(frame);
      viewport.style.removeProperty("--scroll-fade-top");
      viewport.style.removeProperty("--scroll-fade-bottom");
    };
  }, [ref]);
}
