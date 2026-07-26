import { FormEvent, useEffect, useState } from "react";
import { History, RefreshCw, Search, Trash2 } from "lucide-react";

import { deleteTimelineRange, getTimelineJournal, searchTimeline } from "./api";
import type { TimelineJournalItem, TimelineMessage } from "./types";

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric" }).format(date);
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

export function JournalPage() {
  const [items, setItems] = useState<TimelineJournalItem[]>([]);
  const [results, setResults] = useState<TimelineMessage[] | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      setItems((await getTimelineJournal()).items);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "История недоступна");
    }
  };

  useEffect(() => { void refresh(); }, []);

  const onSearch = async (event: FormEvent) => {
    event.preventDefault();
    if (!query.trim()) { setResults(null); return; }
    try {
      setResults((await searchTimeline(query)).items);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось выполнить поиск");
    }
  };

  return <section className="panel history-panel">
    <form className="search-form" onSubmit={onSearch}>
      <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Поиск по истории" aria-label="Поиск по истории" />
      {results && <button className="secondary" type="button" onClick={() => { setQuery(""); setResults(null); }}>Сбросить</button>}
      <button className="icon-button" type="button" onClick={() => void refresh()} aria-label="Обновить историю" title="Обновить историю"><RefreshCw size={17} /></button>
      <button className="icon-button search-submit" type="submit" aria-label="Найти в истории" title="Найти в истории"><Search size={18} /></button>
    </form>
    {error && <p className="error-text" role="alert">{error}</p>}
    {results && <div className="history-list search-results">
      {results.length ? results.map((message) => <article className={`message ${message.role === "user" ? "user" : "assistant"}`} key={message.id}><div className="message-role">{message.role === "user" ? "Вы" : "Iris"}</div><p>{message.content}</p></article>) : <EmptyHistory text="Ничего не найдено" />}
    </div>}
    {!results && <div className="history-list">
      {items.length ? items.map((item) => <article className="history-card" key={item.id ?? item.day}>
        <div><strong>{item.title || formatDate(item.day)}</strong><p>{item.message_count} {item.message_count === 1 ? "сообщение" : "сообщений"} · последняя активность в {formatTime(item.last_activity_at)}</p></div>
        <button className="icon-button danger-button" title="Удалить историю до этой даты" aria-label={`Удалить историю до ${formatDate(item.day)}`} onClick={async () => {
          if (window.confirm(`Удалить все сообщения по ${formatDate(item.day)} включительно? Это действие нельзя отменить.`)) {
            await deleteTimelineRange(`${item.day}T23:59:59.999Z`);
            await refresh();
          }
        }}><Trash2 size={17} /></button>
      </article>) : <EmptyHistory text="История пока пуста" />}
    </div>}
  </section>;
}

function EmptyHistory({ text }: { text: string }) {
  return <div className="empty-state"><History size={28} aria-hidden="true" /><strong>{text}</strong><span>Здесь появятся прошлые разговоры.</span></div>;
}
