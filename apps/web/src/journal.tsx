import { FormEvent, useEffect, useState } from "react";

import { deleteTimelineRange, getTimelineJournal, searchTimeline } from "./api";
import type { TimelineJournalItem, TimelineMessage } from "./types";

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
      setError(cause instanceof Error ? cause.message : "Journal unavailable");
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
      setError(cause instanceof Error ? cause.message : "Search failed");
    }
  };

  return <section className="panel">
    <div className="panel-heading"><h2>Journal</h2><button onClick={() => void refresh()}>Refresh</button></div>
    <form className="chat-form" onSubmit={onSearch}>
      <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search shared history" />
      <button type="submit">Search</button>
    </form>
    {error && <p className="error-text">{error}</p>}
    {results && <div className="message-list">{results.map((message) => <article className={`message ${message.role}`} key={message.id}><strong>{message.role}</strong><p>{message.content}</p></article>)}</div>}
    {!results && <div className="event-list">{items.map((item) => <article className="event-card" key={item.id ?? item.day}><div><strong>{item.title || item.day}</strong><p>{item.message_count} messages · {item.status ?? "history"} · last activity {new Date(item.last_activity_at).toLocaleTimeString()}{item.boundary_reason ? ` · ${item.boundary_reason}` : ""}</p></div><button onClick={async () => { if (window.confirm(`Delete all timeline messages through ${item.day}?`)) { await deleteTimelineRange(`${item.day}T23:59:59.999Z`); await refresh(); } }}>Delete through day</button></article>)}</div>}
  </section>;
}
