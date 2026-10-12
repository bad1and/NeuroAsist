import { useEffect } from "react";
import { waapi } from "animejs";
import { isTestEnvironment } from "./core";

/** Legacy indicators use the same Anime.js lifecycle as authored Iris controls. */
export function useIndicatorAnimations() {
  useEffect(() => {
    if (isTestEnvironment()) return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const spinning = new Map<HTMLElement | SVGElement, ReturnType<typeof waapi.animate>>();
    const entered = new WeakSet<Element>();
    let active = true;
    const spinSelector = ".spin, .is-spinning, .stt-capture-spinner";
    const fadeSelector = ".assistant-thinking, .chat-subtitle-status, .memory-action-menu > div, .token-popover-portal, .bklit-chart-tooltip, .avatar-dev-studio-window, .avatar-dev-statusbar";
    const update = () => {
      if (!active) return;
      for (const [element, motion] of spinning) {
        if (!element.isConnected || !element.matches(spinSelector) || element.closest("[hidden]") || document.hidden || media.matches) {
          motion.revert(); spinning.delete(element);
        }
      }
      if (document.hidden || media.matches) return;
      document.querySelectorAll<HTMLElement | SVGElement>(spinSelector).forEach(element => {
        if (!spinning.has(element) && !element.closest("[hidden]")) spinning.set(element, waapi.animate(element, { rotate: [0, 360], duration: 1000, ease: "linear", loop: true }));
      });
      document.querySelectorAll<HTMLElement | SVGElement>(fadeSelector).forEach(element => {
        if (!entered.has(element)) { entered.add(element); waapi.animate(element, { opacity: [0, 1], duration: 180, ease: "outQuad" }); }
      });
    };
    let scheduled = false;
    const observer = new MutationObserver(() => {
      if (scheduled) return;
      scheduled = true; queueMicrotask(() => { scheduled = false; update(); });
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "hidden"] });
    document.addEventListener("visibilitychange", update);
    media.addEventListener("change", update);
    update();
    return () => {
      active = false;
      observer.disconnect(); document.removeEventListener("visibilitychange", update); media.removeEventListener("change", update);
      spinning.forEach(motion => motion.revert());
    };
  }, []);
}
