import { useEffect, useRef, useState } from "react";
import {
  IconInterfaceBookOpen,
  IconInterfaceArrowUpRight,
  IconInterfaceTextFormattingTextStyle,
  IconInterfaceDeleteBin3,
} from "./CustomIcons";
import { AppDialog } from "./components/AppDialog";
import { MaterialButton } from "./components/MaterialButton";
import { MemoryCollectionToolbar } from "./components/MemoryCollectionToolbar";
import { LoadingRing } from "./components/LoadingRing";
import { animateStaggerCards } from "./animations";
import { deleteMemeCard, getMemeLibrary, saveMemeCard } from "./api";
import type { MemeCard } from "./types";
import "./meme-library.css";

const KINDS = { curated: "Исходная карточка", search_excerpt: "Из поиска", reviewed: "Ручная правка" };
const EMPTY = { name: "", summary: "", tags: "", source: "" };

export function MemeLibraryPanel() {
  const [items, setItems] = useState<MemeCard[]>([]);
  const [limit, setLimit] = useState(48);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<MemeCard | "new" | null>(null);
  const [deleting, setDeleting] = useState<MemeCard | null>(null);
  const [form, setForm] = useState(EMPTY);
  const list = useRef<HTMLDivElement>(null);
  const alive = useRef(true);
  const revision = useRef(0);

  const refresh = async () => {
    const current = ++revision.current;
    try {
      const data = await getMemeLibrary();
      if (!alive.current || current !== revision.current) return;
      setItems(data.items); setLimit(data.limit); setError("");
    } catch (e) {
      if (alive.current && current === revision.current) setError(e instanceof Error ? e.message : "Мемотека недоступна");
    } finally {
      if (alive.current && current === revision.current) setLoading(false);
    }
  };
  useEffect(() => { alive.current = true; void refresh(); return () => { alive.current = false; revision.current += 1; }; }, []);
  useEffect(() => { if (list.current && !loading) animateStaggerCards(list.current, ".memory-card", 25); }, [items, loading]);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await action(); if (alive.current) { setEditing(null); setDeleting(null); await refresh(); } }
    catch (e) { if (alive.current) setError(e instanceof Error ? e.message : "Не удалось сохранить карточку"); }
    finally { if (alive.current) setBusy(false); }
  };
  const edit = (card: MemeCard | "new") => {
    setForm(card === "new" ? EMPTY : { name: card.name, summary: card.summary, tags: card.tags, source: card.source });
    setEditing(card); setError("");
  };
  const filtered = items.filter(c => `${c.name} ${c.summary} ${c.tags}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));

  return <div className="meme-library-panel">
    <MemoryCollectionToolbar materialKey="memes" query={query} onQueryChange={setQuery} searchLabel="Поиск по мемотеке" placeholder="Найти мем" refreshLabel="Обновить мемотеку" onRefresh={() => void refresh()} onAdd={() => edit("new")} busy={busy} addDisabled={items.length >= limit} count={`${items.length} / ${limit}`} />
    <p className="meme-library-note">Проверьте найденные значения и исправьте ошибки. Отключите карточку, чтобы Iris её не использовала.</p>
    {error && !editing && !deleting && <p role="alert" className="meme-library-error">{error}</p>}
    {loading ? <LoadingRing /> : <div className="memory-list" ref={list}>
      {filtered.map(card => <article className={`memory-card memory-collection-card meme-card${card.enabled ? "" : " is-disabled"}`} key={card.id}>
        <div className="memory-card-main">
          <div className="memory-card-heading">
            <div className="memory-card-label"><IconInterfaceBookOpen size={14} aria-hidden="true" /><strong data-i18n-skip>{card.name}</strong></div>
            {!card.enabled && <span className="memory-status inactive">Отключено</span>}
          </div>
          <p className="memory-fact-value" data-i18n-skip>{card.summary}</p>
          <div className="memory-record-footer">
            <div className="memory-record-meta"><span>{KINDS[card.kind]}</span>{card.tags && <span data-i18n-skip>{card.tags}</span>}<span>{card.kind === "reviewed" ? "Исправлено:" : card.kind === "search_excerpt" ? "Найдено:" : "Проверено:"} <time dateTime={card.checked_at}>{card.checked_at.slice(0, 10)}</time></span>{card.published_at && <span>Опубликовано: <span data-i18n-skip>{card.published_at}</span></span>}</div>
            <div className="memory-record-controls">
              <MaterialButton materialKey={`memes.edit:${card.id}`} className="secondary" disabled={busy} onClick={() => edit(card)}><IconInterfaceTextFormattingTextStyle size={15} aria-hidden="true" />Исправить</MaterialButton>
              <MaterialButton materialKey={`memes.toggle:${card.id}`} className="secondary" disabled={busy} onClick={() => void run(() => saveMemeCard(card.id, { enabled: !card.enabled }))}>{card.enabled ? "Отключить" : "Включить"}</MaterialButton>
              <MaterialButton materialKey={`memes.delete:${card.id}`} className="secondary" appearance="quiet" disabled={busy} onClick={() => setDeleting(card)}><IconInterfaceDeleteBin3 size={15} aria-hidden="true" />Удалить</MaterialButton>
              <a className="memory-collection-source" href={card.source} target="_blank" rel="noopener noreferrer">Источник<IconInterfaceArrowUpRight size={14} aria-hidden="true" /></a>
            </div>
          </div>
        </div>
      </article>)}
      {!filtered.length && <div className="empty-state"><IconInterfaceBookOpen size={28} aria-hidden="true" /><strong>{query ? "Ничего не найдено" : "В мемотеке пока нет карточек"}</strong><span>{query ? "Попробуйте другое слово." : "Добавьте мем или отсылку для разговоров с Iris."}</span></div>}
    </div>}
    <AppDialog open={editing !== null} title={editing === "new" ? "Добавить мем" : "Исправить мем"} description="Укажите значение, примеры использования и источник." variant="info" onClose={() => { if (!busy) setEditing(null); }}>
      <form onSubmit={e => { e.preventDefault(); if (editing) void run(() => saveMemeCard(editing === "new" ? null : editing.id, form)); }}>
        <div className="meme-edit-fields">
          <label className="form-field"><span>Название или фраза</span><input required maxLength={100} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} data-i18n-skip /></label>
          <label className="form-field"><span>Значение и применение</span><textarea required rows={4} maxLength={400} value={form.summary} onChange={e => setForm({ ...form, summary: e.target.value })} data-i18n-skip /></label>
          <label className="form-field"><span>Ключевые слова</span><input maxLength={250} value={form.tags} onChange={e => setForm({ ...form, tags: e.target.value })} data-i18n-skip /></label>
          <label className="form-field"><span>Источник</span><input required type="url" maxLength={1000} value={form.source} onChange={e => setForm({ ...form, source: e.target.value })} data-i18n-skip /></label>
          {error && <p role="alert">{error}</p>}
        </div>
        <div className="dialog-actions"><MaterialButton materialKey="memes.cancel" type="button" disabled={busy} onClick={() => setEditing(null)}>Отмена</MaterialButton><MaterialButton materialKey="memes.save" className="primary-button" type="submit" disabled={busy || !form.name.trim() || !form.summary.trim() || !form.source.trim()}>Сохранить</MaterialButton></div>
      </form>
    </AppDialog>
    <AppDialog open={deleting !== null} title="Удалить карточку мема?" description="Карточка исчезнет из справочника и больше не будет подсказываться в ответах." variant="danger" onClose={() => { if (!busy) setDeleting(null); }}>
      <div className="dialog-actions"><MaterialButton materialKey="memes.delete-cancel" disabled={busy} onClick={() => setDeleting(null)}>Отмена</MaterialButton><MaterialButton materialKey="memes.delete-confirm" className="danger-button" disabled={busy} onClick={() => { if (deleting) void run(() => deleteMemeCard(deleting.id)); }}>Удалить</MaterialButton></div>
      {error && <p role="alert">{error}</p>}
    </AppDialog>
  </div>;
}
