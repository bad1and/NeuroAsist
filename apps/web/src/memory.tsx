import { FormEvent, useEffect, useState } from "react";
import { Brain, Check, CircleHelp, Pencil, Pin, Plus, RotateCcw, Search, Trash2, X } from "lucide-react";

import {
  confirmMemory, createMemory, deleteMemory, getMemories, getMemoryAudit,
  rejectMemory, restoreMemory, updateMemory,
} from "./api";
import type { MemoryAuditItem, MemoryItem, MemoryStatus } from "./types";

const STATUSES: Array<MemoryStatus | "all"> = ["all", "active", "candidate", "superseded", "deleted", "rejected"];
const STATUS_LABELS: Record<MemoryStatus | "all", string> = {
  all: "Все", active: "Сохранённые", candidate: "На проверке", superseded: "Заменённые", deleted: "Удалённые", rejected: "Отклонённые", expired: "Истёкшие",
};

export function MemoryPage() {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [status, setStatus] = useState<MemoryStatus | "all">("all");
  const [query, setQuery] = useState("");
  const [audit, setAudit] = useState<Record<string, MemoryAuditItem[]>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [predicate, setPredicate] = useState("заметка");
  const [value, setValue] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [showCreateForm, setShowCreateForm] = useState(false);

  const refresh = async () => {
    try {
      setItems((await getMemories(status === "all" ? undefined : status, query || undefined)).items);
      setMessage(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Память недоступна");
    }
  };

  useEffect(() => { void refresh(); }, [status]);

  const action = async (run: () => Promise<unknown>) => {
    try { await run(); await refresh(); } catch (error) { setMessage(error instanceof Error ? error.message : "Не удалось выполнить действие"); }
  };

  const onCreate = async (event: FormEvent) => {
    event.preventDefault();
    await action(() => createMemory({ predicate, value_text: value, source_message_ids: sourceId ? [sourceId] : [] }));
    setValue("");
    setSourceId("");
    setShowCreateForm(false);
  };

  return <section className="panel memory-panel">
    <div className="panel-header">
      <div><span className="eyebrow">ДОЛГОСРОЧНЫЙ КОНТЕКСТ</span><h2>Память</h2></div>
      <button className="primary-button" onClick={() => setShowCreateForm((current) => !current)}><Plus size={17} aria-hidden="true" />{showCreateForm ? "Закрыть" : "Добавить запись"}</button>
    </div>
    <div className="memory-toolbar">
      <div className="filters" aria-label="Фильтр памяти">{STATUSES.map((item) => <button className={status === item ? "active" : ""} key={item} onClick={() => setStatus(item)}>{STATUS_LABELS[item]}</button>)}</div>
      <form className="search-form compact" onSubmit={(event) => { event.preventDefault(); void refresh(); }}>
        <Search size={17} aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Поиск по памяти" aria-label="Поиск по памяти" /><button className="secondary" type="submit">Найти</button>
      </form>
    </div>
    {showCreateForm && <form className="memory-create-form" onSubmit={onCreate}>
      <label>Тип записи<input value={predicate} onChange={(event) => setPredicate(event.target.value)} required /></label>
      <label>Содержание<input value={value} onChange={(event) => setValue(event.target.value)} required /></label>
      <label>Идентификатор сообщения <small>Необязательно</small><input value={sourceId} onChange={(event) => setSourceId(event.target.value)} /></label>
      <button className="primary-button" type="submit">Сохранить запись</button>
    </form>}
    {message && <p className="error-text" role="alert">{message}</p>}
    <div className="memory-list">
      {items.length ? items.map((memory) => <article className="memory-card" key={memory.id}>
        <div className="memory-card-main"><div className="memory-card-heading"><span className={`memory-status ${memory.status}`}>{STATUS_LABELS[memory.status]}</span>{memory.user_locked && <Pin size={14} aria-label="Закреплённая запись" />}</div><strong>{memory.predicate}</strong><p>{memory.value_text}</p><small>{memory.source_message_ids.length ? `Источник: ${memory.source_message_ids.length} сообщ.` : "Источник не указан"} · использовано: {memory.access_count}</small></div>
        <div className="memory-actions">
          {memory.status === "candidate" && <><button className="primary-button" onClick={() => void action(() => confirmMemory(memory.id))}><Check size={16} aria-hidden="true" />Подтвердить</button><button className="secondary" onClick={() => void action(() => rejectMemory(memory.id))}><X size={16} aria-hidden="true" />Отклонить</button></>}
          {memory.status === "deleted" ? <button className="secondary" onClick={() => void action(() => restoreMemory(memory.id))}><RotateCcw size={16} aria-hidden="true" />Восстановить</button> : <button className="secondary" onClick={() => void action(() => deleteMemory(memory.id))}><Trash2 size={16} aria-hidden="true" />Забыть</button>}
          {memory.status !== "deleted" && <button className="icon-button" title="Изменить" aria-label="Изменить запись" onClick={() => { const next = window.prompt("Изменить запись", memory.value_text); if (next?.trim()) void action(() => updateMemory(memory.id, { value_text: next.trim(), user_locked: true })); }}><Pencil size={16} /></button>}
          {memory.status !== "deleted" && !memory.user_locked && <button className="icon-button" title="Закрепить" aria-label="Закрепить запись" onClick={() => void action(() => updateMemory(memory.id, { user_locked: true }))}><Pin size={16} /></button>}
          <button className="icon-button" title="Показать историю записи" aria-label="Показать историю записи" onClick={async () => { const nextAudit = await getMemoryAudit(memory.id); setAudit((current) => ({ ...current, [memory.id]: nextAudit.items })); }}><CircleHelp size={16} /></button>
        </div>
        {audit[memory.id] && <details className="memory-audit" open><summary>История записи</summary><p>{audit[memory.id].map((item) => `${item.action} (${item.actor})`).join(" → ")}</p></details>}
      </article>) : <div className="empty-state"><Brain size={28} aria-hidden="true" /><strong>Записей пока нет</strong><span>Помощник предложит факты для сохранения после разговора.</span></div>}
    </div>
  </section>;
}
