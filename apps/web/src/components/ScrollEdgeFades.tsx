import { useLayoutEffect } from "react";
import { observeScrollEdgeFade } from "./useScrollEdgeFade";

// Actual content viewports, including body portals and responsive workspaces.
// Keep shells and editable controls out: their material/focus must stay intact.
export const scrollEdgeFadeSelector = [
  ".workspace", ".app-shell > .sidebar", ".message-list", ".search-results",
  ".history-list", ".journal-messages-container", ".avatar-dev-content-pane",
  ".settings-navigation-scroll", ".settings-content", ".setup-page", ".changelog-article",
  ".state-sidebar-panels", ".state-timeline-scroll", ".mood-causes ul",
  ".custom-select-dropdown", ".desktop-avatar-popover-body", ".expense-breakdown-legend",
  ".notification-stack", ".notification-details", ".spotlight-results-area",
  ".first-conversation-setup", ".document-attachment-details", ".document-source-text",
  ".memory-context-details", ".token-dialog-body", ".token-json-viewer",
  ".event-list", ".coding-events-list", ".inspect-pre",
  // Includes inline preparation logs as well as lazy-loaded diagnostic JSON.
  "pre",
  ".startup-content",
].join(", ");

export function installScrollEdgeFades(root: HTMLElement) {
  const attached = new Map<HTMLElement, () => void>();
  let frame: number | undefined;
  const refresh = () => {
    frame = undefined;
    const current = new Set(root.querySelectorAll<HTMLElement>(scrollEdgeFadeSelector));
    if (root.matches(scrollEdgeFadeSelector)) current.add(root);
    for (const [viewport, dispose] of attached) {
      if (!current.has(viewport)) { dispose(); attached.delete(viewport); }
    }
    for (const viewport of current) {
      if (!attached.has(viewport)) attached.set(viewport, observeScrollEdgeFade(viewport));
    }
  };
  const mutations = new MutationObserver(records => {
    // Hover/material class changes inside a row do not require rediscovery.
    if (records.some(record => record.type === "childList" ||
      (record.target instanceof HTMLElement && (attached.has(record.target) || record.target.matches(scrollEdgeFadeSelector))))) {
      frame ??= requestAnimationFrame(refresh);
    }
  });
  mutations.observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ["class"] });
  refresh();
  return () => {
    mutations.disconnect();
    if (frame !== undefined) cancelAnimationFrame(frame);
    for (const dispose of attached.values()) dispose();
    attached.clear();
  };
}

/** Covers route changes and dialogs portalled outside the application root. */
export function ScrollEdgeFades() {
  useLayoutEffect(() => installScrollEdgeFades(document.body), []);
  return null;
}
