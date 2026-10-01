import { cubicBezier } from "animejs";
import { animate, isTestEnvironment, prefersReducedMotion, type Animation } from "./core";

export const NOTIFICATION_EXIT_DURATION = 190;

/** Shared toast motion, including the pinned conversation card. */
export function animateNotification(
  target: HTMLElement,
  phase: "enter" | "exit",
  onComplete?: () => void,
): Animation | null {
  if (isTestEnvironment()) return null;
  const reduced = prefersReducedMotion();
  const entering = phase === "enter";
  return animate(target, {
    opacity: entering ? target.style.opacity ? 1 : [0, 1] : 0,
    translateX: reduced ? 0 : entering ? target.style.transform ? 0 : [28, 0] : 28,
    scale: reduced ? 1 : entering ? target.style.transform ? 1 : [0.96, 1] : 0.96,
    duration: reduced ? 120 : entering ? 220 : NOTIFICATION_EXIT_DURATION,
    ease: entering ? cubicBezier(0.2, 0.8, 0.2, 1) : cubicBezier(0.42, 0, 1, 1),
    onComplete: () => onComplete?.(),
  });
}
