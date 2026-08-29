import {
  IconInterfaceTimeStopWatchCircle,
  IconInterfaceSpirals,
  IconInterfaceSearch,
  IconInterfaceDeleteBin3,
} from "./CustomIcons";
import { FormEvent, useEffect, useRef, useState } from "react";

import { deleteTimelineRange, getTimelineJournal, searchTimeline } from "./api";
import type { TimelineJournalItem, TimelineMessage } from "./types";
import { AppDialog } from "./components/AppDialog";
import { interfaceIntlLocale } from "./i18n";
import { animateButtonPress, animatePageEnter, animateStaggerCards, useAnimeScope } from "./animations";

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(interfaceIntlLocale(), { day: "numeric", month: "long", year: "numeric" }).format(date);
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleTimeString(interfaceIntlLocale(), { hour: "2-digit", minute: "2-digit" });
}

export function JournalPage() {
  const [items, setItems] = useState<TimelineJournalItem[]>([]);
  const [results, setResults] = useState<TimelineMessage[] | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<TimelineJournalItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  const containerRef = useAnimeScope<HTMLElement>((scope, root) => {
    animatePageEnter(root);
  }, []);

  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (listRef.current) {
      const selector = results ? ".message" : ".history-card";
      animateStaggerCards(listRef.current, selector, 40);
    }
  }, [items, results]);

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

  return <section className="panel history-panel" ref={containerRef}>
    <form className="search-form" onSubmit={onSearch}>
      <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Поиск по истории" aria-label="Поиск по истории" />
      {results && <button className="secondary" type="button" onClick={() => { setQuery(""); setResults(null); }}>Сбросить</button>}
      <button className="icon-button" type="button" onClick={(e) => { animateButtonPress(e.currentTarget); void refresh(); }} aria-label="Обновить историю" title="Обновить историю"><IconInterfaceSpirals size={17} /></button>
      <button className="icon-button search-submit" type="submit" aria-label="Найти в истории" title="Найти в истории"><IconInterfaceSearch size={18} /></button>
    </form>
    {error && <p className="error-text" role="alert">{error}</p>}
    {results && <div className="history-list search-results" ref={listRef}>
      {results.length ? results.map((message) => <article className={`message ${message.role === "user" ? "user" : "assistant"}`} key={message.id}><div className="message-role">{message.role === "user" ? "Вы" : "Iris"}</div><p data-i18n-skip>{message.content}</p></article>) : <EmptyHistory text="Ничего не найдено" />}
    </div>}
    {!results && <div className="history-list" ref={listRef}>
      {items.length ? items.map((item) => <article className="history-card" key={item.id ?? item.day}>
        <div><strong>{item.title || formatDate(item.day)}</strong><p>{item.message_count} {item.message_count === 1 ? "сообщение" : "сообщений"} · последняя активность в {formatTime(item.last_activity_at)}</p></div>
        <button className="icon-button danger-button" title="Удалить историю до этой даты" aria-label={`Удалить историю до ${formatDate(item.day)}`} onClick={(e) => { animateButtonPress(e.currentTarget); setPendingDelete(item); }}><IconInterfaceDeleteBin3 size={17} /></button>
      </article>) : <EmptyHistory text="История пока пуста" />}
    </div>}
    <AppDialog
      open={Boolean(pendingDelete)}
      title="Удалить часть истории?"
      description={pendingDelete ? `Все сообщения по ${formatDate(pendingDelete.day)} включительно будут удалены без возможности восстановления.` : undefined}
      onClose={() => !deleting && setPendingDelete(null)}
    >
      <div className="dialog-actions">
        <button className="secondary" type="button" onClick={() => setPendingDelete(null)} disabled={deleting}>Отмена</button>
        <button className="danger-button" type="button" disabled={deleting} onClick={async () => {
          if (!pendingDelete) return;
          setDeleting(true);
          try {
            await deleteTimelineRange(`${pendingDelete.day}T23:59:59.999Z`);
            setPendingDelete(null);
            await refresh();
          } finally {
            setDeleting(false);
          }
        }}>{deleting ? "Удаляю…" : "Удалить историю"}</button>
      </div>
    </AppDialog>
  </section>;
}

function EmptyHistory({ text }: { text: string }) {
  return <div className="empty-state"><IconInterfaceTimeStopWatchCircle size={28} aria-hidden="true" /><strong>{text}</strong><span>Здесь появятся прошлые разговоры.</span></div>;
}
