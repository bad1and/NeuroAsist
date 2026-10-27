import { useEffect, useRef, useState } from "react";
import { IconCitiesPoliticsVote, IconInterfaceClock, IconInterfaceTextFormattingTextStyle } from "./CustomIcons";
import { AppDialog } from "./components/AppDialog";
import { MaterialButton } from "./components/MaterialButton";
import { MemoryCollectionToolbar } from "./components/MemoryCollectionToolbar";
import { LoadingRing } from "./components/LoadingRing";
import { animateStaggerCards } from "./animations";
import { getOpinions, getOpinionHistory, saveOpinion, toggleOpinion } from "./api";
import type { IrisOpinion, OpinionRevision } from "./types";
import { interfaceIntlLocale } from "./i18n";
import "./meme-library.css";

const EMPTY = { topic: "", stance: "", reason: "", aliases: "" };
const ORIGINS = { default: "Исходная позиция", iris: "Из разговора", developer: "Правка разработчика" };

export function OpinionsPanel() {
  const [items, setItems] = useState<IrisOpinion[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<IrisOpinion | "new" | null>(null);
  const [form, setForm] = useState(EMPTY);
  const [history, setHistory] = useState<{ topic: string; items: OpinionRevision[] } | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const alive = useRef(true);
  const revision = useRef(0);
  const historyRevision = useRef(0);
  const list = useRef<HTMLDivElement>(null);
  const refresh = async () => {
    const current = ++revision.current;
    try {
      const data = await getOpinions();
      if (alive.current && current === revision.current) { setItems(data.items); setError(""); }
    } catch (e) {
      if (alive.current && current === revision.current) setError(e instanceof Error ? e.message : "Взгляды Iris недоступны");
    } finally { if (alive.current && current === revision.current) setLoading(false); }
  };
  useEffect(() => { alive.current = true; void refresh(); return () => { alive.current = false; revision.current++; historyRevision.current++; }; }, []);
  useEffect(() => { if (list.current && !loading) animateStaggerCards(list.current, ".memory-card", 25); }, [items, loading]);
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await action(); if (alive.current) { setEditing(null); await refresh(); } }
    catch (e) { if (alive.current) setError(e instanceof Error ? e.message : "Не удалось сохранить позицию"); }
    finally { if (alive.current) setBusy(false); }
  };
  const edit = (item: IrisOpinion | "new") => {
    setEditing(item); setError("");
    setForm(item === "new" ? EMPTY : { topic: item.topic, stance: item.stance, reason: "", aliases: item.aliases.join(", ") });
  };
  const showHistory = async (item: IrisOpinion) => {
    const current = ++historyRevision.current;
    setHistory({ topic: item.topic, items: [] }); setHistoryLoading(true); setError("");
    try {
      const data = await getOpinionHistory(item.id);
      if (alive.current && current === historyRevision.current) setHistory({ topic: item.topic, items: data.items });
    } catch (e) { if (alive.current && current === historyRevision.current) setError(e instanceof Error ? e.message : "История недоступна"); }
    finally { if (alive.current && current === historyRevision.current) setHistoryLoading(false); }
  };
  const filtered = items.filter(item => `${item.topic} ${item.stance} ${item.aliases.join(" ")}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <div className="meme-library-panel opinions-panel">
    <MemoryCollectionToolbar materialKey="opinions" query={query} onQueryChange={setQuery} searchLabel="Поиск по взглядам" placeholder="Найти тему" refreshLabel="Обновить взгляды" onRefresh={() => void refresh()} onAdd={() => edit("new")} busy={busy} />
    <p className="meme-library-note">Прежние позиции остаются в истории. Отключённые взгляды Iris не использует в разговоре.</p>
    {error && !editing && !history && <p role="alert" className="meme-library-error">{error}</p>}
    {loading ? <LoadingRing /> : <div className="memory-list" ref={list}>
      {filtered.map(item => <article className={`memory-card memory-collection-card opinion-card${item.enabled ? "" : " is-disabled"}`} key={item.id}>
        <div className="memory-card-main">
          <div className="memory-card-heading">
            <div className="memory-card-label"><IconCitiesPoliticsVote size={14} aria-hidden="true" /><strong data-i18n-skip>{item.topic}</strong></div>
            {!item.enabled && <span className="memory-status inactive">Отключено</span>}
          </div>
          <p className="memory-fact-value" data-i18n-skip>{item.stance}</p>
          <p className="opinion-reason" data-i18n-skip>{item.reason}</p>
          <div className="memory-record-footer">
            <div className="memory-record-meta"><span>{ORIGINS[item.origin]}</span><span>Версия {item.revision}</span><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleDateString(interfaceIntlLocale(), { day: "numeric", month: "long", year: "numeric" })}</time></div>
            <div className="memory-record-controls">
              <MaterialButton materialKey={`opinions.edit:${item.id}`} className="secondary" disabled={busy} onClick={() => edit(item)}><IconInterfaceTextFormattingTextStyle size={15} aria-hidden="true" />Пересмотреть</MaterialButton>
              <MaterialButton materialKey={`opinions.history:${item.id}`} className="secondary" onClick={() => void showHistory(item)}><IconInterfaceClock size={15} aria-hidden="true" />История изменений</MaterialButton>
              <MaterialButton materialKey={`opinions.toggle:${item.id}`} className="secondary" appearance="quiet" disabled={busy} onClick={() => void run(() => toggleOpinion(item.id, !item.enabled, item.revision))}>{item.enabled ? "Отключить" : "Включить"}</MaterialButton>
            </div>
          </div>
        </div>
      </article>)}
      {!filtered.length && <div className="empty-state"><IconCitiesPoliticsVote size={28} aria-hidden="true" /><strong>{query ? "Ничего не найдено" : "Взглядов пока нет"}</strong><span>{query ? "Попробуйте другую тему." : "Здесь появятся позиции Iris из ваших разговоров."}</span></div>}
    </div>}
    <AppDialog open={editing !== null} title={editing === "new" ? "Добавить позицию" : "Пересмотреть позицию"} description="Укажите позицию и причину. Прежняя версия сохранится в истории." variant="info" onClose={() => { if (!busy) setEditing(null); }}>
      <form onSubmit={e => { e.preventDefault(); if (editing) void run(() => saveOpinion({ ...form, aliases: form.aliases.split(",").map(s => s.trim()).filter(Boolean), id: editing === "new" ? null : editing.id, expected_revision: editing === "new" ? 0 : editing.revision })); }}>
        <div className="meme-edit-fields">
          <label className="form-field"><span>Тема</span><input required minLength={2} maxLength={80} value={form.topic} onChange={e => setForm({ ...form, topic: e.target.value })} data-i18n-skip /></label>
          <label className="form-field"><span>Позиция Iris</span><textarea required minLength={3} maxLength={320} rows={3} value={form.stance} onChange={e => setForm({ ...form, stance: e.target.value })} data-i18n-skip /></label>
          <label className="form-field"><span>Причина</span><textarea required minLength={3} maxLength={240} rows={2} value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })} data-i18n-skip /></label>
          <label className="form-field"><span>Другие названия темы через запятую</span><input maxLength={360} value={form.aliases} onChange={e => setForm({ ...form, aliases: e.target.value })} data-i18n-skip /></label>
          {error && <p role="alert">{error}</p>}
        </div>
        <div className="dialog-actions"><MaterialButton materialKey="opinions.cancel" type="button" disabled={busy} onClick={() => setEditing(null)}>Отмена</MaterialButton><MaterialButton materialKey="opinions.save" className="primary-button" type="submit" disabled={busy || !form.topic.trim() || !form.stance.trim() || !form.reason.trim()}>Сохранить</MaterialButton></div>
      </form>
    </AppDialog>
    <AppDialog open={history !== null} title="История изменений" variant="info" onClose={() => { historyRevision.current++; setHistory(null); }}>
      <p data-i18n-skip>{history?.topic}</p>
      {historyLoading ? <LoadingRing /> : <div className="opinion-history">{history?.items.map(item => <article className="opinion-history-entry" key={item.revision}><div className="memory-record-meta"><span>Версия {item.revision}</span><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString(interfaceIntlLocale())}</time><span>{ORIGINS[item.origin]}</span></div><p data-i18n-skip>{item.stance}</p><small data-i18n-skip>{item.reason}</small></article>)}</div>}
      {error && <p role="alert">{error}</p>}
    </AppDialog>
  </div>;
}
