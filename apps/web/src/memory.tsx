import { FormEvent, useEffect, useState } from "react";
import { Archive, Brain, Check, CheckCircle2, CircleHelp, ClipboardCheck, ListChecks, MoreHorizontal, Pencil, Pin, Plus, RotateCcw, Search, Tag, Trash2, X } from "lucide-react";

import {
  confirmMemory, createMemory, deleteMemory, getMemories, getMemoryAudit,
  closeMemoryCommitment, getMemoryCommitments, getMemoryConflicts, getMemoryTopics,
  rejectMemory, restoreMemory, updateMemory,
} from "./api";
import type { MemoryAuditItem, MemoryCommitment, MemoryItem, MemoryStatus, MemoryTopic } from "./types";
import { AppDialog } from "./components/AppDialog";

type MemorySection = "all" | "active" | "topics" | "commitments" | "candidate" | "archive" | "diagnostics";

const STATUS_LABELS: Record<MemoryStatus | "all", string> = {
  all: "Все", active: "Сохранённые", candidate: "На проверке", superseded: "Заменённые", deleted: "Удалённые", rejected: "Отклонённые", expired: "Истёкшие",
};

const MEMORY_SECTIONS: Array<{ id: MemorySection; label: string; icon: typeof Brain }> = [
  { id: "all", label: "Все", icon: Brain },
  { id: "active", label: "Сохранённые", icon: CheckCircle2 },
  { id: "topics", label: "Темы", icon: Tag },
  { id: "commitments", label: "Планы и обещания", icon: ListChecks },
  { id: "candidate", label: "На проверке", icon: ClipboardCheck },
  { id: "archive", label: "Архив", icon: Archive },
  { id: "diagnostics", label: "Диагностика", icon: CircleHelp },
];

export function MemoryPage() {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [topics, setTopics] = useState<MemoryTopic[]>([]);
  const [commitments, setCommitments] = useState<MemoryCommitment[]>([]);
  const [conflicts, setConflicts] = useState<Array<{ id: string; reason: string; status: string }>>([]);
  const [section, setSection] = useState<MemorySection>("all");
  const [query, setQuery] = useState("");
  const [audit, setAudit] = useState<Record<string, MemoryAuditItem[]>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [predicate, setPredicate] = useState("заметка");
  const [value, setValue] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [editing, setEditing] = useState<MemoryItem | null>(null);
  const [editValue, setEditValue] = useState("");
  const [editBusy, setEditBusy] = useState(false);

  const refresh = async () => {
    try {
      if (section === "topics") { setTopics((await getMemoryTopics()).items); setMessage(null); return; }
      if (section === "commitments") { setCommitments((await getMemoryCommitments()).items); setMessage(null); return; }
      if (section === "diagnostics") { setConflicts((await getMemoryConflicts()).items); setMessage(null); return; }
      const result = await getMemories(section === "all" || section === "archive" ? undefined : section, query || undefined);
      setItems(
        section === "archive"
          ? result.items.filter((item) => !["active", "candidate"].includes(item.status))
          : result.items,
      );
      setMessage(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Память недоступна");
    }
  };

  useEffect(() => { void refresh(); }, [section]);

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
    <nav className="settings-navigation memory-navigation" aria-label="Разделы памяти">
      {MEMORY_SECTIONS.map(({ id, label, icon: Icon }) => (
        <button
          className={`settings-nav-button${section === id ? " is-active" : ""}`}
          aria-current={section === id ? "page" : undefined}
          key={id}
          onClick={() => setSection(id)}
        >
          <Icon size={17} aria-hidden="true" />
          {label}
        </button>
      ))}
    </nav>
    <div className="memory-toolbar">
      <div className="memory-toolbar-actions">
        <form className="search-form compact" onSubmit={(event) => { event.preventDefault(); void refresh(); }}>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Поиск по памяти" aria-label="Поиск по памяти" />
          <button className="icon-button search-submit" type="submit" aria-label="Найти в памяти" title="Найти в памяти"><Search size={17} /></button>
        </form>
        <button
          className="secondary memory-add-button"
          onClick={() => setShowCreateForm((current) => !current)}
          aria-label={showCreateForm ? "Закрыть добавление записи" : "Добавить запись"}
          title={showCreateForm ? "Закрыть добавление записи" : "Добавить запись"}
        ><Plus size={17} aria-hidden="true" />{showCreateForm ? "Закрыть" : "Добавить"}</button>
      </div>
    </div>
    {showCreateForm && <form className="memory-create-form" onSubmit={onCreate}>
      <label>Тип записи<input value={predicate} onChange={(event) => setPredicate(event.target.value)} required /></label>
      <label>Содержание<input value={value} onChange={(event) => setValue(event.target.value)} required /></label>
      <label>Идентификатор сообщения <small>Необязательно</small><input value={sourceId} onChange={(event) => setSourceId(event.target.value)} /></label>
      <button className="primary-button" type="submit">Сохранить запись</button>
    </form>}
    {message && <p className="error-text" role="alert">{message}</p>}
    <div className="memory-list">
      {section === "topics" && topics.map((topic) => <article className="memory-card" key={topic.id}><div className="memory-card-main"><div className="memory-card-heading"><span className="memory-status active">{topic.status}</span>{topic.user_locked && <Pin size={14} />}</div><strong>{topic.title}</strong><p>{topic.summary_text || "Краткое описание ещё не сформировано."}</p><small>Связи: {topic.links.length} · доказательства: {topic.evidence.length}</small></div></article>)}
      {section === "commitments" && commitments.map((commitment) => <article className="memory-card" key={commitment.id}><div className="memory-card-main"><div className="memory-card-heading"><span className={`memory-status ${commitment.status === "open" ? "candidate" : "active"}`}>{commitment.status}</span></div><strong>{commitment.title}</strong><p>{commitment.details}</p><small>{commitment.kind} · уверенность: {Math.round(commitment.confidence * 100)}%</small></div>{commitment.status === "open" && <div className="memory-actions"><button className="primary-button" onClick={() => void action(() => closeMemoryCommitment(commitment.id))}><Check size={16} />Закрыть</button></div>}</article>)}
      {section === "diagnostics" && <>{conflicts.map((conflict) => <article className="memory-card" key={conflict.id}><div className="memory-card-main"><strong>Конфликт: {conflict.status}</strong><p>{conflict.reason}</p></div></article>)}{!conflicts.length && <div className="empty-state"><CircleHelp size={28} /><strong>Открытых конфликтов нет</strong><span>Здесь появятся записи, требующие проверки.</span></div>}</>}
      {!(["topics", "commitments", "diagnostics"] as MemorySection[]).includes(section) && <>
      {items.length ? items.map((memory) => <article className="memory-card" key={memory.id}>
        <div className="memory-card-main"><div className="memory-card-heading"><span className={`memory-status ${memory.status}`}>{STATUS_LABELS[memory.status]}</span>{memory.user_locked && <Pin size={14} aria-label="Закреплённая запись" />}</div><strong>{memory.predicate}</strong><p>{memory.value_text}</p><small>{memory.source_message_ids.length ? `Источник: ${memory.source_message_ids.length} сообщ.` : "Источник не указан"} · использовано: {memory.access_count}</small></div>
        <div className="memory-actions">
          {memory.status === "candidate" && <><button className="primary-button" onClick={() => void action(() => confirmMemory(memory.id))}><Check size={16} aria-hidden="true" />Подтвердить</button><button className="secondary" onClick={() => void action(() => rejectMemory(memory.id))}><X size={16} aria-hidden="true" />Отклонить</button></>}
          {memory.status === "deleted"
            ? <button className="secondary" onClick={() => void action(() => restoreMemory(memory.id))}><RotateCcw size={16} aria-hidden="true" />Восстановить</button>
            : <details className="memory-action-menu">
                <summary className="icon-button" role="button" aria-label="Дополнительные действия"><MoreHorizontal size={17} aria-hidden="true" /></summary>
                <div>
                  <button type="button" onClick={() => { setEditing(memory); setEditValue(memory.value_text); }}><Pencil size={16} aria-hidden="true" />Изменить</button>
                  {!memory.user_locked && <button type="button" onClick={() => void action(() => updateMemory(memory.id, { user_locked: true }))}><Pin size={16} aria-hidden="true" />Закрепить</button>}
                  <button type="button" onClick={async () => { const nextAudit = await getMemoryAudit(memory.id); setAudit((current) => ({ ...current, [memory.id]: nextAudit.items })); }}><CircleHelp size={16} aria-hidden="true" />История записи</button>
                  <button className="is-danger" type="button" onClick={() => void action(() => deleteMemory(memory.id))}><Trash2 size={16} aria-hidden="true" />Забыть</button>
                </div>
              </details>}
        </div>
        {audit[memory.id] && <details className="memory-audit" open><summary>История записи</summary><p>{audit[memory.id].map((item) => `${item.action} (${item.actor})`).join(" → ")}</p></details>}
      </article>) : <div className="empty-state"><Brain size={28} aria-hidden="true" /><strong>Записей пока нет</strong><span>Помощник предложит факты для сохранения после разговора.</span></div>}
      </>}
    </div>
    <AppDialog open={Boolean(editing)} title="Изменить запись" description="После сохранения запись будет закреплена, чтобы Iris не заменила её автоматически." onClose={() => !editBusy && setEditing(null)}>
      <form className="dialog-form" onSubmit={async (event) => {
        event.preventDefault();
        if (!editing || !editValue.trim()) return;
        setEditBusy(true);
        try {
          await action(() => updateMemory(editing.id, { value_text: editValue.trim(), user_locked: true }));
          setEditing(null);
        } finally {
          setEditBusy(false);
        }
      }}>
        <label>Содержание<textarea autoFocus rows={4} value={editValue} onChange={(event) => setEditValue(event.target.value)} required /></label>
        <div className="dialog-actions">
          <button className="secondary" type="button" onClick={() => setEditing(null)} disabled={editBusy}>Отмена</button>
          <button className="primary-button" type="submit" disabled={editBusy || !editValue.trim()}>{editBusy ? "Сохраняю…" : "Сохранить"}</button>
        </div>
      </form>
    </AppDialog>
  </section>;
}
