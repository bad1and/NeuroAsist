import { useLayoutEffect, useRef } from "react";

import { listenForAvatarLayoutInvalidation, setAvatarInAppBounds, setAvatarInAppVisible } from "../desktop";

let lastAvatarHostRevision = 0;

function nextAvatarHostRevision(): number {
  lastAvatarHostRevision = Math.max(lastAvatarHostRevision + 1, Date.now() * 1_000);
  return lastAvatarHostRevision;
}

/**
 * React owns only the geometry of the avatar slot. The actual renderer is a
 * separately supervised Unity D3D process whose HWND is an Iris-owned popup.
 */
export function InAppAvatarHost() {
  const hostRef = useRef<HTMLElement | null>(null);

  useLayoutEffect(() => {
    const element = hostRef.current;
    if (!element) return undefined;

    let cancelled = false;
    let scheduledFrame: number | null = null;
    const syncBounds = () => {
      if (cancelled) return;
      const rect = element.getBoundingClientRect();
      if (rect.width < 2 || rect.height < 2) return;
      const scale = window.devicePixelRatio || 1;
      const revision = nextAvatarHostRevision();
      void setAvatarInAppBounds({
        x: Math.round(rect.left * scale),
        y: Math.round(rect.top * scale),
        width: Math.round(rect.width * scale),
        height: Math.round(rect.height * scale),
        revision,
      }).then(() => {
        if (!cancelled) return setAvatarInAppVisible(true, revision);
        return undefined;
      }).catch(() => {
        // Browser builds do not have a native host.
      });
    };

    const scheduleSync = () => {
      if (cancelled || scheduledFrame !== null) return;
      if (typeof window.requestAnimationFrame !== "function") {
        syncBounds();
        return;
      }
      scheduledFrame = window.requestAnimationFrame(() => {
        scheduledFrame = null;
        syncBounds();
      });
    };

    syncBounds();
    const retryTimers = [
      window.setTimeout(scheduleSync, 180),
      window.setTimeout(scheduleSync, 700),
    ];
    let stopLayoutInvalidation: (() => void) | undefined;
    void listenForAvatarLayoutInvalidation(scheduleSync).then((unlisten) => {
      if (cancelled) unlisten();
      else stopLayoutInvalidation = unlisten;
    });
    const observer = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(scheduleSync);
    observer?.observe(element);
    window.addEventListener("resize", scheduleSync);
    return () => {
      cancelled = true;
      observer?.disconnect();
      stopLayoutInvalidation?.();
      window.removeEventListener("resize", scheduleSync);
      if (scheduledFrame !== null && typeof window.cancelAnimationFrame === "function") {
        window.cancelAnimationFrame(scheduledFrame);
      }
      retryTimers.forEach((timer) => window.clearTimeout(timer));
      void setAvatarInAppVisible(false, nextAvatarHostRevision());
    };
  }, []);

  return <aside ref={hostRef} className="in-app-avatar-stage" aria-label="Аватар Iris" />;
}
