import { invoke } from "@tauri-apps/api/core";
import type { AvatarOverlaySettings, DesktopAvatarLayout, DesktopAvatarMode } from "./types";
export type DesktopRect = { x: number; y: number; width: number; height: number };
export type DesktopMonitor = { id: string; name: string; area: DesktopRect; scale: number; primary: boolean };
export type DesktopAvatarGeometry = {
  desktop_mode: DesktopAvatarMode; monitor: DesktopMonitor; rect: DesktopRect;
  layout: DesktopAvatarLayout; transforming: boolean; commit: boolean;
};
export const getDesktopAvatarMonitors = () => invoke<DesktopMonitor[]>("get_desktop_avatar_monitors");
export const configureDesktopAvatar = (config: AvatarOverlaySettings) => invoke<DesktopAvatarGeometry | null>("configure_desktop_avatar", { config });
export function localAvatarRect(g: DesktopAvatarGeometry): DesktopRect {
  const { area, scale } = g.monitor;
  return { x: (g.rect.x-area.x)/scale, y: (g.rect.y-area.y)/scale,
    width: g.rect.width/scale, height: g.rect.height/scale };
}
export function placePanel(avatar: DesktopRect, width: number, height: number, work: DesktopRect): DesktopRect {
  const gap = 12;
  width = Math.min(width, work.width-gap*2);
  const controls = desktopAvatarControls(avatar, work);
  const x = controls.left.x-width-gap;
  // Near the left edge, keep the panel on screen below the controls.
  const y = controls.left.y + (x < gap ? controls.left.height+gap : 0);
  return { x: Math.max(gap, Math.min(x,work.width-width-gap)),
    y: Math.max(gap, Math.min(y,work.height-height-gap)), width, height };
}

/** Controls stay inside the existing Unity bounds; no window resize is needed. */
export function desktopAvatarControls(avatar: DesktopRect, work: DesktopRect) {
  const size = 44;
  const inset = Math.min(8, Math.max(0, (avatar.width-size*2-4)/2));
  const y = Math.max(6, Math.min(avatar.y+avatar.height*.12, work.height-104));
  return {
    left: { x: Math.max(0, avatar.x+inset), y, width: size, height: size*2+10 },
    right: { x: Math.max(0, Math.min(avatar.x+avatar.width-inset-size, work.width-size)), y, width: size, height: size*2 },
  };
}
