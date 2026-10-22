import { useState } from "react";
import { AppSwitch } from "./AppSwitch";

export const COMPACT_STARTUP_KEY = "iris.startup.compact.v1";
export function compactStartup(): boolean {
  try { return localStorage.getItem(COMPACT_STARTUP_KEY) === "1"; } catch { return false; }
}
export function StartupSpeedSetting() {
  const [enabled, setEnabled] = useState(compactStartup);
  return <div className="settings-card"><AppSwitch checked={enabled} label="Сократить анимацию запуска" description="Вступит в силу при следующем запуске Iris." onChange={checked => { try { localStorage.setItem(COMPACT_STARTUP_KEY, checked ? "1" : "0"); setEnabled(checked); } catch { /* Leave the previous value if storage is unavailable. */ } }} /></div>;
}
