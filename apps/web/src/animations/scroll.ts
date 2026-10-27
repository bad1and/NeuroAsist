import { animate, prefersReducedMotion, type Animation } from "./core";

/** Short wheel smoothing. Touch, precision scrolling and browser zoom stay native. */
export function installSmoothWheel(root: HTMLElement): () => void {
  let motion: Animation | null = null;
  let scroller: HTMLElement | null = null;
  let destination = 0;
  let written = 0;
  let lastWheel = -Infinity;
  const stop = () => { motion?.cancel(); motion = null; scroller = null; };
  const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  const wheel = (event: WheelEvent) => {
    const mode = event.deltaMode;
    const magnitude = Math.abs(event.deltaY);
    if (event.defaultPrevented || !event.cancelable || event.ctrlKey || event.metaKey || event.shiftKey || !Number.isFinite(event.deltaY) || !magnitude || prefersReducedMotion()) { stop(); return; }
    const interval = event.timeStamp - lastWheel;
    lastWheel = event.timeStamp;
    // DPI scaling can produce 33.333 or 53px mouse steps. Value divisibility
    // cannot identify a device; preserve fine, high-frequency precision streams.
    const precision = mode === 0 && (magnitude < 12 || (interval >= 0 && interval < 35 && magnitude < 40));
    if (precision || Math.abs(event.deltaX) >= magnitude * .5) { stop(); return; }
    const origin = event.target instanceof Element ? event.target : null;
    if (!origin || origin.closest("textarea, input, select, [contenteditable='true'], [data-native-scroll]")) return;
    let target = origin as HTMLElement | null;
    while (target && root.contains(target)) {
      if (target.scrollHeight > target.clientHeight + 1 && /^(auto|scroll)$/.test(getComputedStyle(target).overflowY)) break;
      target = target.parentElement;
    }
    if (!target || !root.contains(target)) return;
    const current = target.scrollTop;
    const maximum = target.scrollHeight - target.clientHeight;
    if ((event.deltaY < 0 && current <= 0) || (event.deltaY > 0 && current >= maximum - 1)) { stop(); return; }
    const delta = event.deltaY * (mode === 1 ? 20 : mode === 2 ? target.clientHeight : 1);
    const continuing = scroller === target && motion && Math.sign(destination - current) === Math.sign(delta);
    const limit = Math.min(480, target.clientHeight * .8);
    destination = Math.max(0, Math.min(maximum, current + Math.max(-limit, Math.min(limit, (continuing ? destination - current : 0) + delta))));
    motion?.cancel();
    scroller = target;
    written = current;
    event.preventDefault();
    const position = { value: current };
    motion = animate(position, {
      value: destination, duration: 240, ease: "outQuad",
      onUpdate: () => { if (scroller) { scroller.scrollTop = position.value; written = scroller.scrollTop; } },
      onComplete: () => { motion = null; scroller = null; },
    });
  };
  const scroll = (event: Event) => {
    // A jump to a search result, chat auto-follow or scrollbar drag wins immediately.
    if (event.target === scroller && scroller && Math.abs(scroller.scrollTop - written) > 1) stop();
  };
  const key = (event: KeyboardEvent) => {
    if (["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " ", "Tab", "Escape"].includes(event.key)) stop();
  };
  root.addEventListener("wheel", wheel, { passive: false });
  root.addEventListener("scroll", scroll, true);
  root.addEventListener("pointerdown", stop, true);
  root.addEventListener("touchstart", stop, { passive: true });
  root.addEventListener("keydown", key, true);
  media?.addEventListener("change", stop);
  return () => {
    stop();
    root.removeEventListener("wheel", wheel);
    root.removeEventListener("scroll", scroll, true);
    root.removeEventListener("pointerdown", stop, true);
    root.removeEventListener("touchstart", stop);
    root.removeEventListener("keydown", key, true);
    media?.removeEventListener("change", stop);
  };
}
