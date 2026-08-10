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
