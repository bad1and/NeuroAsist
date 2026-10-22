import { useEffect } from "react";
import { requestJson } from "../api";
import { isDesktopApp } from "../desktop";

let lastPresentationRevision = 0;

/** Presentation is transient window state, independent of emotions and body actions. */
export function useAvatarPresentation(seated: boolean, enabled: boolean, rendererPhase?: string) {
  useEffect(() => {
    if (!enabled || !isDesktopApp()) return;
    lastPresentationRevision = Math.max(lastPresentationRevision + 1, Date.now() * 1000);
    void requestJson("/avatar/presentation", {
      method: "POST",
      body: JSON.stringify({ mode: seated ? "welcome_seated" : "portrait", revision: lastPresentationRevision }),
    }).catch(error => console.warn("Avatar presentation could not be updated", error));
  }, [seated, enabled, rendererPhase]);
}
