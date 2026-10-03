import { useCallback, useEffect, useRef, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import {
  getDesktopWindowPreferences,
  isDesktopApp,
  listenForWindowPreferences,
  type DesktopWindowPreferences,
} from "./desktop";

export function useDesktopWindowPreferences() {
  const available = isDesktopApp() && getCurrentWindow().label !== "qa_studio";
  const [preferences, setPreferences] = useState<DesktopWindowPreferences | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [reload, setReload] = useState(0);
  const revision = useRef(0);
  const update = useCallback((next: DesktopWindowPreferences) => {
    revision.current += 1;
    setPreferences(next);
    setLoadError(false);
  }, []);

  useEffect(() => {
    if (!available) return;
    let disposed = false;
    let stop: (() => void) | undefined;
    void (async () => {
      try {
        stop = await listenForWindowPreferences((next) => {
          if (!disposed) update(next);
        });
        if (disposed) { stop(); return; }
        const readRevision = revision.current;
        const next = await getDesktopWindowPreferences();
        if (!disposed && readRevision === revision.current) update(next);
      } catch (error) {
        console.error("Could not load desktop window preferences", error);
        if (!disposed) setLoadError(true);
      }
    })();
    return () => { disposed = true; stop?.(); };
  }, [available, reload, update]);

  return { available, preferences, loadError, update, retry: () => setReload((value) => value + 1) };
}
