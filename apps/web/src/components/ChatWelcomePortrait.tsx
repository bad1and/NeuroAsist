import { useEffect, useRef, useState } from "react";
import { createTimer, type Timer } from "animejs";
import { createWelcomePortraitRig, type WelcomePortraitRig } from "./welcome-portrait-rig";

export function ChatWelcomePortrait({ active }: { active: boolean }) {
  const imageRef = useRef<HTMLImageElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [animated, setAnimated] = useState(false);

  useEffect(() => {
    setAnimated(false);
    const image = imageRef.current;
    const canvas = canvasRef.current;
    if (!active || !image || !canvas || typeof window.matchMedia !== "function") return;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let rig: WelcomePortraitRig | null = null;
    let timer: Timer | null = null;
    let contextLost = false;
    const sync = () => {
      timer?.pause();
      if (motion.matches || contextLost) {
        setAnimated(false);
        return;
      }
      if (document.hidden || !image.complete || !image.naturalWidth) return;
      if (!rig) {
        rig = createWelcomePortraitRig(canvas, image);
        if (!rig) return; // Preserve the original PNG when WebGL is unavailable.
        rig.draw(0);
        timer = createTimer({
          duration: 120_000, loop: true, frameRate: 30, autoplay: false,
          onUpdate: clock => rig?.draw(clock.currentTime / 1000),
        });
      }
      setAnimated(true);
      timer?.resume();
    };
    const loseContext = (event: Event) => {
      event.preventDefault();
      contextLost = true;
      sync();
    };
    const restoreContext = () => {
      timer?.cancel();
      rig?.dispose();
      timer = null;
      rig = null;
      contextLost = false;
      sync();
    };
    sync();
    image.addEventListener("load", sync);
    document.addEventListener("visibilitychange", sync);
    motion.addEventListener("change", sync);
    canvas.addEventListener("webglcontextlost", loseContext);
    canvas.addEventListener("webglcontextrestored", restoreContext);
    return () => {
      image.removeEventListener("load", sync);
      document.removeEventListener("visibilitychange", sync);
      motion.removeEventListener("change", sync);
      canvas.removeEventListener("webglcontextlost", loseContext);
      canvas.removeEventListener("webglcontextrestored", restoreContext);
      timer?.cancel();
      rig?.dispose();
    };
  }, [active]);

  return <div className="chat-welcome-portrait" aria-hidden="true" data-animated={animated}>
    <img ref={imageRef} src="/brand/iris-welcome-seated.png" alt="" draggable={false} width={1024} height={1536} />
    <canvas ref={canvasRef} width={1024} height={1536} />
  </div>;
}
