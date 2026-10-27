/** One invalidation listener per window, instead of one per material control. */
let revision = 0;
let subscribers = 0;
const invalidate = () => { revision++; };
export const materialGeometryRevision = () => revision;
export function subscribeMaterialGeometry(): () => void {
  if (subscribers++ === 0) {
    window.addEventListener("scroll", invalidate, { capture: true, passive: true });
    window.addEventListener("resize", invalidate, { passive: true });
  }
  return () => {
    if (--subscribers === 0) {
      window.removeEventListener("scroll", invalidate, true);
      window.removeEventListener("resize", invalidate);
      revision++;
    }
  };
}

type SizeListener = (width: number, height: number) => void;
const listeners = new Map<HTMLElement, SizeListener>();
let observer: ResizeObserver | null = null;

/** Shared observation avoids hundreds of independent observer callbacks on resize. */
export function observeMaterialSize(element: HTMLElement, onSize: SizeListener): () => void {
  if (typeof ResizeObserver === "undefined") {
    const bounds = element.getBoundingClientRect();
    onSize(bounds.width, bounds.height);
    return () => {};
  }
  observer ??= new ResizeObserver(entries => {
    for (const entry of entries) {
      const listener = listeners.get(entry.target as HTMLElement);
      if (!listener) continue;
      const box = entry.borderBoxSize?.[0];
      if (box) listener(box.inlineSize, box.blockSize);
      else {
        const bounds = entry.target.getBoundingClientRect();
        listener(bounds.width, bounds.height);
      }
    }
  });
  listeners.set(element, onSize);
  observer.observe(element);
  return () => {
    observer?.unobserve(element);
    listeners.delete(element);
    if (!listeners.size) { observer?.disconnect(); observer = null; }
  };
}
