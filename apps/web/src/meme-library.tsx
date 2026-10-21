import { useEffect, useRef, useState } from "react";
import {
  IconInterfacePlus as Plus,
  IconInterfaceRefresh as RefreshCw,
} from "./CustomIcons";
import { AppDialog } from "./components/AppDialog";
import { MaterialButton } from "./components/MaterialButton";
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
    <header className="meme-library-heading">
      <div><h2>Мемотека</h2><p>Отсылки, значения и источники. Ирис пополняет справочник после поиска о мемах.</p></div>
      <span className="memory-status">{items.length} / {limit}</span>
    </header>
    <div className="meme-library-toolbar">
      <input aria-label="Поиск по мемотеке" placeholder="Найти мем" value={query} onChange={e => setQuery(e.target.value)} />
      <MaterialButton materialKey="memes.refresh" appearance="quiet" aria-label="Обновить мемотеку" disabled={busy} onClick={() => void refresh()}><RefreshCw size={16} /></MaterialButton>
      <MaterialButton materialKey="memes.add" disabled={busy || items.length >= limit} onClick={() => edit("new")}><Plus size={16} />Добавить</MaterialButton>
    </div>
    <p className="meme-library-note">Выдержки поиска требуют проверки. Ручная правка закрепляет значение; отключённые карточки не подсказываются в ответах.</p>
    {error && !editing && !deleting && <p role="alert" className="meme-library-error">{error}</p>}
    {loading ? <LoadingRing /> : <div className="memory-list" ref={list}>
      {filtered.map(card => <article className={`memory-card meme-card${card.enabled ? "" : " is-disabled"}`} key={card.id}>
        <div className="memory-card-main">
          <div className="memory-card-heading"><strong data-i18n-skip>{card.name}</strong><span className="memory-status">{KINDS[card.kind]}</span></div>
          <p data-i18n-skip>{card.summary}</p>
          {card.tags && <small data-i18n-skip>{card.tags}</small>}
          <div className="meme-card-source"><a href={card.source} target="_blank" rel="noopener noreferrer">Источник</a><small>{card.kind === "reviewed" ? "Правка" : card.kind === "search_excerpt" ? "Найдено" : "Проверка"}: {card.checked_at.slice(0, 10)}{card.published_at && ` · Публикация: ${card.published_at}`}</small></div>
        </div>
        <div className="memory-actions">
          <MaterialButton materialKey={`memes.edit:${card.id}`} appearance="quiet" disabled={busy} onClick={() => edit(card)}>Исправить</MaterialButton>
          <MaterialButton materialKey={`memes.toggle:${card.id}`} appearance="quiet" disabled={busy} onClick={() => void run(() => saveMemeCard(card.id, { enabled: !card.enabled }))}>{card.enabled ? "Отключить" : "Включить"}</MaterialButton>
          <MaterialButton materialKey={`memes.delete:${card.id}`} appearance="quiet" disabled={busy} onClick={() => setDeleting(card)}>Удалить</MaterialButton>
        </div>
      </article>)}
      {!filtered.length && <p className="empty-state">{query ? "Ничего не найдено" : "В мемотеке пока нет карточек"}</p>}
    </div>}
    <AppDialog open={editing !== null} title={editing === "new" ? "Добавить мем" : "Исправить мем"} description="Укажите значение, ситуации применения и источник. Карточка будет сохранена как ручная правка." variant="info" onClose={() => { if (!busy) setEditing(null); }}>
      <form onSubmit={e => { e.preventDefault(); if (editing) void run(() => saveMemeCard(editing === "new" ? null : editing.id, form)); }}>
        <div className="meme-edit-fields">
          <label className="form-field"><span>Название или фраза</span><input required maxLength={100} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} data-i18n-skip /></label>
          <label className="form-field"><span>Значение и применение</span><textarea required rows={4} maxLength={400} value={form.summary} onChange={e => setForm({ ...form, summary: e.target.value })} data-i18n-skip /></label>
          <label className="form-field"><span>Ключевые слова</span><input maxLength={250} value={form.tags} onChange={e => setForm({ ...form, tags: e.target.value })} data-i18n-skip /></label>
          <label className="form-field"><span>Источник</span><input required type="url" maxLength={1000} value={form.source} onChange={e => setForm({ ...form, source: e.target.value })} data-i18n-skip /></label>
          {error && <p role="alert">{error}</p>}
        </div>
        <div className="dialog-actions"><MaterialButton materialKey="memes.cancel" type="button" disabled={busy} onClick={() => setEditing(null)}>Отмена</MaterialButton><MaterialButton materialKey="memes.save" type="submit" disabled={busy || !form.name.trim() || !form.summary.trim() || !form.source.trim()}>Сохранить</MaterialButton></div>
      </form>
    </AppDialog>
    <AppDialog open={deleting !== null} title="Удалить карточку мема?" description="Карточка исчезнет из справочника и больше не будет подсказываться в ответах." variant="danger" onClose={() => { if (!busy) setDeleting(null); }}>
      <div className="dialog-actions"><MaterialButton materialKey="memes.delete-cancel" disabled={busy} onClick={() => setDeleting(null)}>Отмена</MaterialButton><MaterialButton materialKey="memes.delete-confirm" disabled={busy} onClick={() => { if (deleting) void run(() => deleteMemeCard(deleting.id)); }}>Удалить</MaterialButton></div>
      {error && <p role="alert">{error}</p>}
    </AppDialog>
  </div>;
}
