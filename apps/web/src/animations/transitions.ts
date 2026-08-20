import { animate, createTimeline, stagger, prefersReducedMotion, isTestEnvironment, ANIMATION_TOKENS } from "./core";
import type { Animation } from "./core";

/**
 * Animate page entrance: subtle fade, scale and vertical slide with cubic easing
 */
export function animatePageEnter(target: HTMLElement | string): Animation | null {
  if (typeof window === "undefined" || !target || isTestEnvironment()) return null;
  const reduced = prefersReducedMotion();

  return animate(target, {
    opacity: [0, 1],
    translateY: reduced ? 0 : [10, 0],
    duration: reduced ? ANIMATION_TOKENS.duration.micro : ANIMATION_TOKENS.duration.page,
    ease: ANIMATION_TOKENS.ease.smooth,
  });
}

/**
 * Staggered cascade entrance for collections of cards or list items with soft spring
 */
export function animateStaggerCards(
  container: HTMLElement | string,
  itemSelector: string = ".overview-card, .history-card, .memory-card, .event-row, .state-card, article",
  customDelay: number = 40,
): Animation | null {
  if (typeof window === "undefined" || !container || isTestEnvironment()) return null;
  const reduced = prefersReducedMotion();
  const targets = typeof container === "string" 
    ? `${container} ${itemSelector}`
    : container.querySelectorAll(itemSelector);

  if (!targets || (targets instanceof NodeList && targets.length === 0)) return null;

  return animate(targets, {
    opacity: [0, 1],
    scale: reduced ? 1 : [0.96, 1],
    translateY: reduced ? 0 : [14, 0],
    duration: reduced ? ANIMATION_TOKENS.duration.micro : ANIMATION_TOKENS.duration.medium,
    delay: reduced ? 0 : stagger(customDelay, { from: "first" }),
    ease: ANIMATION_TOKENS.ease.softSpring,
  });
}

/**
 * Expressive chat message entrance with soft spring bounce
 */
export function animateMessagePop(element: HTMLElement): Animation | null {
  if (typeof window === "undefined" || !element || isTestEnvironment()) return null;
  const reduced = prefersReducedMotion();

  return animate(element, {
    opacity: [0, 1],
    translateY: reduced ? 0 : [12, 0],
    scale: reduced ? 1 : [0.93, 1],
    duration: reduced ? ANIMATION_TOKENS.duration.micro : ANIMATION_TOKENS.duration.standard,
    ease: ANIMATION_TOKENS.ease.bounce,
  });
}

/**
 * Legacy alias for animateMessagePop
 */
export const animateMessageEnter = animateMessagePop;

/**
 * Animated number counter (counts smoothly from start to target value)
 */
export function animateNumberCounter(
  element: HTMLElement,
  targetValue: number,
  formatter?: (val: number) => string,
): Animation | null {
  if (typeof window === "undefined" || !element || isTestEnvironment()) {
    if (element) element.textContent = formatter ? formatter(targetValue) : String(targetValue);
    return null;
  }
  if (prefersReducedMotion()) {
    element.textContent = formatter ? formatter(targetValue) : String(targetValue);
    return null;
  }

  const obj = { count: 0 };
  return animate(obj, {
    count: targetValue,
    duration: ANIMATION_TOKENS.duration.counter,
    ease: ANIMATION_TOKENS.ease.smooth,
    onUpdate: () => {
      const current = Math.round(obj.count);
      element.textContent = formatter ? formatter(current) : String(current);
    },
  });
}

/**
 * Dialog/modal entrance animation with soft spring
 */
export function animateModalEnter(dialog: HTMLElement): Animation | null {
  if (typeof window === "undefined" || !dialog || isTestEnvironment()) return null;
  const reduced = prefersReducedMotion();

  return animate(dialog, {
    opacity: [0, 1],
    scale: reduced ? 1 : [0.92, 1],
    translateY: reduced ? 0 : [10, 0],
    duration: reduced ? ANIMATION_TOKENS.duration.micro : ANIMATION_TOKENS.duration.medium,
    ease: ANIMATION_TOKENS.ease.bounce,
  });
}

/**
 * Tactile button click spring micro-interaction
 */
export function animateButtonPress(element: HTMLElement): Animation | null {
  if (typeof window === "undefined" || !element || prefersReducedMotion() || isTestEnvironment()) return null;

  return animate(element, {
    scale: [1, 0.94, 1],
    duration: ANIMATION_TOKENS.duration.standard,
    ease: ANIMATION_TOKENS.ease.spring,
  });
}

/**
 * Active tab / filter pill switch bounce
 */
export function animateTabSwitch(element: HTMLElement): Animation | null {
  if (typeof window === "undefined" || !element || prefersReducedMotion() || isTestEnvironment()) return null;

  return animate(element, {
    scale: [0.94, 1.04, 1],
    duration: ANIMATION_TOKENS.duration.fast,
    ease: ANIMATION_TOKENS.ease.spring,
  });
}

/**
 * Notice / alert banner animated entry from top
 */
export function animateNoticeEnter(element: HTMLElement): Animation | null {
  if (typeof window === "undefined" || !element || isTestEnvironment()) return null;
  const reduced = prefersReducedMotion();

  return animate(element, {
    opacity: [0, 1],
    translateY: reduced ? 0 : [-10, 0],
    scale: reduced ? 1 : [0.98, 1],
    duration: reduced ? ANIMATION_TOKENS.duration.micro : ANIMATION_TOKENS.duration.fast,
    ease: ANIMATION_TOKENS.ease.softSpring,
  });
}

/**
 * Assistant thinking floating dots wave
 */
export function animateThinkingWave(dots: NodeListOf<HTMLElement> | HTMLElement[]): Animation | null {
  if (typeof window === "undefined" || !dots || dots.length === 0 || isTestEnvironment()) return null;
  if (prefersReducedMotion()) return null;

  return animate(dots, {
    translateY: [
      { to: -5, duration: 320, ease: "outQuad" },
      { to: 0, duration: 320, ease: "inQuad" },
    ],
    opacity: [
      { to: 1, duration: 320 },
      { to: 0.4, duration: 320 },
    ],
    delay: stagger(150),
    loop: true,
  });
}

/**
 * Ambient breathing visual orb animation
 */
export function animateOrb(element: HTMLElement): Animation | null {
  if (typeof window === "undefined" || !element || prefersReducedMotion() || isTestEnvironment()) return null;

  return animate(element, {
    scale: [0.97, 1.03, 0.97],
    opacity: [0.75, 1, 0.75],
    duration: 3600,
    loop: true,
    ease: "inOutSine",
  });
}

/**
 * Ambient breathing aura animation
 */
export function animateAmbientGlow(element: HTMLElement): Animation | null {
  if (typeof window === "undefined" || !element || prefersReducedMotion() || isTestEnvironment()) return null;

  return animate(element, {
    opacity: [0.35, 0.75, 0.35],
    scale: [0.98, 1.03, 0.98],
    duration: 3200,
    loop: true,
    ease: ANIMATION_TOKENS.ease.pulse,
  });
}

/**
 * Subtle pulse for live indicators and recording buttons
 */
export function animateLivePulse(element: HTMLElement): Animation | null {
  if (typeof window === "undefined" || !element || prefersReducedMotion() || isTestEnvironment()) return null;

  return animate(element, {
    scale: [1, 1.06, 1],
    duration: 1100,
    loop: true,
    ease: "inOutSine",
  });
}

/**
 * Live conversation pulsating radar rings
 */
export function animateLiveRadar(rings: NodeListOf<HTMLElement> | HTMLElement[]): Animation | null {
  if (typeof window === "undefined" || !rings || rings.length === 0 || isTestEnvironment()) return null;
  if (prefersReducedMotion()) return null;

  return animate(rings, {
    scale: [1, 1.6],
    opacity: [0.7, 0],
    duration: 1800,
    delay: stagger(600),
    loop: true,
    ease: "outQuad",
  });
}

/**
 * Smooth item removal (scale down and fade before DOM deletion)
 */
export function animateCardRemove(
  element: HTMLElement,
  onComplete?: () => void,
): Animation | null {
  if (typeof window === "undefined" || !element || isTestEnvironment()) {
    onComplete?.();
    return null;
  }
  const reduced = prefersReducedMotion();

  const params: Record<string, unknown> = {
    opacity: [1, 0],
    scale: reduced ? 1 : [1, 0.9],
    translateY: reduced ? 0 : [0, -8],
    duration: reduced ? ANIMATION_TOKENS.duration.micro : ANIMATION_TOKENS.duration.fast,
    ease: "inQuad",
  };
  if (onComplete) {
    params.onComplete = onComplete;
  }

  return animate(element, params as Parameters<typeof animate>[1]);
}
