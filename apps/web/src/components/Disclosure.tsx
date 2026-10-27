import { forwardRef, useId, useLayoutEffect, useRef, useState, type ComponentPropsWithoutRef, type ReactNode } from "react";
import { IconInterfaceChevronDown as ChevronDown } from "../CustomIcons";
import { animate, isTestEnvironment, prefersReducedMotion } from "../animations/core";
import { MaterialButton } from "./MaterialButton";
import "./Disclosure.css";

type TriggerProps = Omit<ComponentPropsWithoutRef<"button">, "aria-expanded"> & { materialKey: string; open: boolean };

/** Shared inline disclosure control; the open section keeps its graphite face. */
export const DisclosureTrigger = forwardRef<HTMLButtonElement, TriggerProps>(function DisclosureTrigger({
  open, materialKey, className = "", children, ...props
}, ref) {
  const arrowRef = useRef<SVGSVGElement>(null);
  const previousOpen = useRef(open);
  useLayoutEffect(() => {
    const arrow = arrowRef.current;
    if (!arrow) return;
    const settle = () => { arrow.style.transform = `rotate(${open ? 180 : 0}deg)`; };
    const changed = previousOpen.current !== open;
    previousOpen.current = open;
    if (!changed || prefersReducedMotion()) { settle(); return; }
    const motion = animate(arrow, { rotate: open ? 180 : 0, duration: 160, ease: "outCubic" });
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const preference = () => { motion.cancel(); settle(); };
    media?.addEventListener("change", preference);
    return () => { motion.cancel(); media?.removeEventListener("change", preference); };
  }, [open]);
  return <MaterialButton {...props} ref={ref} materialKey={materialKey} type={props.type ?? "button"}
    appearance={open ? "lens" : "quiet"} tone="graphite" aria-expanded={open}
    className={`iris-disclosure-trigger ${className}`}>
    <span className="iris-disclosure-label">{children}</span>
    <ChevronDown ref={arrowRef} size={20} className="iris-disclosure-chevron" aria-hidden="true" />
  </MaterialButton>;
});

export function DisclosurePanel({ open, id, labelledBy, regionLabel, contentClassName = "", children }:
  { open: boolean; id: string; labelledBy: string; regionLabel?: string; contentClassName?: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const initial = useRef(true);
  const previous = useRef(open);
  useLayoutEffect(() => {
    const panel = ref.current;
    if (!panel) return;
    let active = true;
    const clear = () => {
      panel.style.removeProperty("height"); panel.style.removeProperty("overflow"); panel.style.removeProperty("opacity");
      delete panel.dataset.disclosureAnimating;
    };
    const settle = () => { if (active) { panel.hidden = !open; clear(); } };
    if (!open && panel.contains(document.activeElement)) document.getElementById(labelledBy)?.focus();
    if (initial.current || isTestEnvironment() || prefersReducedMotion()) {
      initial.current = false; previous.current = open; settle(); return;
    }
    panel.hidden = false;
    const from = panel.style.height || previous.current ? panel.getBoundingClientRect().height : 0;
    previous.current = open;
    const body = panel.firstElementChild as HTMLElement;
    const style = getComputedStyle(body);
    const to = open ? body.offsetHeight + (parseFloat(style.marginTop) || 0) + (parseFloat(style.marginBottom) || 0) : 0;
    panel.style.overflow = "hidden";
    panel.style.height = `${from}px`;
    panel.dataset.disclosureAnimating = "true";
    const motion = animate(panel, { height: to, opacity: open ? 1 : 0, duration: open ? 180 : 150, ease: "outCubic", onComplete: settle });
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const preference = () => { motion.cancel(); settle(); };
    media?.addEventListener("change", preference);
    return () => { active = false; motion.cancel(); media?.removeEventListener("change", preference); };
  }, [open, labelledBy]);
  useLayoutEffect(() => () => {
    initial.current = true;
    ref.current?.style.removeProperty("height");
    ref.current?.style.removeProperty("overflow");
    ref.current?.style.removeProperty("opacity");
    if (ref.current) delete ref.current.dataset.disclosureAnimating;
  }, []);
  return <div ref={ref} id={id} className="iris-disclosure-panel" hidden={!open} inert={!open || undefined}
    aria-hidden={!open || undefined} role={regionLabel ? "region" : undefined}
    aria-label={regionLabel} aria-labelledby={regionLabel ? undefined : labelledBy}>
    <div className={`iris-disclosure-content ${contentClassName}`}>{children}</div>
  </div>;
}

type DisclosureProps = Omit<ComponentPropsWithoutRef<"div">, "children"> & {
  materialKey: string; label: ReactNode; children: ReactNode; open?: boolean; defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void; actions?: ReactNode; contentClassName?: string;
  triggerClassName?: string; contentId?: string; regionLabel?: string;
};

/** Default for inline expandable content; fields stay mounted while collapsed. */
export const Disclosure = forwardRef<HTMLDivElement, DisclosureProps>(function Disclosure({
  materialKey, label, children, open, defaultOpen = false, onOpenChange, actions,
  className = "", contentClassName, triggerClassName, contentId, regionLabel, ...props
}, ref) {
  const generatedId = useId();
  const panelId = contentId ?? generatedId;
  const triggerId = `${panelId}-trigger`;
  const [localOpen, setLocalOpen] = useState(defaultOpen);
  const expanded = open ?? localOpen;
  return <div {...props} ref={ref} className={`iris-disclosure ${className}`} data-expanded={expanded}>
    <div className="iris-disclosure-header">
      <DisclosureTrigger materialKey={materialKey} open={expanded} id={triggerId} className={triggerClassName}
        aria-controls={panelId} onClick={() => {
          if (open === undefined) setLocalOpen(!expanded);
          onOpenChange?.(!expanded);
        }}>{label}</DisclosureTrigger>
      {actions && <div className="iris-disclosure-actions">{actions}</div>}
    </div>
    <DisclosurePanel id={panelId} open={expanded} labelledBy={triggerId} regionLabel={regionLabel} contentClassName={contentClassName}>
      {children}
    </DisclosurePanel>
  </div>;
});
