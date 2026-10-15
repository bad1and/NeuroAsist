import { useLayoutEffect, type RefObject } from "react";

/** Fade lengths follow the actual scroll distance, including overscroll. */
export function timelineScrollFade(scrollTop: number, clientHeight: number, scrollHeight: number) {
  if (clientHeight <= 0) return { top: 0, bottom: 0 };
  const range = Math.max(0, scrollHeight - clientHeight);
  const position = Math.max(0, Math.min(range, scrollTop));
  return { top: Math.min(48, clientHeight / 4, position), bottom: Math.min(72, clientHeight / 3, range - position) };
}

export function useTimelineScrollFade(viewportRef: RefObject<HTMLDivElement | null>, contentRef: RefObject<HTMLDivElement | null>) {
  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    const content = contentRef.current;
    if (!viewport || !content) return;
    let frame: number | undefined;
    const measure = () => {
      frame = undefined;
      const fade = timelineScrollFade(viewport.scrollTop, viewport.clientHeight, viewport.scrollHeight);
      // This is a spatial scroll mask, not a timed animation. One update per frame
      // keeps the rail, markers and cards on exactly the same opacity surface.
      viewport.style.setProperty("--timeline-fade-top", `${fade.top}px`);
      viewport.style.setProperty("--timeline-fade-bottom", `${fade.bottom}px`);
    };
    const schedule = () => { frame ??= requestAnimationFrame(measure); };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule);
    observer?.observe(viewport);
    observer?.observe(content);
    viewport.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    measure();
    return () => {
      observer?.disconnect();
      viewport.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (frame !== undefined) cancelAnimationFrame(frame);
    };
  }, [viewportRef, contentRef]);
}
