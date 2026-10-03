import { cubicBezier } from "animejs";
import { animate, isTestEnvironment, prefersReducedMotion, type Animation } from "./core";

export const NOTIFICATION_EXIT_DURATION = 190;

/** Shared viewport-edge slide for toasts and the persistent conversation panel. */
export function animateNotification(
  target: HTMLElement,
  phase: "enter" | "exit",
  onComplete?: () => void,
): Animation | null {
  if (isTestEnvironment()) return null;
  const reduced = prefersReducedMotion();
  const entering = phase === "enter";
  const transform = getComputedStyle(target).transform;
  const currentX = transform && transform !== "none" ? new DOMMatrixReadOnly(transform).m41 : 0;
  // Subtract the current translation so closing mid-entry still aims beyond the edge.
  const left = target.getBoundingClientRect().left - currentX;
  const distance = Math.max(0, window.innerWidth - left) + 16;
  const interrupted = Boolean(target.style.transform);
  return animate(target, {
    opacity: reduced ? entering ? target.style.opacity ? 1 : [0, 1] : 0 : 1,
    translateX: reduced ? 0 : entering ? interrupted ? 0 : [distance, 0] : distance,
    scale: 1,
    duration: reduced ? 120 : entering ? 420 : NOTIFICATION_EXIT_DURATION,
    ease: entering ? cubicBezier(0.22, 1, 0.36, 1) : cubicBezier(0.42, 0, 1, 1),
    onComplete: () => onComplete?.(),
  });
}
