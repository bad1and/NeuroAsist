import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";
import type { AvatarPlacement, InterfaceLocale } from "./types";

export type CoreStatus = "starting" | "ready" | "failed" | "crashed";

export type DesktopRuntime = {
  apiBaseUrl: string;
  apiToken: string;
  wsEventsUrl: string;
  safeMode: boolean;
  coreStatus: CoreStatus;
};

export type AvatarInAppBounds = {
  x: number;
  y: number;
  width: number;
  height: number;
  // Bounds and visibility carry the same monotonic revision so native code
  // can discard IPC messages that arrive after the chat host unmounts.
  revision: number;
};

export type AvatarHostStatus = {
  placement: AvatarPlacement;
  running: boolean;
  embedded: boolean;
  visible: boolean;
};

export function isDesktopApp(): boolean {
  return typeof window !== "undefined" && Boolean(window.__TAURI_INTERNALS__);
}

export function initialCoreStatus(): CoreStatus {
  return isDesktopApp()
    ? window.__NEUROASIST_DESKTOP_CONFIG__?.coreStatus ?? "starting"
    : "ready";
}

export async function listenForCoreStatus(
  listener: (status: CoreStatus) => void,
): Promise<UnlistenFn> {
  if (!isDesktopApp()) return () => undefined;
  return listen<CoreStatus>("desktop-core-status", ({ payload }) => listener(payload));
}

export async function listenForAvatarVisibility(
  listener: (visible: boolean) => void,
): Promise<UnlistenFn> {
  if (!isDesktopApp()) return () => undefined;
  return listen<boolean>("desktop-avatar-visibility", ({ payload }) => listener(payload));
}

export async function listenForAvatarLayoutInvalidation(
  listener: () => void,
): Promise<UnlistenFn> {
  if (!isDesktopApp()) return () => undefined;
  return listen("desktop-avatar-layout-invalidated", () => listener());
}

export async function restartDesktopCore(): Promise<DesktopRuntime> {
  return invoke<DesktopRuntime>("restart_core");
}

export async function getDesktopRuntime(): Promise<DesktopRuntime> {
  return invoke<DesktopRuntime>("desktop_runtime");
}

export async function quitDesktopApp(): Promise<void> {
  return invoke<void>("quit_app");
}

export async function setDesktopInterfaceLocale(locale: InterfaceLocale): Promise<void> {
  if (!isDesktopApp()) return;
  await invoke<void>("set_interface_locale", { locale });
}

export async function configureAvatarPlacement(placement: AvatarPlacement): Promise<AvatarHostStatus | null> {
  if (!isDesktopApp()) return null;
  return invoke<AvatarHostStatus>("configure_avatar_placement", { placement });
}

export async function setAvatarInAppBounds(bounds: AvatarInAppBounds): Promise<void> {
  if (!isDesktopApp()) return;
  await invoke<void>("set_avatar_in_app_bounds", { bounds });
}

export async function setAvatarInAppVisible(visible: boolean, revision: number): Promise<void> {
  if (!isDesktopApp()) return;
  await invoke<void>("set_avatar_in_app_visible", { visible, revision });
}

let browserQaWindow: Window | null = null;

export async function openQaStudioWindow(): Promise<void> {
  if (isDesktopApp()) {
    try {
      await invoke("open_qa_studio");
      return;
    } catch (error) {
      console.error("Failed to open QA studio desktop window:", error);
      // Fall back to window.open if command fails
    }
  }
  const url = `${window.location.origin}${window.location.pathname}?view=qa-studio`;
  if (browserQaWindow && !browserQaWindow.closed) {
    browserQaWindow.focus();
    return;
  }
  browserQaWindow = window.open(
    url,
    "IrisQAStudio",
    "width=760,height=880,menubar=no,toolbar=no,location=no,status=no,resizable=yes"
  );
  if (browserQaWindow) {
    browserQaWindow.focus();
  }
}

export async function closeQaStudioWindow(): Promise<void> {
  if (isDesktopApp()) {
    try {
      await invoke("close_qa_studio");
    } catch (error) {
      console.error("Failed to close QA studio desktop window:", error);
    }
  }
  if (browserQaWindow && !browserQaWindow.closed) {
    browserQaWindow.close();
    browserQaWindow = null;
  }
  try {
    const channel = new BroadcastChannel("iris_qa_studio");
    channel.postMessage({ action: "close" });
    channel.close();
  } catch {
    // Ignore
  }
}

export async function isQaStudioWindowOpen(): Promise<boolean> {
  if (isDesktopApp()) {
    try {
      return await invoke<boolean>("is_qa_studio_open");
    } catch {
      return false;
    }
  }
  return Boolean(browserQaWindow && !browserQaWindow.closed);
}

export async function listenForQaStudioState(
  listener: (open: boolean) => void,
): Promise<UnlistenFn> {
  if (isDesktopApp()) {
    try {
      return await listen<boolean>("qa-studio-state", ({ payload }) => listener(payload));
    } catch (error) {
      console.error("Failed to listen for qa-studio-state:", error);
      return () => undefined;
    }
  }

  let channel: BroadcastChannel | null = null;
  try {
    channel = new BroadcastChannel("iris_qa_studio");
    channel.onmessage = (event: MessageEvent) => {
      if (event.data?.action === "state" && typeof event.data.open === "boolean") {
        listener(event.data.open);
      } else if (event.data?.action === "closed") {
        listener(false);
      }
    };
  } catch {
    // Ignore
  }

  return () => {
    channel?.close();
  };
}

