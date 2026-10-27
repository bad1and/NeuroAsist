import { Disclosure } from "./Disclosure";
import { useCallback, useEffect, useRef, useState } from "react";
import { MaterialButton } from "./MaterialButton";
import {
  IconInterfaceAlertAlarmBell2 as Bell,
} from "../CustomIcons";
import { getReminders, updateReminder, type Reminder } from "../product-api";
import { requestJson } from "../api";
import { allowReminderNotifications } from "./ReminderDelivery";
import type { MemoryCommitment } from "../types";
import { interfaceIntlLocale } from "../i18n";

function localTime(value: string): string {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function ReminderReschedule({ item, busy, onSave }: { item: Reminder; busy: boolean; onSave: (due: string) => void }) {
  const [value, setValue] = useState(() => localTime(item.due_at));
  useEffect(() => setValue(localTime(item.due_at)), [item.due_at]);
  return <form className="reminder-actions" onSubmit={event => { event.preventDefault(); onSave(new Date(value).toISOString()); }}>
    <label>Новый срок<input aria-label={`Перенести: ${item.title}`} type="datetime-local" required min={localTime(new Date(Date.now() + 60_000).toISOString())} value={value} disabled={busy} onChange={event => setValue(event.target.value)} /></label>
    <MaterialButton materialKey={`reminders.save-date.${item.id}`} type="submit" className="secondary" disabled={busy || !value || value === localTime(item.due_at)}>Сохранить срок</MaterialButton>
  </form>;
}

export function RemindersPanel({ plans, onChanged, query = "", sortOrder = "date-desc" }: {
  plans: MemoryCommitment[]; onChanged: () => void; query?: string;
  sortOrder?: "date-desc" | "date-asc" | "alpha-asc" | "alpha-desc";
}) {
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [filter, setFilter] = useState<"open" | "all">("open");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const requestRef = useRef(0);
  const refresh = useCallback(async () => {
    const request = ++requestRef.current;
    try { const response = await getReminders(); if (request === requestRef.current) { setReminders(response.items); setError(""); } }
    catch (cause) { if (request === requestRef.current) setError(cause instanceof Error ? cause.message : "Не удалось загрузить напоминания"); }
  }, []);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15_000);
    window.addEventListener("focus", refresh);
    return () => { requestRef.current++; clearInterval(timer); window.removeEventListener("focus", refresh); };
  }, [refresh]);
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await action(); await refresh(); onChanged(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Не удалось изменить план"); }
    finally { setBusy(false); }
  };
  const byId = new Map(plans.map(plan => [plan.id, plan as MemoryCommitment & Partial<Reminder>]));
  reminders.forEach(reminder => byId.set(reminder.id, { ...byId.get(reminder.id), ...reminder, kind: byId.get(reminder.id)?.kind || "open_loop", details: byId.get(reminder.id)?.details || "", confidence: 1, importance: 1, user_locked: true }));
  const term = query.trim().toLocaleLowerCase();
  const providedPlanIds = new Set(plans.map(plan => plan.id));
  const terms = (term.match(/[\p{L}\p{N}]+/gu) || []).filter(word => word.length >= 2);
  const items = [...byId.values()].filter(item => (filter === "all" || item.status === "open")
    // Plans have already passed server FTS. Match reminders added by the
    // outbox with the same OR/prefix rule, without discarding server matches.
    && (!terms.length || providedPlanIds.has(item.id) || terms.some(term =>
      (`${item.title} ${item.details || ""}`.toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu) || []).some(word => word.startsWith(term))))).sort((left, right) => {
      if (sortOrder === "alpha-asc") return left.title.localeCompare(right.title);
      if (sortOrder === "alpha-desc") return right.title.localeCompare(left.title);
      const difference = (Date.parse(left.created_at || "") || 0) - (Date.parse(right.created_at || "") || 0);
      return (sortOrder === "date-asc" ? 1 : -1) * (difference || left.id.localeCompare(right.id));
    });
  const patch = (item: typeof items[number], status: "completed" | "cancelled") => run(() => item.delivery_token ? updateReminder(item.id, { status }) : requestJson(`/memory/commitments/${encodeURIComponent(item.id)}`, { method: "PATCH", body: JSON.stringify({ status }) }));
  return <section className="reminders-panel" aria-label="Планы и напоминания">
    <div className="reminder-toolbar">
      <MaterialButton materialKey="reminders.filter" className="secondary" type="button" aria-pressed={filter === "all"} onClick={() => setFilter(filter === "open" ? "all" : "open")}>{filter === "open" ? "Показать завершённые" : "Скрыть завершённые"}</MaterialButton>
      {reminders.length > 0 && <MaterialButton materialKey="reminders.permissions" className="secondary" type="button" title="Разрешить системные уведомления" onClick={() => { void allowReminderNotifications().then(granted => setNotice(granted ? "Системные уведомления разрешены" : "Напоминания будут показаны внутри Iris")).catch(() => setNotice("Напоминания будут показаны внутри Iris")); }}><Bell size={16} aria-hidden="true" />Уведомления</MaterialButton>}
    </div>
    {error && <p role="alert" className="error-text">{error} <MaterialButton materialKey="reminders.retry" className="text-button" type="button" onClick={() => void refresh()}>Повторить</MaterialButton></p>}
    {notice && <p role="status">{notice}</p>}
    {!items.length && <div className="empty-state"><strong>{filter === "open" ? "Предстоящих планов пока нет" : "Планов пока нет"}</strong><span>Попросите Iris запомнить план или напомнить о нём.</span></div>}
    <div className="reminders-list">
    {items.map(item => <article className="memory-card reminder-card" id={`memory-record-${item.id}`} key={item.id}>
      <div className="memory-card-main"><div className="memory-card-heading"><h3 data-i18n-skip>{item.title}</h3><span className="memory-status">{{ open: "Предстоит", completed: "Выполнено", cancelled: "Отменено" }[item.status]}</span></div>
        {item.details && <p className="reminder-details" data-i18n-skip>{item.details}</p>}
        {item.due_at && <time dateTime={item.due_at}>{item.delivery_token && <Bell size={14} aria-label="Напоминание" />}{new Date(item.due_at).toLocaleString(interfaceIntlLocale(), { dateStyle: "medium", timeStyle: "short" })}</time>}
        {item.status === "open" && <div className="reminder-card-actions">
          <MaterialButton materialKey={`reminders.done.${item.id}`} className="secondary" disabled={busy} onClick={() => void patch(item, "completed")}>Готово</MaterialButton>
          <MaterialButton materialKey={`reminders.cancel.${item.id}`} className="text-button" disabled={busy} onClick={() => void patch(item, "cancelled")}>Отменить</MaterialButton>
          {item.delivery_token && <Disclosure materialKey={`reminder.reschedule.${item.id}`} label="Перенести" className="reminder-reschedule"><ReminderReschedule item={item as Reminder} busy={busy} onSave={value => void run(() => updateReminder(item.id, { due_at: value }))} /></Disclosure>}
        </div>}
      </div>
    </article>)}
    </div>
  </section>;
}
