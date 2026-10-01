import { type ReactNode, type RefObject, useCallback, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { animateNotification, runSafeAnimation, type Animation } from "../animations";

/** Move the same subtitle tree between the chat and shell without restarting its timers. */
export function ConversationSurface({
  active,
  backgroundVisible,
  backgroundHost,
  children,
}: {
  active: boolean;
  backgroundVisible: boolean;
  backgroundHost?: RefObject<HTMLDivElement | null>;
  children: ReactNode | ((inBackground: boolean, minimized: boolean, toggleMinimized: () => void) => ReactNode);
}) {
  const slotRef = useRef<HTMLDivElement>(null);
  const [surface] = useState(() => document.createElement("div"));
  const [inBackground, setInBackground] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const sizeBeforeToggle = useRef<{ width: number; height: number } | null>(null);
  const toggleMinimized = useCallback(() => {
    sizeBeforeToggle.current = surface.getBoundingClientRect();
    setMinimized((value) => !value);
  }, [surface]);

  useLayoutEffect(() => {
    const show = !active && backgroundVisible && Boolean(backgroundHost);
    let cancelled = false;
    let motion: Animation | null = null;
    const moveToChat = () => {
      if (cancelled) return;
      surface.className = "conversation-surface";
      surface.style.removeProperty("opacity");
      surface.style.removeProperty("transform");
      surface.style.removeProperty("width");
      surface.style.removeProperty("height");
      surface.inert = false;
      if (slotRef.current) slotRef.current.appendChild(surface);
      setInBackground(false);
    };
    const update = () => {
      if (cancelled) return;
      if (show && backgroundHost?.current) {
        surface.inert = false;
        surface.className = "notification-card conversation-surface is-background";
        backgroundHost.current.appendChild(surface);
        setInBackground(true);
        motion = animateNotification(surface, "enter");
      } else {
        // Keep compact subtitles until exit completes. A reversal cancels the old move.
        if (surface.classList.contains("is-background")) {
          surface.inert = true;
          motion = animateNotification(surface, "exit", moveToChat);
        }
        if (!motion) moveToChat();
      }
    };
    // A notification host rendered later in the same commit attaches its ref after
    // this layout effect. Wait for that commit without requiring another navigation.
    if (show && !backgroundHost?.current) queueMicrotask(update);
    else update();
    return () => { cancelled = true; motion?.cancel(); };
  }, [active, backgroundVisible, backgroundHost, surface]);

  useLayoutEffect(() => {
    surface.classList.toggle("is-minimized", inBackground && minimized);
    surface.style.removeProperty("width");
    surface.style.removeProperty("height");
    const before = sizeBeforeToggle.current;
    sizeBeforeToggle.current = null;
    if (!inBackground || !before) return;
    const after = surface.getBoundingClientRect();
    let cancelled = false;
    const motion = runSafeAnimation(surface, {
      width: [before.width, after.width],
      height: [before.height, after.height],
      duration: 220,
      ease: "outCubic",
      onComplete: () => {
        if (cancelled) return;
        surface.style.removeProperty("width");
        surface.style.removeProperty("height");
      },
    });
    return () => { cancelled = true; motion?.cancel(); };
  }, [minimized, inBackground, surface]);

  useLayoutEffect(() => () => surface.remove(), [surface]);

  return <><div ref={slotRef} className="conversation-subtitle-slot" />{createPortal(typeof children === "function" ? children(inBackground, minimized, toggleMinimized) : children, surface)}</>;
}
