import { useLayoutEffect, useRef } from "react";

import { listenForAvatarLayoutInvalidation, setAvatarInAppBounds, setAvatarInAppVisible } from "../desktop";

// Date-based revisions survive a Vite hot reload, while the counter handles
// more than one layout update in the same millisecond. They stay below
// Number.MAX_SAFE_INTEGER for the foreseeable future.
let lastAvatarHostRevision = 0;

function nextAvatarHostRevision(): number {
  lastAvatarHostRevision = Math.max(lastAvatarHostRevision + 1, Date.now() * 1_000);
  return lastAvatarHostRevision;
}

/**
 * A DOM anchor for the native Unity surface. Unity is deliberately not
 * rendered by React: the Windows player is a D3D surface.  React owns only its
 * intended geometry and keeps it in sync with zoom, DPI, and responsive chat
 * layout changes.
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
        // An in-flight bounds call may finish after the user has left the
        // chat. Never allow that old promise to reveal the native popup.
        if (cancelled) return;
        return setAvatarInAppVisible(true, revision);
      }).catch(() => {
        // The standalone browser build deliberately has no native avatar host.
      });
    };

    // ResizeObserver can fire several times per native resize or window drag.
    // One update per animation frame keeps the D3D popup and the Tauri window
    // in lockstep without flooding the IPC bridge with SetWindowPos calls.
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
    // Unity finishes configuring its native popup shortly after the DOM host
    // mounts. Reapply the authoritative chat rectangle after that startup
    // window so a late Unity resize can never expand over the application.
    const retryTimers = [
      window.setTimeout(scheduleSync, 180),
      window.setTimeout(scheduleSync, 700),
    ];
    let stopLayoutInvalidation: (() => void) | undefined;
    void listenForAvatarLayoutInvalidation(scheduleSync).then((unlisten) => {
      if (cancelled) unlisten();
      else stopLayoutInvalidation = unlisten;
    });
    const observer = typeof ResizeObserver === "undefined"
      ? undefined
      : new ResizeObserver(scheduleSync);
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
