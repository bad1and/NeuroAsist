import { animate, createTimeline, stagger, prefersReducedMotion, isTestEnvironment, ANIMATION_TOKENS } from "./core";
import type { Animation } from "./core";

/**
 * Animate page entrance: subtle fade and vertical slide
 */
export function animatePageEnter(target: HTMLElement | string): Animation | null {
  if (typeof window === "undefined" || !target || isTestEnvironment()) return null;
  const reduced = prefersReducedMotion();

  return animate(target, {
    opacity: [0, 1],
    translateY: reduced ? 0 : [6, 0],
    duration: reduced ? ANIMATION_TOKENS.duration.micro : ANIMATION_TOKENS.duration.page,
    ease: ANIMATION_TOKENS.ease.out,
  });
}

/**
 * Staggered cascade entrance for collections of cards or list items
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
    translateY: reduced ? 0 : [10, 0],
    duration: reduced ? ANIMATION_TOKENS.duration.micro : ANIMATION_TOKENS.duration.standard,
    delay: reduced ? 0 : stagger(customDelay),
    ease: ANIMATION_TOKENS.ease.out,
  });
}

/**
 * Animate newly added chat message bubble
 */
export function animateMessageEnter(element: HTMLElement): Animation | null {
  if (typeof window === "undefined" || !element || isTestEnvironment()) return null;
  const reduced = prefersReducedMotion();

  return animate(element, {
    opacity: [0, 1],
    translateY: reduced ? 0 : [12, 0],
    scale: reduced ? 1 : [0.98, 1],
    duration: reduced ? ANIMATION_TOKENS.duration.micro : ANIMATION_TOKENS.duration.standard,
    ease: ANIMATION_TOKENS.ease.out,
  });
}

/**
 * Dialog/modal entrance animation
 */
export function animateModalEnter(dialog: HTMLElement): Animation | null {
  if (typeof window === "undefined" || !dialog || isTestEnvironment()) return null;
  const reduced = prefersReducedMotion();

  return animate(dialog, {
    opacity: [0, 1],
    scale: reduced ? 1 : [0.96, 1],
    translateY: reduced ? 0 : [8, 0],
    duration: reduced ? ANIMATION_TOKENS.duration.micro : ANIMATION_TOKENS.duration.fast,
    ease: ANIMATION_TOKENS.ease.out,
  });
}

/**
 * Button click tactile micro-interaction
 */
export function animateButtonPress(element: HTMLElement): Animation | null {
  if (typeof window === "undefined" || !element || prefersReducedMotion() || isTestEnvironment()) return null;

  return animate(element, {
    scale: [1, 0.96, 1],
    duration: ANIMATION_TOKENS.duration.fast,
    ease: ANIMATION_TOKENS.ease.out,
  });
}

/**
 * Ambient breathing aura animation
 */
export function animateAmbientGlow(element: HTMLElement): Animation | null {
  if (typeof window === "undefined" || !element || prefersReducedMotion() || isTestEnvironment()) return null;

  return animate(element, {
    opacity: [0.35, 0.7, 0.35],
    scale: [0.98, 1.02, 0.98],
    duration: 3600,
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
    scale: [1, 1.05, 1],
    duration: 1200,
    loop: true,
    ease: "inOutSine",
  });
}
