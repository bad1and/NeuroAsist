import { useEffect, useRef, useState } from "react";
import { animate, isTestEnvironment, type Animation } from "../animations";
import "./ChatWelcomeScenery.css";

const floraAssets = Promise.all([
  import("../../../../assets/startup-flora-left.webp"),
  import("../../../../assets/startup-flora-right.webp"),
]);

/** Transparent scenery stays behind the separately hosted Unity portrait. */
export function ChatWelcomeScenery({ active }: { active: boolean }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [flora, setFlora] = useState<string[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    void floraAssets.then(assets => {
      if (!cancelled) setFlora(assets.map(asset => asset.default));
    }).catch(() => { /* The portal and start action remain usable without decoration. */ });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || !flora || isTestEnvironment()) return;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let animations: Animation[] = [];
    const sync = () => {
      animations.forEach(animation => animation.revert());
      animations = [];
      if (!active || document.hidden || motion.matches) return;
      root.querySelectorAll<HTMLImageElement>("img").forEach((plant, index) => {
        const sign = index === 0 ? 1 : -1;
        animations.push(animate(plant, {
          rotate: [0, sign * 0.7, 0],
          translateX: [0, sign * 3, 0],
          duration: index === 0 ? 16000 : 19000,
          ease: "inOutSine",
          loop: true,
        }));
      });
    };
    sync();
    document.addEventListener("visibilitychange", sync);
    motion.addEventListener("change", sync);
    return () => {
      document.removeEventListener("visibilitychange", sync);
      motion.removeEventListener("change", sync);
      animations.forEach(animation => animation.revert());
    };
  }, [active, flora]);

  return <div ref={rootRef} className="chat-welcome-scenery" aria-hidden="true">
    <div className="chat-welcome-depth" />
    <div className="chat-welcome-flora chat-welcome-flora-left">
      {flora && <img src={flora[0]} alt="" draggable={false} />}
    </div>
    <div className="chat-welcome-flora chat-welcome-flora-right">
      {flora && <img src={flora[1]} alt="" draggable={false} />}
    </div>
    <div className="chat-welcome-ground" />
  </div>;
}
