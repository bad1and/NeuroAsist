import { useEffect, useSyncExternalStore } from "react";
import { invoke } from "@tauri-apps/api/core";
import { isDesktopApp } from "./desktop";

export const SHORTCUTS = [
  { id: "search", title: "Найти в Iris", description: "Поиск по истории, памяти, планам и настройкам.", group: "Навигация", default: "Ctrl+KeyK" },
  { id: "settings", title: "Открыть настройки", description: "Перейти к настройкам приложения.", group: "Навигация", default: "Ctrl+Comma" },
  { id: "chat", title: "Открыть диалог", description: "Вернуться к текущему разговору.", group: "Навигация", default: "Ctrl+Shift+Digit1" },
  { id: "history", title: "Открыть историю", description: "Все разговоры с Iris.", group: "Навигация", default: "Ctrl+Shift+Digit2" },
  { id: "memory", title: "Открыть память", description: "Сохранённые факты и предпочтения.", group: "Навигация", default: "Ctrl+Shift+Digit3" },
  { id: "plans", title: "Открыть планы", description: "Планы и напоминания.", group: "Навигация", default: "Ctrl+Shift+Digit4" },
  { id: "sidebar", title: "Свернуть боковую панель", description: "Свернуть или развернуть навигацию.", group: "Навигация", default: "Ctrl+Shift+KeyB" },
  { id: "composer", title: "Перейти к вводу сообщения", description: "Работает в открытом диалоге.", group: "Разговор", default: "Ctrl+Shift+KeyL" },
  { id: "microphone", title: "Выключить / включить микрофон", description: "Во время живого разговора, в любом разделе Iris.", group: "Разговор", default: "Ctrl+Shift+KeyM" },
  { id: "sound", title: "Выключить / включить звук", description: "Управление голосом Iris в текущем разговоре.", group: "Разговор", default: "Ctrl+Shift+KeyS" },
  { id: "stopSpeech", title: "Прервать речь Iris", description: "Остановить озвучивание текущего ответа.", group: "Разговор", default: "Ctrl+Shift+KeyX" },
  { id: "showWindow", title: "Показать окно Iris", description: "Открыть Iris поверх других приложений.", group: "Системные", default: null },
  { id: "toggleAvatar", title: "Показать / скрыть аватар", description: "Переключить видимость аватара вне приложения.", group: "Системные", default: null },
] as const;
export type ShortcutId = typeof SHORTCUTS[number]["id"];
export type GlobalShortcutId = "showWindow" | "toggleAvatar";
export type Bindings = Record<ShortcutId, string | null>;
export type GlobalShortcutStatus = { bindings: Record<GlobalShortcutId, string | null>; errors: Partial<Record<GlobalShortcutId, string>> };
export const isGlobalShortcut = (id: ShortcutId): id is GlobalShortcutId => id === "showWindow" || id === "toggleAvatar";
export const SHORTCUT_STORAGE_KEY = "iris.shortcuts.v1";
export const defaultBindings = (): Bindings => Object.fromEntries(SHORTCUTS.map(item => [item.id, item.default])) as Bindings;

const codes = /^(Key[A-Z]|Digit[0-9]|F(?:[1-9]|1[0-2])|Comma|Period|Slash|Semicolon|Quote|BracketLeft|BracketRight|Backslash|Minus|Equal|Space)$/;
export function bindingError(binding: string): string | null {
  const parts = binding.split("+");
  const code = parts.pop() ?? "";
  if (!codes.test(code) || !parts.includes("Ctrl") || parts.some(part => !["Ctrl", "Shift", "Alt"].includes(part)) || new Set(parts).size !== parts.length) return "Используйте Ctrl и клавишу, при желании добавьте Shift или Alt.";
  if (parts.includes("Alt") && !parts.includes("Shift")) return "Ctrl+Alt может совпадать с AltGr. Добавьте Shift, чтобы не мешать вводу текста.";
  if (parts.join("+") !== ["Ctrl", ...(parts.includes("Shift") ? ["Shift"] : []), ...(parts.includes("Alt") ? ["Alt"] : [])].join("+")) return "Неподдерживаемое сочетание.";
  if (["Ctrl+KeyA", "Ctrl+KeyC", "Ctrl+KeyV", "Ctrl+KeyX", "Ctrl+KeyZ", "Ctrl+KeyY", "Ctrl+KeyS", "Ctrl+KeyF", "Ctrl+KeyP", "Ctrl+KeyO", "Ctrl+KeyN", "Ctrl+KeyW", "Ctrl+KeyT", "Ctrl+KeyR", "Ctrl+KeyL", "Ctrl+KeyU", "Ctrl+Shift+KeyZ", "Ctrl+Shift+KeyV", "Ctrl+Shift+KeyT", "Ctrl+Shift+KeyW", "Ctrl+Shift+KeyN", "Ctrl+Shift+KeyR", "Ctrl+Shift+KeyI", "Ctrl+Shift+KeyJ", "Ctrl+Shift+KeyC", "Ctrl+Shift+KeyO", "Ctrl+F4", "Ctrl+Shift+F4"].includes(binding)) return "Это стандартное сочетание для текста, браузера или окна. Выберите другое.";
  return null;
}

// code is the physical key: KeyK stays KeyK when the OS produces the letter К/Л.
export function bindingFromEvent(event: KeyboardEvent): string | null {
  if (event.isComposing || event.repeat || event.getModifierState("AltGraph") || event.metaKey || !codes.test(event.code)) return null;
  return [...(event.ctrlKey ? ["Ctrl"] : []), ...(event.shiftKey ? ["Shift"] : []), ...(event.altKey ? ["Alt"] : []), event.code].join("+");
}
export function formatBinding(binding: string | null): string {
  if (!binding) return "Не назначено";
  return binding.replace(/Key([A-Z])/g, "$1").replace(/Digit([0-9])/g, "$1")
    .replace("Comma", ",").replace("Period", ".").replace("Slash", "/").replace("Semicolon", ";")
    .replace("Quote", "'").replace("BracketLeft", "[").replace("BracketRight", "]").replace("Backslash", "\\")
    .replace("Minus", "−").replace("Equal", "=").replace("Space", "Space");
}

export function readBindings(): Bindings {
  const defaults = defaultBindings();
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(SHORTCUT_STORAGE_KEY) ?? "{}");
    if (!saved || typeof saved !== "object" || Array.isArray(saved)) return defaults;
    const used = new Set<string>();
    for (const item of SHORTCUTS.filter(item => !isGlobalShortcut(item.id))) {
      const value = (saved as Record<string, unknown>)[item.id];
      const candidate = value === null || (typeof value === "string" && !bindingError(value)) ? value : item.default;
      defaults[item.id] = candidate && used.has(candidate) ? null : candidate;
      if (defaults[item.id]) used.add(defaults[item.id]!);
    }
  } catch { /* Unavailable or corrupt storage leaves the defaults usable. */ }
  return defaults;
}

let bindings = readBindings();
let recording = false;
const subscribers = new Set<() => void>();
const emit = () => subscribers.forEach(listener => listener());
const subscribe = (listener: () => void) => { subscribers.add(listener); return () => { subscribers.delete(listener); }; };
export function useShortcutBindings() { return useSyncExternalStore(subscribe, () => bindings); }
export function setShortcutRecording(value: boolean) { recording = value; }
export function shortcutsAreRecording() { return recording; }
export async function getGlobalShortcuts(): Promise<GlobalShortcutStatus> {
  return invoke<GlobalShortcutStatus>("get_shortcut_preferences");
}
export function mergeGlobalShortcuts(status: GlobalShortcutStatus) {
  bindings = { ...bindings, ...status.bindings };
  emit();
}
export async function saveBindings(next: Bindings, reconnectGlobals = false): Promise<void> {
  const used = new Set<string>();
  for (const item of SHORTCUTS) {
    const value = next[item.id];
    if (value && (bindingError(value) || used.has(value))) throw new Error(bindingError(value) || "Это сочетание уже назначено другой команде.");
    if (value) used.add(value);
  }
  const previous = localStorage.getItem(SHORTCUT_STORAGE_KEY);
  // Verify local persistence before changing native registrations.
  localStorage.setItem(SHORTCUT_STORAGE_KEY, JSON.stringify(Object.fromEntries(SHORTCUTS.filter(item => !isGlobalShortcut(item.id)).map(item => [item.id, next[item.id]]))));
  try {
    if (isDesktopApp() && (reconnectGlobals || next.showWindow !== bindings.showWindow || next.toggleAvatar !== bindings.toggleAvatar)) {
      await invoke<GlobalShortcutStatus>("set_shortcut_preferences", { bindings: { showWindow: next.showWindow, toggleAvatar: next.toggleAvatar } });
    }
  } catch (error) {
    if (previous === null) localStorage.removeItem(SHORTCUT_STORAGE_KEY);
    else localStorage.setItem(SHORTCUT_STORAGE_KEY, previous);
    throw error;
  }
  bindings = { ...next };
  emit();
}

if (typeof window !== "undefined") window.addEventListener("storage", event => {
  if (event.key === SHORTCUT_STORAGE_KEY || event.key === null) {
    bindings = { ...readBindings(), showWindow: bindings.showWindow, toggleAvatar: bindings.toggleAvatar };
    emit();
  }
});

export function useShortcutCommands(commands: Partial<Record<ShortcutId, () => boolean | void>>, enabled = true) {
  const current = useShortcutBindings();
  useEffect(() => {
    if (!enabled) return;
    const handle = (event: KeyboardEvent) => {
      if (recording || event.defaultPrevented || event.isComposing || event.repeat || document.querySelector('[aria-modal="true"]') || document.querySelector(".app-shell[inert]")) return;
      const chord = bindingFromEvent(event);
      if (!chord) return;
      const command = SHORTCUTS.find(item => !isGlobalShortcut(item.id) && current[item.id] === chord && commands[item.id]);
      if (command && commands[command.id]?.() !== false) { event.preventDefault(); }
    };
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, [current, commands, enabled]);
}
