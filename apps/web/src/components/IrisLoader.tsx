import { useEffect, useRef } from "react";
import type { AnimationItem } from "lottie-web";

const lottiePlayer =
  import.meta.env.MODE === "test"
    ? null
    : import("lottie-web/build/player/lottie_light").then(({ default: lottie }) => lottie);
const animationDataPromise = import("../brand/iris-loader.json").then(({ default: animationData }) => animationData);

export type IrisLoaderSize = "compact" | "standard" | "hero";

export function IrisLoader({
  active = true,
  className = "",
  label,
  size = "standard",
}: {
  active?: boolean;
  className?: string;
  label?: string;
  size?: IrisLoaderSize;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const animationRef = useRef<AnimationItem | null>(null);
  const activeRef = useRef(active);

  useEffect(() => {
    activeRef.current = active;
    const animation = animationRef.current;
    if (!animation) return;
    if (active) {
      animation.play();
    } else {
      animation.goToAndStop(0, true);
    }
  }, [active]);

  useEffect(() => {
    const container = containerRef.current;
    if (
      !container ||
      typeof window.requestAnimationFrame !== "function"
    ) {
      return;
    }

    let animation: AnimationItem | null = null;
    let disposed = false;
    let readyFrame = 0;

    const handleReady = () => {
      if (animation && !activeRef.current) {
        animation.goToAndStop(0, true);
      }
    };

    void Promise.all([lottiePlayer, animationDataPromise]).then(([lottie, animationData]) => {
      if (disposed) return;
      if (!lottie) return;
      animation = lottie.loadAnimation({
        container,
        renderer: "svg",
        loop: true,
        autoplay: activeRef.current,
        animationData,
        rendererSettings: {
          preserveAspectRatio: "xMidYMid meet",
          progressiveLoad: false,
        },
      });
      animation.addEventListener("DOMLoaded", handleReady);
      animationRef.current = animation;

      // Lottie can finish parsing an inline animation before the listener is
      // attached. Make the rendered SVG visible on the next frame as well.
      readyFrame = window.requestAnimationFrame(handleReady);
    });

    return () => {
      disposed = true;
      window.cancelAnimationFrame(readyFrame);
      animation?.removeEventListener("DOMLoaded", handleReady);
      animation?.destroy();
      animationRef.current = null;
    };
  }, []);

  const classes = [
    "iris-loader",
    `iris-loader-${size}`,
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className={classes}
      role={label ? "status" : undefined}
      aria-live={label ? "polite" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <div className="iris-loader-media">
        <span className="iris-loader-fallback" aria-hidden="true" />
        <div ref={containerRef} className="iris-loader-canvas" aria-hidden="true" />
      </div>
    </div>
  );
}
