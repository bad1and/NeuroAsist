import { requestJson } from "./api";

export type Reminder = {
  id: string; title: string; status: "open" | "completed" | "cancelled";
  due_at: string; timezone_label: string; delivery_token: string; delivered_at: string | null;
};
export function getReminders(dueOnly = false, signal?: AbortSignal): Promise<{ items: Reminder[] }> {
  return requestJson(`/reminders?due_only=${dueOnly}`, { signal });
}
export function updateReminder(id: string, patch: { status?: Reminder["status"]; due_at?: string }): Promise<Reminder> {
  return requestJson(`/reminders/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(patch) });
}
export function acknowledgeReminder(item: Reminder): Promise<{ acknowledged: boolean }> {
  return requestJson(`/reminders/${encodeURIComponent(item.id)}/ack`, { method: "POST", body: JSON.stringify({ delivery_token: item.delivery_token }) });
}
