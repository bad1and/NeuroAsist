import { SelectionMaterial } from "./SelectionMaterial";
import { useLayoutEffect, useRef, type ReactNode } from "react";
import { animate, prefersReducedMotion } from "../animations/core";
import "./SelectionControls.css";

export interface AppSwitchProps {
  checked: boolean;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  className?: string;
  onChange: (checked: boolean) => void;
}

export function AppSwitch({
  checked,
  label,
  description,
  disabled,
  className = "",
  onChange,
}: AppSwitchProps) {
  const thumb = useRef<HTMLSpanElement>(null);
  const fill = useRef<HTMLSpanElement>(null);
  const mounted = useRef(false);
  useLayoutEffect(() => {
    if (!thumb.current || !fill.current) return;
    const duration = mounted.current && !prefersReducedMotion() ? 220 : 0;
    mounted.current = true;
    const slide = animate(thumb.current, { x: checked ? 18 : 0, duration, ease: "outCubic" });
    const tint = animate(fill.current, { opacity: checked ? 1 : 0, duration, ease: "outQuad" });
    return () => { slide.cancel(); tint.cancel(); };
  }, [checked]);
  return (
    <label className={`settings-switch-row ${className}${disabled ? " is-disabled" : ""}`.trim()}>
      <span className="settings-switch-copy">
        <strong>{label}</strong>
        {description && <small>{description}</small>}
      </span>
      <input
        className="settings-switch-input"
        type="checkbox"
        role="switch"
        aria-checked={checked}
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="settings-switch" aria-hidden="true">
        <span className="iris-switch-fill" ref={fill}><SelectionMaterial /></span>
        <span className="iris-switch-thumb" ref={thumb}><SelectionMaterial tone="thumb" /></span>
      </span>
    </label>
  );
}
