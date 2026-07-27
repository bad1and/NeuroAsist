import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";

export type CoreStatus = "starting" | "ready" | "failed" | "crashed";

export type DesktopRuntime = {
  apiBaseUrl: string;
  apiToken: string;
  wsEventsUrl: string;
  safeMode: boolean;
  coreStatus: CoreStatus;
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

export async function restartDesktopCore(): Promise<DesktopRuntime> {
  return invoke<DesktopRuntime>("restart_core");
}

export async function getDesktopRuntime(): Promise<DesktopRuntime> {
  return invoke<DesktopRuntime>("desktop_runtime");
}

export async function quitDesktopApp(): Promise<void> {
  return invoke<void>("quit_app");
}
