import { useLayoutEffect, type RefObject } from "react";
import "./ScrollEdgeFade.css";

/** Settings' spatial fade: short content and the first/last rows stay clear. */
export function scrollEdgeFade(scrollTop: number, clientHeight: number, scrollHeight: number) {
  const height = Math.max(0, clientHeight);
  const range = Math.max(0, scrollHeight - height);
  const position = Math.max(0, Math.min(range, scrollTop));
  return { top: Math.min(48, height / 4, position), bottom: Math.min(64, height / 4, range - position) };
}

const viewports = new WeakMap<HTMLElement, { users: number; dispose: () => void }>();

/** Shared by explicit hooks and the application's scroll-viewport registry. */
export function observeScrollEdgeFade(viewport: HTMLElement) {
  let entry = viewports.get(viewport);
  if (!entry) {
    let frame: number | undefined;
    const measure = () => {
      frame = undefined;
      // Responsive workspaces can switch between scrolling and a fixed shell.
      // Only the scrolling paint area fades; shell shadows stay intact.
      const overflow = getComputedStyle(viewport).overflowY;
      const scrolls = overflow === "auto" || overflow === "scroll";
      const fade = scrolls ? scrollEdgeFade(viewport.scrollTop, viewport.clientHeight, viewport.scrollHeight) : { top: 0, bottom: 0 };
      viewport.toggleAttribute("data-scroll-edge-fade", fade.top > 0 || fade.bottom > 0);
      viewport.style.setProperty("--scroll-fade-top", `${fade.top}px`);
      viewport.style.setProperty("--scroll-fade-bottom", `${fade.bottom}px`);
    };
    const schedule = () => { frame ??= requestAnimationFrame(measure); };
    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule);
    const observeContent = () => {
      resize?.disconnect();
      resize?.observe(viewport);
      // A scroll viewport can keep its size while a section or disclosure grows.
      for (const child of viewport.children) resize?.observe(child);
    };
    const mutations = new MutationObserver(records => {
      if (records.some(record => record.type === "childList")) observeContent();
      schedule();
    });
    mutations.observe(viewport, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["hidden", "open", "class"] });
    viewport.addEventListener("scroll", schedule, { passive: true });
    viewport.addEventListener("load", schedule, true);
    window.addEventListener("resize", schedule);
    observeContent();
    measure();
    entry = { users: 0, dispose: () => {
      mutations.disconnect();
      resize?.disconnect();
      viewport.removeEventListener("scroll", schedule);
      viewport.removeEventListener("load", schedule, true);
      window.removeEventListener("resize", schedule);
      if (frame !== undefined) cancelAnimationFrame(frame);
      viewport.removeAttribute("data-scroll-edge-fade");
      viewport.style.removeProperty("--scroll-fade-top");
      viewport.style.removeProperty("--scroll-fade-bottom");
    } };
    viewports.set(viewport, entry);
  }
  entry.users++;
  let active = true;
  return () => {
    if (!active) return;
    active = false;
    if (--entry.users === 0) { entry.dispose(); viewports.delete(viewport); }
  };
}

export function useScrollEdgeFade(ref: RefObject<HTMLElement | null>) {
  useLayoutEffect(() => ref.current ? observeScrollEdgeFade(ref.current) : undefined, [ref]);
}
