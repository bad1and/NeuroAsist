import { FormEvent, useEffect, useState } from "react";

import {
  clearMemories, confirmMemory, createMemory, deleteMemory, getMemories,
  getMemoryAudit, rejectMemory, reindexMemories, restoreMemory,
  resetAllCompanionData, updateMemory,
} from "./api";
import type { MemoryAuditItem, MemoryItem, MemoryStatus } from "./types";

const STATUSES: Array<MemoryStatus | "all"> = ["all", "active", "candidate", "superseded", "deleted", "rejected"];

export function MemoryPage() {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [status, setStatus] = useState<MemoryStatus | "all">("all");
  const [query, setQuery] = useState("");
  const [audit, setAudit] = useState<Record<string, MemoryAuditItem[]>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [predicate, setPredicate] = useState("note");
  const [value, setValue] = useState("");
  const [sourceId, setSourceId] = useState("");

  const refresh = async () => {
    try {
      setItems((await getMemories(status === "all" ? undefined : status, query || undefined)).items);
      setMessage(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Memory unavailable");
    }
  };

  useEffect(() => { void refresh(); }, [status]);

  const action = async (run: () => Promise<unknown>) => {
    try { await run(); await refresh(); } catch (error) { setMessage(error instanceof Error ? error.message : "Memory action failed"); }
  };

  const onCreate = async (event: FormEvent) => {
    event.preventDefault();
    await action(() => createMemory({ predicate, value_text: value, source_message_ids: sourceId ? [sourceId] : [] }));
    setValue("");
  };

  return <section className="panel">
    <div className="panel-heading"><h2>Memory Center</h2><span>{items.filter((item) => item.status === "candidate").length} awaiting review</span><button onClick={() => void refresh()}>Refresh</button></div>
    <div className="filters">{STATUSES.map((item) => <button className={status === item ? "active" : ""} key={item} onClick={() => setStatus(item)}>{item}</button>)}</div>
    <form className="chat-form" onSubmit={(event) => { event.preventDefault(); void refresh(); }}>
      <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search long-term memory" />
      <button type="submit">Search</button>
    </form>
    <form className="form-grid" onSubmit={onCreate}>
      <label>Predicate<input value={predicate} onChange={(event) => setPredicate(event.target.value)} required /></label>
      <label>Memory<input value={value} onChange={(event) => setValue(event.target.value)} required /></label>
      <label>Source message ID<input value={sourceId} onChange={(event) => setSourceId(event.target.value)} required /></label>
      <button type="submit">Add verified memory</button>
    </form>
    <button className="secondary" onClick={() => { if (window.confirm("Delete long-term memories only? Timeline history stays intact.")) void action(clearMemories); }}>Clear memory only</button>
    <button className="secondary" onClick={() => {
      if (window.confirm("Permanently delete ALL conversation history, episode summaries, and long-term memories? This cannot be undone.")) void action(resetAllCompanionData);
    }}>Reset all memory and history</button>
    <button className="secondary" onClick={() => void action(reindexMemories)}>Rebuild FTS index</button>
    {message && <p className="error-text">{message}</p>}
    <div className="event-list">{items.map((memory) => <article className="event-card" key={memory.id}>
      <div><strong>{memory.predicate}: {memory.value_text}</strong><p>{memory.status} · {memory.kind} · source {memory.source_message_ids.join(", ") || "missing"} · used {memory.access_count}×</p></div>
      <div className="avatar-actions">
        {memory.status === "candidate" && <><button onClick={() => void action(() => confirmMemory(memory.id))}>Confirm</button><button className="secondary" onClick={() => void action(() => rejectMemory(memory.id))}>Reject</button></>}
        {memory.status === "deleted" ? <button onClick={() => void action(() => restoreMemory(memory.id))}>Restore</button> : <button className="secondary" onClick={() => void action(() => deleteMemory(memory.id))}>Forget</button>}
        {memory.status !== "deleted" && <button className="secondary" onClick={() => {
          const next = window.prompt("Edit memory", memory.value_text);
          if (next?.trim()) void action(() => updateMemory(memory.id, { value_text: next.trim(), user_locked: true }));
        }}>Edit</button>}
        {memory.status !== "deleted" && !memory.user_locked && <button className="secondary" onClick={() => void action(() => updateMemory(memory.id, { user_locked: true }))}>Pin</button>}
        <button className="secondary" onClick={async () => {
          const nextAudit = await getMemoryAudit(memory.id);
          setAudit((current) => ({ ...current, [memory.id]: nextAudit.items }));
        }}>Why?</button>
      </div>
      {audit[memory.id] && <p>Audit: {audit[memory.id].map((item) => `${item.action} (${item.actor})`).join(" → ")}</p>}
    </article>)}</div>
  </section>;
}
