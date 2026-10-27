import { useLayoutEffect, useRef, type ReactNode } from "react";
import { animate, isTestEnvironment, prefersReducedMotion } from "../animations/core";

/** Animate the real panel height so following content stays in the same layout. */
export function NavigationDisclosure({ open, id, children, contentClassName = "settings-nav-children" }:
  { open: boolean; id: string; children: ReactNode; contentClassName?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const initial = useRef(true);
  const previous = useRef(open);
  useLayoutEffect(() => {
    const panel = ref.current;
    if (!panel) return;
    const icon = panel.parentElement?.querySelector<SVGElement>(".settings-nav-chevron");
    const clear = () => {
      panel.style.removeProperty("height");
      panel.style.removeProperty("overflow");
      panel.style.removeProperty("opacity");
    };
    let active = true;
    const settle = () => {
      if (!active) return;
      panel.hidden = !open;
      clear();
      if (icon) icon.style.transform = `rotate(${open ? 180 : 0}deg)`;
    };
    if (initial.current || isTestEnvironment() || prefersReducedMotion()) {
      initial.current = false;
      previous.current = open;
      settle();
      return;
    }
    // React may have applied hidden for closing; restore it before reading height.
    panel.hidden = false;
    const from = (panel.style.height || previous.current) ? panel.getBoundingClientRect().height : 0;
    previous.current = open;
    const body = panel.firstElementChild as HTMLElement;
    const style = getComputedStyle(body);
    const to = open ? body.offsetHeight + (parseFloat(style.marginTop) || 0) + (parseFloat(style.marginBottom) || 0) : 0;
    panel.style.overflow = "hidden";
    panel.style.height = `${from}px`;
    // A short, bounded layout animation keeps the card background attached to its rows.
    // Scaling or translating the rows independently lets them escape that background.
    const motion = animate(panel, {
      height: to, opacity: open ? 1 : 0,
      duration: open ? 180 : 150, ease: "outCubic", onComplete: settle,
    });
    const arrow = icon ? animate(icon, { rotate: open ? 180 : 0, duration: 160, ease: "outCubic" }) : null;
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const preference = () => { motion.cancel(); arrow?.cancel(); settle(); };
    media?.addEventListener("change", preference);
    return () => { active = false; motion.cancel(); arrow?.cancel(); media?.removeEventListener("change", preference); };
  }, [open]);
  useLayoutEffect(() => () => {
    initial.current = true;
    const panel = ref.current;
    panel?.style.removeProperty("height");
    panel?.style.removeProperty("overflow");
    panel?.style.removeProperty("opacity");
  }, []);
  return <div ref={ref} id={id} className="settings-nav-disclosure" hidden={!open} inert={!open || undefined} aria-hidden={!open || undefined}>
    <div className={contentClassName}>{children}</div>
  </div>;
}
