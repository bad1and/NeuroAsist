import { useEffect, useRef, useState } from "react";
import {
  IconInterfaceSearch as Search,
} from "../CustomIcons";
import { requestJson } from "../api";
import type { MemoryItem, MemoryCommitment, TimelineMessage } from "../types";
import { AppDialog } from "./AppDialog";
import { searchSettings, type SearchDestination } from "../search-navigation";

type Result = { id: string; group: string; title: string; excerpt: string; destination: SearchDestination; titleIsUserText?: boolean; excerptIsUserText?: boolean };
const focus = (id: string, query: string) => ({ id, query, requestId: crypto.randomUUID() });

export function GlobalSearch({ open, developerMode, onClose, onSelect }: {
  open: boolean; developerMode: boolean; onClose: () => void; onSelect: (destination: SearchDestination) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Result[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [unavailable, setUnavailable] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const text = query.trim();
    setActiveIndex(0); setUnavailable([]);
    const settings: Result[] = searchSettings(text, developerMode).slice(0, 8).map(item => ({ id: `setting.${item.section}`, group: "Настройки", title: item.title, excerpt: "Открыть раздел", destination: { kind: "setting", section: item.section } }));
    setResults(settings);
    if (!text) { setLoading(false); return; }
    setLoading(true);
    const timer = setTimeout(async () => {
      const q = encodeURIComponent(text);
      const replies = await Promise.allSettled([
        requestJson<{ items: TimelineMessage[] }>(`/timeline/search?q=${q}&limit=8`, { signal: controller.signal }),
        requestJson<{ items: MemoryItem[] }>(`/memory?status=active&q=${q}&limit=8`, { signal: controller.signal }),
        requestJson<{ items: MemoryCommitment[] }>(`/memory/commitments?status=open&q=${q}`, { signal: controller.signal }),
      ]);
      if (controller.signal.aborted) return;
      const found: Result[] = [];
      const [history, memory, plans] = replies;
      if (history.status === "fulfilled") found.push(...history.value.items.filter(item => item.role !== "system_event").map(item => ({ id: `history.${item.id}`, group: "История", title: `${item.role === "user" ? "Вы" : "Iris"} · ${new Date(item.created_at).toLocaleDateString()}`, excerpt: item.content || item.corrected_content || item.original_content, excerptIsUserText: true, destination: { kind: "history" as const, focus: focus(item.id, text) } })));
      if (memory.status === "fulfilled") found.push(...memory.value.items.map(item => ({ id: `memory.${item.id}`, group: "Память", title: "Сохранённый факт", excerpt: item.value_text, excerptIsUserText: true, destination: { kind: "memory" as const, focus: { ...focus(item.id, text), section: "all" as const } } })));
      if (plans.status === "fulfilled") found.push(...plans.value.items.slice(0, 8).map(item => ({ id: `plan.${item.id}`, group: "Планы", title: item.title, excerpt: item.details || "Предстоящий план", titleIsUserText: true, excerptIsUserText: Boolean(item.details), destination: { kind: "memory" as const, focus: { ...focus(item.id, text), section: "commitments" as const } } })));
      setUnavailable(replies.flatMap((reply, index) => reply.status === "rejected" ? [["история", "память", "планы"][index]] : []));
      setResults([...settings, ...found]); setLoading(false);
    }, 180);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [open, query, developerMode]);
  useEffect(() => { if (open) inputRef.current?.focus(); }, [open]);
  useEffect(() => { if (open) document.getElementById(`iris-search-option-${activeIndex}`)?.scrollIntoView?.({ block: "nearest", behavior: "instant" }); }, [activeIndex, open]);
  const choose = (result: Result) => { onClose(); onSelect(result.destination); };
  return <AppDialog open={open} onClose={onClose} title="Найти в Iris" icon={<Search size={24} aria-hidden="true" />} variant="info" size="wide">
    {open && <div className="global-search">
      <input ref={inputRef} autoFocus value={query} maxLength={200} onChange={event => setQuery(event.target.value)} placeholder="Разговоры, память, планы и настройки" aria-label="Поиск в Iris" role="combobox" aria-expanded="true" aria-autocomplete="list" aria-controls="iris-search-results" aria-activedescendant={results[activeIndex] ? `iris-search-option-${activeIndex}` : undefined} onKeyDown={event => {
        if (event.nativeEvent.isComposing) return;
        if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); setActiveIndex(index => results.length ? (index + (event.key === "ArrowDown" ? 1 : -1) + results.length) % results.length : 0); }
        if (event.key === "Enter" && results[activeIndex]) { event.preventDefault(); choose(results[activeIndex]); }
      }} />
      {loading && <p role="status">Ищу…</p>}
      {unavailable.length > 0 && <p className="settings-apply-note">Сейчас недоступны: {unavailable.join(", ")}. Остальные результаты показаны.</p>}
      <ul id="iris-search-results" role="listbox" aria-label="Результаты поиска">{results.map((result, index) => <li key={result.id} id={`iris-search-option-${index}`} role="option" aria-selected={activeIndex === index} onMouseDown={event => event.preventDefault()} onClick={() => choose(result)}><small>{result.group}</small><strong data-i18n-skip={result.titleIsUserText || undefined}>{result.title}</strong><span data-i18n-skip={result.excerptIsUserText || undefined}>{result.excerpt}</span></li>)}</ul>
      {!loading && !results.length && <p>Ничего не найдено. Попробуйте другое слово.</p>}
      <p className="settings-apply-note">↑ ↓ — выбрать · Enter — открыть · Escape — закрыть</p>
    </div>}
  </AppDialog>;
}
