import { useLayoutEffect, useRef, type KeyboardEvent } from "react";
import { IconInterfaceSliders as Sliders } from "../CustomIcons";
import { createTimeline, isTestEnvironment, prefersReducedMotion, stagger, type Timeline } from "../animations/core";
import { ButtonMaterialLayers, MaterialButton } from "./MaterialButton";
import { buttonSeed, materialStyle } from "./buttonMaterial";

type Step = { label: string; short: string; hint: string };
const faceStyle = materialStyle(buttonSeed("setup.stage-selection"), .35);

/** A moving material face and expanding slots share one continuous geometry. */
export function SetupStepNavigation({ steps, step, onSelect }: {
  steps: readonly Step[]; step: number; onSelect: (step: number) => void;
}) {
  const railRef = useRef<HTMLElement>(null);
  const faceRef = useRef<HTMLDivElement>(null);
  const first = useRef(true);
  useLayoutEffect(() => () => { first.current = true; }, []);
  useLayoutEffect(() => {
    const rail = railRef.current, face = faceRef.current;
    if (!rail || !face) return;
    const slots = [...rail.querySelectorAll<HTMLElement>(".setup-stage-slot")];
    const copies = [...rail.querySelectorAll<HTMLElement>(".setup-stage-copy")];
    let motion: Timeline | undefined;
    let frame: number | undefined;
    let lastWidth = 0;
    let active = true;
    const layout = (entrance: boolean, snap = false) => {
      const width = rail.clientWidth;
      if (!width) return;
      lastWidth = width;
      motion?.cancel();
      const gap = parseFloat(getComputedStyle(rail).columnGap) || 0;
      const available = width - gap * (slots.length - 1);
      const compact = Math.max(44, (available - Math.min(300, available * .46)) / (slots.length - 1));
      const expanded = available - compact * (slots.length - 1);
      const widths = slots.map((_, index) => index === step ? expanded : compact);
      const x = widths.slice(0, step).reduce((sum, value) => sum + value + gap, 0);
      const settle = () => {
        slots.forEach((slot, index) => {
          slot.style.width = `${widths[index]}px`;
          slot.style.opacity = "1";
          slot.style.transform = "translateX(0px)";
        });
        copies.forEach((copy, index) => {
          copy.style.opacity = index === step ? "1" : "0";
          copy.style.transform = "translateX(0px)";
          copy.style.clipPath = index === step ? "inset(0% 0% 0% 0%)" : "inset(0% 100% 0% 0%)";
        });
        face.style.width = `${expanded}px`;
        face.style.transform = `translateX(${x}px)`;
        face.style.opacity = "1";
        rail.dataset.motion = "settled";
      };
      if (snap || isTestEnvironment() || prefersReducedMotion() || document.hidden) {
        settle(); return;
      }
      rail.dataset.motion = "moving";
      // Cancelling retains the current widths and face position for rapid input.
      // Only the newly selected copy restarts its reveal; text is never scaled.
      copies.forEach((copy, index) => { if (index !== step) copy.style.opacity = "0"; });
      if (entrance) {
        slots.forEach((slot, index) => { slot.style.width = `${widths[index]}px`; });
        face.style.width = `${Math.min(compact, expanded)}px`;
        face.style.transform = `translateX(${Math.max(0, x - 24)}px)`;
        face.style.opacity = "0";
      } else {
        slots.forEach(slot => { slot.style.opacity = "1"; slot.style.transform = "translateX(0px)"; });
      }
      motion = createTimeline({ onComplete: () => { if (active) settle(); } });
      slots.forEach((slot, index) => motion!.add(slot, { width: widths[index], duration: 520, ease: "outQuint" }, 0));
      if (entrance) motion.add(slots, { opacity: [0, 1], translateX: [-24, 0], duration: 380, delay: stagger(65), ease: "outCubic" }, 0);
      const arrival = entrance ? step * 65 : 0;
      motion.add(face, { translateX: x, opacity: 1, duration: 520, ease: "outQuint" }, arrival);
      if (entrance) motion.add(face, { width: expanded, duration: 520, ease: "outQuint" }, arrival);
      else {
        // Narrow while travelling, then unfold into the arriving stage's slot.
        motion.add(face, { width: Math.min(compact, expanded), duration: 130, ease: "inOutQuad" }, 0);
        motion.add(face, { width: expanded, duration: 390, ease: "outQuint" }, 130);
      }
      motion.add(copies[step], {
        opacity: [0, 1], translateX: [-18, 0], clipPath: ["inset(0% 100% 0% 0%)", "inset(0% 0% 0% 0%)"],
        duration: 340, ease: "outQuart",
      }, entrance ? 140 + step * 65 : 170);
    };
    layout(first.current);
    first.current = false;
    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => {
      if (Math.abs(rail.clientWidth - lastWidth) < 1) return;
      if (frame !== undefined) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => { frame = undefined; layout(false, true); });
    });
    resize?.observe(rail);
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const settlePreference = () => layout(false, true);
    media?.addEventListener("change", settlePreference);
    document.addEventListener("visibilitychange", settlePreference);
    return () => {
      active = false;
      motion?.cancel(); resize?.disconnect();
      if (frame !== undefined) cancelAnimationFrame(frame);
      media?.removeEventListener("change", settlePreference);
      document.removeEventListener("visibilitychange", settlePreference);
    };
  }, [step, steps]);
  const navigate = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const next = event.key === "ArrowRight" ? (index + 1) % steps.length
      : event.key === "ArrowLeft" ? (index + steps.length - 1) % steps.length
        : event.key === "Home" ? 0 : event.key === "End" ? steps.length - 1 : null;
    if (next === null) return;
    event.preventDefault(); onSelect(next);
    railRef.current?.querySelectorAll<HTMLButtonElement>(".setup-stage")[next]?.focus();
  };
  return <div className="setup-window-heading">
    <span className="setup-window-identity" aria-hidden="true"><Sliders size={20} /><span>Настроить Iris</span></span>
    <nav ref={railRef} className="setup-stage-rail" aria-label="Шаги первого запуска">
      <div ref={faceRef} className="setup-stage-face iris-button dp-lens dp-accent" style={faceStyle} aria-hidden="true"><ButtonMaterialLayers /></div>
      {steps.map((item, index) => <div className="setup-stage-slot" key={item.label}>
        <MaterialButton materialKey={`setup.step.${index}`} className="setup-stage" type="button" appearance="plain"
          aria-label={`${index + 1}. ${item.label}`} aria-current={step === index ? "step" : undefined}
          title={item.label} onClick={() => onSelect(index)} onKeyDown={event => navigate(event, index)}>
          <span className="setup-stage-number" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
          <span className="setup-stage-text" aria-hidden="true">
            <span className="setup-stage-short">{item.short}</span>
            <span className="setup-stage-copy"><span className="setup-stage-label">{item.label}</span><span className="setup-stage-mobile-label">{item.short}</span><span className="setup-stage-hint">{item.hint}</span></span>
          </span>
        </MaterialButton>
      </div>)}
    </nav>
  </div>;
}
