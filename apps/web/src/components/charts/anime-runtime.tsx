/**
 * Iris adaptation of the Bklit animation primitives. All runtime motion uses
 * Anime.js v4. Motion's declarations are used only to retain registry prop types.
 * This is a deliberately small adapter for the installed chart components.
 */
import React, { forwardRef, useEffect, useLayoutEffect, useRef, useState } from "react";
import { animate as anime, prefersReducedMotion } from "../../animations/core";
export type { Transition, Variants } from "motion/react";
import type { Transition } from "motion/react";

export class MotionValue<T> {
  private listeners = new Set<(value: T) => void>();
  private tween: ReturnType<typeof anime> | undefined;
  constructor(private value: T, private smooth = false) {}
  get() { return this.value; }
  jump(next: T) {
    this.tween?.cancel();
    this.value = next;
    this.listeners.forEach(listener => listener(next));
  }
  set(next: T) {
    this.tween?.cancel();
    if (!this.smooth || prefersReducedMotion() || typeof next !== "number" || typeof this.value !== "number") {
      this.jump(next);
      return;
    }
    const state = { value: this.value };
    this.tween = anime(state, { value: next, duration: 180, ease: "outCubic",
      onUpdate: () => {
        this.value = state.value;
        this.listeners.forEach(listener => listener(this.value));
      } });
  }
  on(_event: "change", listener: (value: T) => void) {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }
  destroy() { this.tween?.cancel(); this.listeners.clear(); }
}

export function useMotionValue<T>(initial: T) {
  const [value] = useState(() => new MotionValue(initial));
  useEffect(() => () => value.destroy(), [value]);
  return value;
}

export function useSpring(initial: number | MotionValue<number>, _options?: unknown) {
  const [value] = useState(() => new MotionValue(initial instanceof MotionValue ? initial.get() : initial, true));
  useLayoutEffect(() => {
    if (initial instanceof MotionValue) {
      value.jump(initial.get());
      return initial.on("change", next => value.set(next));
    }
  }, [initial, value]);
  useEffect(() => () => value.destroy(), [value]);
  return value;
}

export function useTransform<T, U>(input: MotionValue<T>, transform: (value: T) => U): MotionValue<U>;
export function useTransform<T, U>(input: MotionValue<T>[], transform: (values: T[]) => U): MotionValue<U>;
export function useTransform<T, U>(input: MotionValue<T> | MotionValue<T>[], transform: ((value: T) => U) | ((values: T[]) => U)) {
  const sources = Array.isArray(input) ? input : [input];
  const latest = useRef({ sources, transform, multiple: Array.isArray(input) });
  latest.current = { sources, transform, multiple: Array.isArray(input) };
  const compute = () => {
    const { sources: current, transform: mapper, multiple } = latest.current;
    return multiple ? (mapper as (values: T[]) => U)(current.map(source => source.get()))
      : (mapper as (value: T) => U)(current[0].get());
  };
  const [derived] = useState(() => new MotionValue(compute()));
  useLayoutEffect(() => {
    derived.jump(compute());
    const unsubscribes = sources.map(source => source.on("change", () => derived.jump(compute())));
    return () => unsubscribes.forEach(unsubscribe => unsubscribe());
  }, [...sources, derived, transform]);
  return derived;
}

export function useReducedMotion() {
  const [reduced, setReduced] = useState(prefersReducedMotion);
  useEffect(() => {
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const change = () => setReduced(prefersReducedMotion());
    media?.addEventListener("change", change);
    return () => media?.removeEventListener("change", change);
  }, []);
  return reduced;
}

type TweenOptions = Transition & { onUpdate?: (value: number) => void; onComplete?: () => void };
export function animate(source: number | MotionValue<number>, target: number, options: TweenOptions = {}) {
  const state = { value: source instanceof MotionValue ? source.get() : source };
  const update = () => { if (source instanceof MotionValue) source.jump(state.value); options.onUpdate?.(state.value); };
  if (prefersReducedMotion() || options.duration === 0) {
    state.value = target;
    update();
    options.onComplete?.();
    return { stop() {} };
  }
  const tween = anime(state, { value: target, duration: (options.duration ?? 0.65) * 1000,
    delay: (options.delay ?? 0) * 1000, loop: options.repeat === Infinity,
    ease: options.ease === "linear" ? "linear" : "outCubic",
    onUpdate: update, onComplete: () => options.onComplete?.() });
  return { stop: () => tween.cancel() };
}

// Registry motion.* props span both HTML and SVG. Resolve reactive values and
// animate a small object, then write to the native element without React frames.
type NativeProps = Record<string, any>;
const components = new Map<string, React.ComponentType<NativeProps>>();
function createAnimatedElement(tag: string) {
  return forwardRef<Element, NativeProps>(function AnimeChartElement(props, outerRef) {
    const { animate: destination, initial, exit: _exit, transition, variants, onAnimationComplete, onUpdate,
      whileHover: _hover, whileTap: _tap, layout: _layout, ...native } = props;
    const element = useRef<Element | null>(null);
    const state = useRef<NativeProps>({});
    const mounted = useRef(false);
    const latest = useRef({ onAnimationComplete, onUpdate });
    latest.current = { onAnimationComplete, onUpdate };
    const resolve = (value: any): any => value instanceof MotionValue ? value.get() : value;
    const target = typeof destination === "string" ? variants?.[destination] : destination;
    const start = typeof initial === "string" ? variants?.[initial] : initial;
    const write = (key: string, value: any, isStyle = false) => {
      const node = element.current;
      if (!node || value == null) return;
      state.current[key] = value;
      const svg = node instanceof SVGElement;
      if ((key === "x" || key === "y") && (isStyle || !svg || ["path", "g", "circle"].includes(tag)) || key === "scale") {
        const transform = `translate(${state.current.x ?? 0}${svg ? "" : "px"}, ${state.current.y ?? 0}${svg ? "" : "px"}) scale(${state.current.scale ?? 1})`;
        if (svg) node.setAttribute("transform", transform);
        else (node as HTMLElement).style.transform = transform;
      } else if (isStyle || ["opacity", "filter", "color", "backgroundColor"].includes(key)) {
        (node as HTMLElement).style[key as any] = typeof value === "number" && !["opacity", "zIndex", "scale"].includes(key) ? `${value}px` : String(value);
      } else node.setAttribute(key, String(value));
    };
    const subscriptions: { key: string; value: MotionValue<any>; style: boolean }[] = [];
    const domProps: NativeProps = {};
    for (const [key, value] of Object.entries(native)) {
      if (key === "style") {
        domProps.style = {};
        for (const [styleKey, styleValue] of Object.entries(value ?? {})) {
          if (styleValue instanceof MotionValue) subscriptions.push({ key: styleKey, value: styleValue, style: true });
          if (!["x", "y", "scale"].includes(styleKey)) domProps.style[styleKey] = resolve(styleValue);
        }
      } else {
        if (value instanceof MotionValue) subscriptions.push({ key, value, style: false });
        domProps[key] = resolve(value);
      }
    }
    useLayoutEffect(() => {
      const unsubscribes = subscriptions.map(subscription => {
        write(subscription.key, subscription.value.get(), subscription.style);
        return subscription.value.on("change", value => write(subscription.key, value, subscription.style));
      });
      return () => unsubscribes.forEach(unsubscribe => unsubscribe());
    });
    const signature = JSON.stringify(target ?? {});
    useLayoutEffect(() => {
      if (!target || !element.current) return;
      const values = Object.fromEntries(Object.entries(target).filter(([key]) => key !== "transition"));
      if (!mounted.current) {
        for (const [key, value] of Object.entries(values)) {
          state.current[key] = resolve(start?.[key] ?? native[key] ?? (key === "opacity" ? 1 : value));
          write(key, state.current[key]);
        }
      }
      mounted.current = true;
      if (prefersReducedMotion()) {
        Object.entries(values).forEach(([key, value]) => write(key, value));
        latest.current.onAnimationComplete?.();
        return;
      }
      const tween = anime(state.current, { ...values, duration: (transition?.duration ?? 0.24) * 1000,
        delay: (transition?.delay ?? 0) * 1000, ease: "outCubic",
        onUpdate: () => {
          Object.keys(values).forEach(key => write(key, state.current[key]));
          latest.current.onUpdate?.(state.current);
        }, onComplete: () => latest.current.onAnimationComplete?.() });
      return () => { tween.cancel(); };
    }, [signature]);
    domProps.ref = (node: Element | null) => {
      element.current = node;
      if (typeof outerRef === "function") outerRef(node);
      else if (outerRef) outerRef.current = node;
    };
    return React.createElement(tag, domProps);
  });
}
export const motion = new Proxy({} as Record<string, React.ComponentType<NativeProps>>, {
  get: (_target, tag: string) => {
    if (!components.has(tag)) components.set(tag, createAnimatedElement(tag));
    return components.get(tag);
  },
});

// Tooltip entrances animate through motion.div; removing a tooltip stays instant
// so pointer/keyboard changes never leave stale values over the chart.
export function AnimatePresence({ children }: { children?: React.ReactNode; initial?: boolean; mode?: string }) {
  return <>{children}</>;
}
