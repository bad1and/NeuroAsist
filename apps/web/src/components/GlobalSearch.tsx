import { Fragment, useEffect, useRef, useState } from "react";
import {
  IconInterfaceCross as Cross,
  IconInterfaceArrowRight as ArrowRight,
  IconInterfaceClock as Clock,
  IconInterfaceBookmark as Bookmark,
  IconInterfaceCalendarMark as Calendar,
  IconInterfacePageControllerSettings as Settings,
} from "../CustomIcons";
import { requestJson } from "../api";
import type { MemoryItem, MemoryCommitment, TimelineMessage } from "../types";
import { AppDialog } from "./AppDialog";
import { searchSettings, type SearchDestination } from "../search-navigation";
import { MaterialButton } from "./MaterialButton";
import { buttonSeed } from "./buttonMaterial";

type Result = { id: string; group: string; title: string; excerpt: string; destination: SearchDestination; titleIsUserText?: boolean; excerptIsUserText?: boolean };
const focus = (id: string, query: string) => ({ id, query, requestId: crypto.randomUUID() });
const categories = ["Все", "История", "Память", "Планы", "Настройки"] as const;
const categoryButtonSeed = buttonSeed("search.categories");
const groupIcons = { История: Clock, Память: Bookmark, Планы: Calendar, Настройки: Settings };

function Highlight({ text, query }: { text: string; query: string }) {
  const needle = query.trim();
  if (needle.length < 2) return <>{text}</>;
  const index = text.toLocaleLowerCase().indexOf(needle.toLocaleLowerCase());
  if (index < 0) return <>{text}</>;
  return <>{text.slice(0, index)}<mark>{text.slice(index, index + needle.length)}</mark>{text.slice(index + needle.length)}</>;
}

export function GlobalSearch({ open, developerMode, onClose, onSelect }: {
  open: boolean; developerMode: boolean; onClose: () => void; onSelect: (destination: SearchDestination) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Result[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [unavailable, setUnavailable] = useState<string[]>([]);
  const [category, setCategory] = useState<typeof categories[number]>("Все");
  const inputRef = useRef<HTMLInputElement>(null);
  const visibleResults = category === "Все" ? results : results.filter(result => result.group === category);
  const activeResult = visibleResults[activeIndex];
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
  useEffect(() => { if (open) document.getElementById(`iris-search-option-${activeIndex}`)?.scrollIntoView?.({ block: "nearest", behavior: "instant" }); }, [activeIndex, open, category, results]);
  const choose = (result: Result) => { onClose(); onSelect(result.destination); };
  const clear = () => { setQuery(""); setCategory("Все"); setActiveIndex(0); inputRef.current?.focus(); };
  const searchField = <div className="spotlight-search-field">
      <input ref={inputRef} autoFocus value={query} maxLength={200} onChange={event => setQuery(event.target.value)} placeholder="Найти в Iris" aria-label="Поиск в Iris" role="combobox" aria-expanded="true" aria-autocomplete="list" aria-controls="iris-search-results" aria-activedescendant={activeResult ? `iris-search-option-${activeIndex}` : undefined} onKeyDown={event => {
        if (event.nativeEvent.isComposing) return;
        if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); setActiveIndex(index => visibleResults.length ? (index + (event.key === "ArrowDown" ? 1 : -1) + visibleResults.length) % visibleResults.length : 0); }
        if (event.key === "Enter" && activeResult) { event.preventDefault(); choose(activeResult); }
      }} />
      {query && <MaterialButton materialKey="search.clear" appearance="plain" className="spotlight-clear" type="button" aria-label="Очистить поиск" title="Очистить поиск" onClick={clear}><span className="spotlight-clear-glyph" aria-hidden="true"><Cross size={10} /></span></MaterialButton>}
    </div>;
  return <AppDialog open={open} onClose={onClose} title="Найти в Iris" headerContent={searchField} variant="info" size="wide" presentation="spotlight">
    {open && <div className="global-search">
      <div className="spotlight-categories" role="group" aria-label="Где искать">{categories.map(item => <MaterialButton key={item} materialKey={`search.category.${item}`} seed={categoryButtonSeed} appearance="lens" className={category === item ? "is-active" : undefined} type="button" aria-pressed={category === item} onClick={() => { setCategory(item); setActiveIndex(0); inputRef.current?.focus(); }}>{item}</MaterialButton>)}</div>
      <div className="spotlight-results-area">
        {loading && <p className="spotlight-status" role="status">Ищу…</p>}
        {unavailable.length > 0 && <p className="spotlight-status is-warning" role="status">Сейчас недоступны: {unavailable.join(", ")}. Остальные результаты показаны.</p>}
        <ul id="iris-search-results" role="listbox" aria-label="Результаты поиска" aria-busy={loading}>{visibleResults.map((result, index) => {
          const Icon = groupIcons[result.group as keyof typeof groupIcons] ?? Settings;
          return <Fragment key={result.id}>
            {query.trim() && (index === 0 || visibleResults[index - 1].group !== result.group) && <li role="presentation" className="spotlight-section-label">{result.group}</li>}
            <li className="spotlight-result" id={`iris-search-option-${index}`} role="option" aria-selected={activeIndex === index} onMouseDown={event => event.preventDefault()} onMouseEnter={() => setActiveIndex(index)} onClick={() => choose(result)}>
              <div className="spotlight-result-icon" aria-hidden="true"><Icon size={18} /></div>
              <div className="spotlight-result-copy"><strong data-i18n-skip={result.titleIsUserText || undefined}>{result.titleIsUserText ? <Highlight text={result.title} query={query} /> : result.title}</strong>{result.destination.kind !== "setting" && <span data-i18n-skip={result.excerptIsUserText || undefined}>{result.excerptIsUserText ? <Highlight text={result.excerpt} query={query} /> : result.excerpt}</span>}</div>
              <ArrowRight className="spotlight-result-arrow" size={16} aria-hidden="true" />
            </li>
          </Fragment>;
        })}</ul>
        {!loading && !visibleResults.length && <div className="spotlight-empty"><strong>{query.trim() ? "Ничего не найдено" : "Что найдём?"}</strong><p>{query.trim() ? "Попробуйте другое слово или выберите другой раздел." : "Начните вводить, чтобы найти разговор, факт или план."}</p></div>}
      </div>
    </div>}
  </AppDialog>;
}
