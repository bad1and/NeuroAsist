import { forwardRef, useCallback, useLayoutEffect, useRef, type ComponentPropsWithoutRef, type CSSProperties, type ReactNode } from "react";
import { buttonSeed, materialStyle } from "./buttonMaterial";
import { useMaterialFeedback } from "./useMaterialFeedback";

type Props = ComponentPropsWithoutRef<"button"> & {
  materialKey: string;
  seed?: number;
  tone?: "accent" | "graphite" | "danger" | "warning" | "success";
  appearance?: "lens" | "plain" | "quiet" | "joined";
};

function MaterialFace() {
  return <span className="dp-material">
    <span className="dp-inner-top" /><span className="dp-inner-bottom" />
    <span className="dp-inner-edge" /><span className="dp-bevel" />
    <span className="dp-bloom" /><span className="dp-noise" />
  </span>;
}

export function ButtonMaterialLayers({ children }: { children?: ReactNode } = {}) {
  return <>
    <span className="dp-hover-surface" aria-hidden="true">
      <span className="dp-depth" />
      <MaterialFace />{children}
      <span className="dp-hover-light"><span className="dp-hover-spot" /></span>
    </span>
    <span className="dp-rim" aria-hidden="true" />
  </>;
}

/** One continuous face for adjacent actions, with independent native hit targets. */
export function MaterialButtonGroup({ materialKey, muted = [false, false], className = "", style, children, ...props }:
  ComponentPropsWithoutRef<"div"> & { materialKey: string; muted?: readonly [boolean, boolean] }) {
  const ref = useRef<HTMLDivElement>(null);
  const seed = buttonSeed(materialKey);
  const bothMuted = muted[0] && muted[1];
  useMaterialFeedback(ref, { seed, pressSurface: true });
  return <div {...props} ref={ref} className={`${className} iris-button iris-button-group dp-lens dp-${bothMuted ? "danger" : "graphite"}`}
    data-material-seed={seed} data-material-contour="media"
    style={{ ...materialStyle(seed, .35), "--button-contour": "url(#iris-material-media)", ...style } as CSSProperties}>
    {children}<ButtonMaterialLayers>
      {!bothMuted && muted.map((value, side) => value && <span key={side} className="dp-joined-half dp-lens dp-danger" data-side={side}><MaterialFace /></span>)}
    </ButtonMaterialLayers>
  </div>;
}

const plainClasses = /\b(text-button|card-link|navigation-scrim|send-button|custom-select-trigger|search-clear-btn|token-badge|journal-header-tokens|notification-expand-link|coding-task-card|avatar-dev-card|journal-message-details-toggle)\b/;
const navigationClasses = /\b(navigation-button|settings-nav-button|settings-nav-direct|settings-nav-group-button|avatar-dev-subnav-btn)\b/;

/** Keeps the native button, its children, form semantics and forwarded DOM ref. */
export const MaterialButton = forwardRef<HTMLButtonElement, Props>(function MaterialButton({
  materialKey, seed, tone, appearance, className = "", style, children, disabled, ...props
}, forwardedRef) {
  const localRef = useRef<HTMLButtonElement>(null);
  const attach = useCallback((node: HTMLButtonElement | null) => {
    localRef.current = node;
    if (typeof forwardedRef === "function") forwardedRef(node);
    else if (forwardedRef) forwardedRef.current = node;
  }, [forwardedRef]);
  const active = /\b(is-active|active|is-primary)\b/.test(className);
  const mode = appearance ?? (plainClasses.test(className) ? "plain" : navigationClasses.test(className) && !active ? "quiet" : "lens");
  const materialTone = tone ?? (/\b(danger-button|is-danger|dock-finish-btn|avatar-dev-btn-danger)\b/.test(className) ? "danger"
    : active || /\b(primary-button|chat-start-button|avatar-dev-btn-primary)\b/.test(className) ? "accent" : "graphite");
  const resolvedSeed = seed ?? buttonSeed(materialKey);
  const contour = className.includes("chat-start-button") ? "start" : className.includes("dock-finish-btn") ? "finish"
    : className.includes("dock-new-dialog-btn") ? "new" : className.includes("dock-icon-btn") ? "square" : undefined;
  useMaterialFeedback(localRef, { disabled: disabled || mode === "plain" || mode === "joined", seed: resolvedSeed, quiet: mode === "quiet", pressSurface: true });

  useLayoutEffect(() => {
    const element = localRef.current;
    if (!element || mode === "plain") return;
    const originalPosition = element.style.position;
    if (getComputedStyle(element).position === "static") element.style.position = "relative";
    const measure = () => {
      const { width, height } = element.getBoundingClientRect();
      const computed = getComputedStyle(element);
      const squircle = computed.getPropertyValue("corner-shape").includes("squircle") || /\b(icon-button|dock-icon-btn)\b/.test(className);
      element.dataset.materialSquare = String(mode !== "joined" && width > 0 && Math.abs(width - height) < 1 && squircle);
      element.dataset.materialCompact = String(height <= 80 && width / height <= 3);
    };
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(element);
    return () => { observer?.disconnect(); element.style.position = originalPosition; };
  }, [mode, className]);

  return <button {...props} ref={attach} disabled={disabled}
    className={`${className} iris-button${mode === "plain" ? "" : ` dp-lens dp-${materialTone}`}`}
    data-material={mode} data-material-contour={contour} data-material-seed={mode === "plain" ? undefined : resolvedSeed}
    style={{ ...(mode === "plain" ? {} : materialStyle(resolvedSeed, .35)),
      ...(contour ? { "--button-contour": `url(#iris-material-${contour})` } as CSSProperties : {}), ...style }}>
    {children}{mode !== "plain" && mode !== "joined" && <ButtonMaterialLayers />}
  </button>;
});
