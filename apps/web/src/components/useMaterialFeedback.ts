import { useEffect, type RefObject } from "react";
import { createAnimatable, cubicBezier, type AnimatableObject } from "animejs";
import { animate, prefersReducedMotion, type Animation } from "../animations/core";

/** Shared cursor feedback for the accepted lens material. */
export function useMaterialFeedback(
  ref: RefObject<HTMLElement | null>,
  { field = false, disabled = false, pinned = "", seed = null, quiet = false, pressSurface = false, pressScale = true }:
  { field?: boolean; disabled?: boolean; pinned?: string; seed?: number | null; quiet?: boolean; pressSurface?: boolean; pressScale?: boolean } = {},
) {
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const rim = element.querySelector<HTMLElement>(":scope > .dp-rim");
    const light = element.querySelector<HTMLElement>(".dp-hover-light");
    const surface = element.querySelector<HTMLElement>(".dp-hover-surface");
    const spot = element.querySelector<HTMLElement>(".dp-hover-spot");
    if (!rim && !light && !surface) return;
    const running = new Map<HTMLElement, Animation>();
    let hovered = false;
    let focused = element.matches(":focus-visible") || (field && element.contains(document.activeElement));
    let pressed = false;
    let reduced = prefersReducedMotion();
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    // Independent of the material RNG: existing seeds retain their static appearance.
    let hash = (seed ?? 42) ^ 0x6d2b79f5;
    hash = Math.imul(hash ^ (hash >>> 16), 0x21f0aaad);
    hash = Math.imul(hash ^ (hash >>> 15), 0x735a2d97);
    hash = (hash ^ (hash >>> 15)) >>> 0;
    const character = (hash % 997) / 996;
    const fluidity = ((hash >>> 10) % 997) / 996;
    const spread = ((hash >>> 20) % 997) / 996;
    const ease = cubicBezier(.22, .68, 0, 1);
    let faceMotion: AnimatableObject | undefined;
    let lightMotion: AnimatableObject | undefined;
    let bounds: DOMRect | undefined;
    let frame = 0;
    let cursorX = 0;
    let cursorY = 0;
    let compactShape: boolean | undefined;

    const resetMotion = () => {
      cancelAnimationFrame(frame);
      frame = 0;
      faceMotion?.rotateX(0, 360);
      faceMotion?.rotateY(0, 360);
      faceMotion?.y(0, 360);
      lightMotion?.x(0, 360);
      lightMotion?.y(0, 360);
    };
    const track = () => {
      frame = 0;
      if (!hovered || disabled || reduced || field || !surface || !spot) return;
      bounds ??= element.getBoundingClientRect();
      if (!bounds.width || !bounds.height) return;
      const x = Math.max(-1, Math.min(1, (cursorX - bounds.left) / bounds.width * 2 - 1));
      const y = Math.max(-1, Math.min(1, (cursorY - bounds.top) / bounds.height * 2 - 1));
      const compact = bounds.width / bounds.height <= 3;
      const tilt = (compact ? 2.1 : 1.15) + character * .65;
      if (!faceMotion) {
        faceMotion = createAnimatable(surface, { rotateX: 230, rotateY: 230, y: 230, ease });
        lightMotion = createAnimatable(spot, { x: 160 + fluidity * 100, y: 160 + fluidity * 100, ease });
        light?.style.setProperty("--dp-hover-strength", `${.08 + character * .035}`);
      }
      if (compactShape !== compact) {
        compactShape = compact;
        light?.style.setProperty("--dp-hover-width", `${(compact ? 40 : 23) + spread * 12}%`);
      }
      // Only the decorative surface moves; text and hit bounds stay stable.
      faceMotion.rotateX(-y * tilt);
      faceMotion.rotateY(x * tilt);
      faceMotion.y(-.65 * (1 - Math.abs(y) * .35));
      lightMotion?.x(x * bounds.width * .42);
      lightMotion?.y(y * bounds.height * .38);
    };
    const move = (event: PointerEvent) => {
      if (event.pointerType === "touch" || reduced || disabled || field) return;
      if (!hovered) { hovered = true; update(); }
      cursorX = event.clientX;
      cursorY = event.clientY;
      if (!frame) frame = requestAnimationFrame(track);
    };
    const invalidateBounds = () => { bounds = undefined; };

    const change = (target: HTMLElement | null, values: Record<string, number>) => {
      if (!target) return;
      running.get(target)?.cancel();
      running.set(target, animate(target, { ...values, duration: reduced ? 120 : 180, ease: "outQuad" }));
    };
    const update = () => {
      const visible = !disabled && Boolean(pinned || focused || (field && (hovered || pressed)));
      element.dataset.rimVisible = String(visible);
      change(rim, { opacity: visible ? 1 : 0 });
      change(light, { opacity: !disabled && (hovered || pressed) ? 1 : 0 });
      if (quiet || (pressScale && pressSurface && !reduced)) change(surface, {
        ...(quiet ? { opacity: !disabled && (hovered || focused || pressed) ? 1 : 0 } : {}),
        ...(pressScale && pressSurface && !reduced ? { scale: pressed ? .96 : 1 } : {}),
      });
    };
    const restore = () => {
      if (!pressed) return;
      pressed = false;
      if (pressScale && !field && !reduced && !pressSurface) change(element, { scale: 1 });
      update();
    };
    const enter = (event: PointerEvent) => {
      if (disabled || event.pointerType === "touch") return;
      hovered = true;
      bounds = undefined;
      move(event);
      update();
    };
    const leave = () => { hovered = false; resetMotion(); restore(); update(); };
    const focus = (event: FocusEvent) => {
      const target = event.target;
      focused = field || (target instanceof HTMLElement && target.matches(":focus-visible"));
      update();
    };
    const blur = (event: FocusEvent) => {
      if (event.relatedTarget instanceof Node && element.contains(event.relatedTarget)) return;
      focused = false;
      restore();
      update();
    };
    const down = (event?: Event) => {
      if (disabled || (event?.target instanceof Element && event.target.closest("button:disabled"))) return;
      pressed = true;
      if (pressScale && !field && !reduced && !pressSurface) change(element, { scale: 0.96 });
      update();
    };
    const keydown = (event: KeyboardEvent) => {
      if (!field && (event.key === " " || event.key === "Enter") && !event.repeat) down();
    };
    const keyup = (event: KeyboardEvent) => {
      if (!field && (event.key === " " || event.key === "Enter")) restore();
    };
    const motionPreference = () => {
      reduced = prefersReducedMotion();
      resetMotion();
      if (reduced) {
        faceMotion?.revert();
        lightMotion?.revert();
        faceMotion = undefined;
        lightMotion = undefined;
        compactShape = undefined;
        if (!field) {
          running.get(element)?.cancel();
          element.style.removeProperty("transform");
          if (pressSurface) {
            running.get(surface!)?.cancel();
            surface?.style.removeProperty("transform");
          }
        }
      }
      update();
    };
    element.addEventListener("pointerenter", enter);
    element.addEventListener("pointermove", move);
    element.addEventListener("pointerleave", leave);
    element.addEventListener("pointerdown", down);
    element.addEventListener("pointerup", restore);
    element.addEventListener("pointercancel", leave);
    element.addEventListener("focusin", focus);
    element.addEventListener("focusout", blur);
    element.addEventListener("keydown", keydown);
    element.addEventListener("keyup", keyup);
    window.addEventListener("resize", invalidateBounds);
    window.addEventListener("scroll", invalidateBounds, true);
    media?.addEventListener("change", motionPreference);
    update();
    return () => {
      element.removeEventListener("pointerenter", enter);
      element.removeEventListener("pointermove", move);
      element.removeEventListener("pointerleave", leave);
      element.removeEventListener("pointerdown", down);
      element.removeEventListener("pointerup", restore);
      element.removeEventListener("pointercancel", leave);
      element.removeEventListener("focusin", focus);
      element.removeEventListener("focusout", blur);
      element.removeEventListener("keydown", keydown);
      element.removeEventListener("keyup", keyup);
      window.removeEventListener("resize", invalidateBounds);
      window.removeEventListener("scroll", invalidateBounds, true);
      media?.removeEventListener("change", motionPreference);
      cancelAnimationFrame(frame);
      faceMotion?.revert();
      lightMotion?.revert();
      running.forEach((animation) => animation.cancel());
      element.style.removeProperty("transform");
      light?.style.removeProperty("opacity");
      rim?.style.removeProperty("opacity");
      if (quiet) surface?.style.removeProperty("opacity");
      if (pressSurface) surface?.style.removeProperty("transform");
    };
  }, [ref, field, disabled, pinned, seed, quiet, pressSurface, pressScale]);
}
