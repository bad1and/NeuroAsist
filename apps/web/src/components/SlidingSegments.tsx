import { SelectionMaterial } from "./SelectionMaterial";
import { useLayoutEffect, useRef, type ComponentPropsWithoutRef } from "react";
import { animate, prefersReducedMotion, type Animation } from "../animations/core";
import "./SelectionControls.css";

/** A single moving face shared by the native buttons in a selection group. */
export function SlidingSegments({ value, children, className = "", role = "group", ...props }:
  ComponentPropsWithoutRef<"div"> & { value: string | boolean }) {
  const track = useRef<HTMLDivElement>(null);
  const face = useRef<HTMLSpanElement>(null);
  const ready = useRef(false);
  const lastGeometry = useRef("");
  const running = useRef<Animation | null>(null);
  const remeasure = useRef<() => void>(() => {});
  useLayoutEffect(() => {
    const root = track.current;
    const indicator = face.current;
    if (!root || !indicator) return;
    const measure = (move: boolean) => {
      const selected = root.querySelector<HTMLButtonElement>("button.is-active, button.active, button[aria-pressed='true'], button[aria-selected='true']");
      if (!selected) { indicator.style.opacity = "0"; ready.current = false; return; }
      const bounds = selected.getBoundingClientRect();
      const origin = root.getBoundingClientRect();
      const geometry = { x: bounds.left - origin.left + root.scrollLeft - root.clientLeft,
        y: bounds.top - origin.top + root.scrollTop - root.clientTop, width: bounds.width, height: bounds.height };
      const signature = JSON.stringify(geometry);
      if (ready.current && lastGeometry.current === signature) return;
      lastGeometry.current = signature;
      running.current?.cancel();
      indicator.style.opacity = "1";
      if (!ready.current || !move || prefersReducedMotion()) {
        indicator.style.transform = `translateX(${geometry.x}px) translateY(${geometry.y}px)`;
        indicator.style.width = `${geometry.width}px`;
        indicator.style.height = `${geometry.height}px`;
      } else {
        running.current = animate(indicator, { ...geometry, duration: 240, ease: "outCubic" });
      }
      ready.current = true;
    };
    remeasure.current = () => measure(false);
    measure(true);
  }, [value, children]);
  useLayoutEffect(() => {
    const root = track.current;
    const observer = root && typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(() => remeasure.current()) : null;
    if (root) {
      observer?.observe(root);
      root.querySelectorAll("button").forEach(button => observer?.observe(button));
    }
    return () => { observer?.disconnect(); running.current?.cancel(); };
  }, []);
  return <div {...props} role={role} ref={track} className={`iris-segments ${className}`}
    onKeyDown={event => {
      props.onKeyDown?.(event);
      if (event.defaultPrevented || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      const buttons = Array.from(track.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);
      const index = buttons.indexOf(event.target as HTMLButtonElement);
      if (index < 0 || !buttons.length) return;
      event.preventDefault();
      const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1
        : (index + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next].focus();
      buttons[next].click();
    }}>
    <span className="iris-segments-face" ref={face} aria-hidden="true"><SelectionMaterial /></span>
    {children}
  </div>;
}
