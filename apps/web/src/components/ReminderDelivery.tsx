import { useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { isPermissionGranted, requestPermission } from "@tauri-apps/plugin-notification";
import { isDesktopApp } from "../desktop";
import { getReminders, acknowledgeReminder, updateReminder, type Reminder } from "../product-api";
import { notify } from "../notifications";

const displayed = new Set<string>();
const pending = new Set<string>();

export async function allowReminderNotifications(): Promise<boolean> {
  if (isDesktopApp()) return await isPermissionGranted() || await requestPermission() === "granted";
  return typeof Notification !== "undefined" && (Notification.permission === "granted" || await Notification.requestPermission() === "granted");
}

export async function showSystemReminder(item: Reminder): Promise<boolean> {
  if (isDesktopApp()) {
    if (!await isPermissionGranted()) return false;
    await invoke("plugin:notification|notify", { options: { title: "Iris · Напоминание", body: item.title } });
    return true;
  }
  if (typeof Notification !== "undefined" && Notification.permission === "granted") {
    new Notification("Iris · Напоминание", { body: item.title, tag: item.delivery_token });
    return true;
  }
  return false;
}

async function deliver(item: Reminder) {
  if (pending.has(item.delivery_token)) return;
  pending.add(item.delivery_token);
  try {
    const key = `iris.reminder-delivered.${item.delivery_token}`;
    let wasDisplayed = displayed.has(item.delivery_token);
    try { wasDisplayed ||= localStorage.getItem(key) === "1"; } catch { /* The in-memory guard still works. */ }
    if (!wasDisplayed) {
      const change = async (patch: Parameters<typeof updateReminder>[1]) => {
        try { await updateReminder(item.id, patch); notify.dismiss(`reminder.${item.delivery_token}`); }
        catch (error) { notify.error("Напоминание", String(error)); }
      };
      notify.reminder("Напоминание", item.title, { id: `reminder.${item.delivery_token}`, actions: [
        { label: "Готово", onClick: () => { void change({ status: "completed" }); } },
        { label: "Через 15 минут", onClick: () => { void change({ due_at: new Date(Date.now() + 15 * 60_000).toISOString() }); } },
      ] });
      try { await showSystemReminder(item); } catch { /* The in-app reminder remains available. */ }
      displayed.add(item.delivery_token);
      try { localStorage.setItem(key, "1"); } catch { /* Do not lose the in-app result. */ }
    }
    await acknowledgeReminder(item);
  } finally { pending.delete(item.delivery_token); }
}

export function ReminderDelivery({ enabled }: { enabled: boolean }) {
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let busy = false;
    const poll = async () => {
      if (busy) return;
      busy = true;
      try {
        const response = await getReminders(true, controller.signal);
        for (const item of response.items) {
          if (controller.signal.aborted) break;
          await deliver(item);
        }
      } catch { /* A transient connection failure retries on the next tick. */ }
      finally { busy = false; }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 5000);
    window.addEventListener("focus", poll);
    return () => { controller.abort(); clearInterval(timer); window.removeEventListener("focus", poll); };
  }, [enabled]);
  return null;
}
