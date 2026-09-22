import { useLayoutEffect, useRef, useState } from "react";

import {
  isDesktopApp,
  listenForAvatarLayoutInvalidation,
  setAvatarInAppBounds,
  setAvatarInAppVisible,
  type AvatarHostStatus,
} from "../desktop";
import { IrisLoader } from "./IrisLoader";

let lastAvatarHostRevision = 0;

function nextAvatarHostRevision(): number {
  lastAvatarHostRevision = Math.max(lastAvatarHostRevision + 1, Date.now() * 1_000);
  return lastAvatarHostRevision;
}

/**
 * React owns only the geometry of the avatar slot. The actual renderer is a
 * separately supervised Unity D3D process whose HWND is an Iris-owned popup.
 */
export function InAppAvatarHost({
  status,
  onRetry,
}: {
  status?: AvatarHostStatus | null;
  onRetry?: () => Promise<void>;
} = {}) {
  const hostRef = useRef<HTMLElement | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  // Browser builds do not have a Unity supervisor. Keep their historical
  // empty/ready slot instead of inventing a native warmup that can never end.
  const phase = status?.phase ?? (isDesktopApp() ? "starting" : "ready");
  const loading = phase === "starting" || phase === "warming";
  const failed = phase === "failed" || phase === "not_configured" || phase === "disabled";

  const retry = async () => {
    if (!onRetry || retrying) return;
    setRetrying(true);
    setRetryError(null);
    try {
      await onRetry();
    } catch (error) {
      setRetryError(error instanceof Error ? error.message : "Не удалось перезапустить аватар");
    } finally {
      setRetrying(false);
    }
  };

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

  return (
    <aside ref={hostRef} className="in-app-avatar-stage" aria-label="Аватар Iris">
      {loading && (
        <div className="in-app-avatar-loader-fallback" role="status" aria-live="polite">
          <IrisLoader size="standard" active />
          <span className="in-app-avatar-loader-label">
            {phase === "warming" ? "Прогреваю 3D-аватар…" : "Запускаю 3D-аватар…"}
          </span>
        </div>
      )}
      {failed && (
        <div className="in-app-avatar-failure" role="alert">
          <strong>
            {phase === "disabled"
              ? "3D-аватар отключён"
              : phase === "not_configured"
                ? "3D-аватар не установлен"
                : "Не удалось загрузить 3D-аватар"}
          </strong>
          <span>{retryError ?? status?.error ?? "Unity не подтвердила готовность за отведённое время."}</span>
          {phase !== "disabled" && onRetry && (
            <button className="secondary" type="button" disabled={retrying} onClick={() => void retry()}>
              {retrying ? "Перезапускаю…" : "Повторить"}
            </button>
          )}
        </div>
      )}
    </aside>
  );
}
