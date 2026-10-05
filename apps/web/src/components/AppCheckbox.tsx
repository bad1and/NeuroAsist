import { SelectionMaterial } from "./SelectionMaterial";
import { useLayoutEffect, useRef, type ComponentPropsWithoutRef } from "react";
import { animate, prefersReducedMotion } from "../animations/core";
import "./SelectionControls.css";

type Props = Omit<ComponentPropsWithoutRef<"input">, "type">;

/** Native checkbox semantics with a quiet recessed face and animated check. */
export function AppCheckbox({ checked, className = "", ...props }: Props) {
  const mark = useRef<SVGSVGElement>(null);
  const mounted = useRef(false);
  useLayoutEffect(() => {
    const target = mark.current;
    if (!target) return;
    const duration = mounted.current && !prefersReducedMotion() ? 150 : 0;
    mounted.current = true;
    const animation = animate(target, { opacity: checked ? 1 : 0, scale: checked ? 1 : .75, duration, ease: "outQuad" });
    return () => { animation.cancel(); };
  }, [checked]);
  return <span className="iris-checkbox">
    <input {...props} type="checkbox" checked={checked} className={`iris-checkbox-input ${className}`} />
    <span className="iris-checkbox-face" aria-hidden="true">
      <SelectionMaterial tone={checked ? "accent" : "graphite"} />
      <svg ref={mark} viewBox="0 0 18 18"><path d="m4.5 9 3 3 6-6" /></svg>
    </span>
  </span>;
}
