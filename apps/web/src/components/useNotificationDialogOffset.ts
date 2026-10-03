import { useLayoutEffect, type RefObject } from "react";

/** Reserve the actual dialog height, including while its exit is playing. */
export function useNotificationDialogOffset(hostRef: RefObject<HTMLElement | null>, mounted: boolean) {
  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const dialogs = new Set<HTMLElement>();
    const measure = () => {
      // offsetHeight excludes the entrance scale, so the conversation is clear
      // of the dialog from its very first frame.
      const height = Math.max(0, ...Array.from(dialogs, (dialog) => dialog.offsetHeight));
      host.style.setProperty("--notification-dialog-offset", `${height > 0 ? height + 8 : 0}px`);
    };
    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    const sync = () => {
      const current = new Set(document.querySelectorAll<HTMLElement>(".app-dialog-host"));
      for (const dialog of dialogs) {
        if (!current.has(dialog)) {
          resize?.unobserve(dialog);
          dialogs.delete(dialog);
        }
      }
      for (const dialog of current) {
        if (!dialogs.has(dialog)) {
          dialogs.add(dialog);
          resize?.observe(dialog);
        }
      }
      measure();
    };
    const mutations = new MutationObserver(sync);
    mutations.observe(document.body, { childList: true, subtree: true });
    window.addEventListener("resize", measure);
    sync();
    return () => {
      mutations.disconnect();
      resize?.disconnect();
      window.removeEventListener("resize", measure);
      host.style.removeProperty("--notification-dialog-offset");
    };
  }, [hostRef, mounted]);
}
