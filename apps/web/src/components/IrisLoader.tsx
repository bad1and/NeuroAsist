import { animate, stagger, prefersReducedMotion, useAnimeScope } from "../animations";
import { IrisPetals } from "./IrisPetals";

export type IrisLoaderSize = "compact" | "standard" | "hero";

export function IrisLoader({ active = true, className = "", label, size = "standard" }: {
  active?: boolean;
  className?: string;
  label?: string;
  size?: IrisLoaderSize;
}) {
  const ref = useAnimeScope<HTMLDivElement>((_, root) => {
    if (!active || prefersReducedMotion()) return;
    animate(root.querySelectorAll("[data-petal]"), {
      opacity: [0.55, 1, 0.55], scaleY: [0.96, 1, 0.96],
      duration: 2800, delay: stagger(180), loop: true, ease: "inOutSine",
    });
  }, [active]);
  return (
    <div ref={ref} className={["iris-loader", `iris-loader-${size}`, className].filter(Boolean).join(" ")}
      role={label ? "status" : undefined} aria-live={label ? "polite" : undefined}
      aria-label={label} aria-hidden={label ? undefined : true}>
      <div className="iris-loader-media"><IrisPetals /></div>
    </div>
  );
}
