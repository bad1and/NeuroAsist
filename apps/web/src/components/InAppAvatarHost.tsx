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

    syncBounds();
    // Unity finishes configuring its native popup shortly after the DOM host
    // mounts. Reapply the authoritative chat rectangle after that startup
    // window so a late Unity resize can never expand over the application.
    const retryTimers = [
      window.setTimeout(syncBounds, 180),
      window.setTimeout(syncBounds, 700),
    ];
    let stopLayoutInvalidation: (() => void) | undefined;
    void listenForAvatarLayoutInvalidation(syncBounds).then((unlisten) => {
      if (cancelled) unlisten();
      else stopLayoutInvalidation = unlisten;
    });
    const observer = typeof ResizeObserver === "undefined"
      ? undefined
      : new ResizeObserver(syncBounds);
    observer?.observe(element);
    window.addEventListener("resize", syncBounds);
    return () => {
      cancelled = true;
      observer?.disconnect();
      stopLayoutInvalidation?.();
      window.removeEventListener("resize", syncBounds);
      retryTimers.forEach((timer) => window.clearTimeout(timer));
      void setAvatarInAppVisible(false, nextAvatarHostRevision());
    };
  }, []);

  return <aside ref={hostRef} className="in-app-avatar-stage" aria-label="Аватар Iris" />;
}
