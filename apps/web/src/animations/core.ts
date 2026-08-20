import {
  animate,
  createTimeline,
  stagger,
  createScope,
  Scope,
  utils,
} from "animejs";

export type Animation = ReturnType<typeof animate>;
export type Timeline = ReturnType<typeof createTimeline>;

export { animate, createTimeline, stagger, createScope, Scope, utils };

export function isTestEnvironment(): boolean {
  if (typeof import.meta !== "undefined" && import.meta.env?.MODE === "test") {
    return true;
  }
  const proc = typeof globalThis !== "undefined" ? (globalThis as unknown as { process?: { env?: Record<string, string> } }).process : undefined;
  return Boolean(proc?.env?.NODE_ENV === "test" || proc?.env?.VITEST === "true");
}

export function prefersReducedMotion(): boolean {
  if (isTestEnvironment()) return true;
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export const ANIMATION_TOKENS = {
  duration: {
    instant: 0,
    micro: 120,
    fast: 180,
    standard: 220,
    page: 240,
    ambient: 2400,
  },
  ease: {
    out: "outQuad",
    inOut: "inOutQuad",
    smooth: "outCubic",
    bounce: "outBack(1.4)",
    pulse: "inOutSine",
  },
} as const;

/**
 * Executes an animation safely respecting prefers-reduced-motion.
 * If reduced motion is enabled, spatial transformations are skipped and durations reduced.
 */
export function runSafeAnimation(
  target: Parameters<typeof animate>[0],
  parameters: Record<string, unknown>,
): Animation | null {
  if (typeof window === "undefined" || !target || isTestEnvironment()) return null;
  const reduced = prefersReducedMotion();

  if (reduced) {
    const sanitizedParams: Record<string, unknown> = {
      duration: ANIMATION_TOKENS.duration.micro,
      ease: "outQuad",
    };
    if ("opacity" in parameters) {
      sanitizedParams.opacity = parameters.opacity;
    }
    return animate(target, sanitizedParams as Parameters<typeof animate>[1]);
  }

  return animate(target, parameters as Parameters<typeof animate>[1]);
}
