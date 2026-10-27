import { useLayoutEffect, useRef } from "react";
import { animate, prefersReducedMotion } from "../animations/core";
import { formatTokens } from "./expenses";

export function ExpenseNumber({ value, format = formatTokens }: { value: number; format?: (value: number) => string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const previous = useRef(value);
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    const from = previous.current;
    previous.current = value;
    if (prefersReducedMotion() || from === value) { node.textContent = format(value); return; }
    const state = { value: from };
    const motion = animate(state, { value, duration: 540, ease: "outCubic",
      onUpdate: () => { node.textContent = format(state.value); },
      onComplete: () => { node.textContent = format(value); } });
    return () => { motion.cancel(); };
  }, [value, format]);
  return <><span ref={ref} aria-hidden="true">{format(value)}</span><span className="expense-sr-only">{format(value)}</span></>;
}
