import { useState } from "react";
import {
  IconInterfaceBrain as Brain,
} from "../CustomIcons";
import { requestJson, updateMemory } from "../api";
import type { MemoryItem } from "../types";
import { AppDialog } from "./AppDialog";
import { MaterialButton } from "./MaterialButton";

type ContextRecord = { id: string; value: string; predicate: string; current: MemoryItem | null };

function ContextRecordRow({ item, sessionId }: { item: ContextRecord; sessionId?: string | null }) {
  const [text, setText] = useState(item.current?.value_text || item.value);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const run = async (action: () => Promise<unknown>, message: string) => {
    setBusy(true); setError("");
    try { await action(); setNotice(message); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Не удалось изменить запись"); }
    finally { setBusy(false); }
  };
  return <article className="context-record">
    <p data-i18n-skip>{item.value}</p>
    <small>Входной контекст этого ответа</small>
    {!item.current ? <p className="settings-apply-note">Запись уже удалена. Показан сохранённый фрагмент контекста.</p> : <>
      {item.current.value_text !== item.value && <p className="settings-apply-note">После ответа запись была изменена.</p>}
      <details><summary>Исправить текущую запись</summary><textarea aria-label="Новое значение записи памяти" value={text} maxLength={2000} rows={3} onChange={event => setText(event.target.value)} /><MaterialButton materialKey={`context.save.${item.id}`} className="secondary" type="button" disabled={busy || !text.trim()} onClick={() => void run(() => updateMemory(item.id, { value_text: text }), "Текущая запись исправлена. Снимок старого ответа сохранён.")}>Сохранить исправление</MaterialButton></details>
      <MaterialButton materialKey={`context.exclude.${item.id}`} className="text-button" type="button" disabled={busy || !sessionId} onClick={() => void run(() => requestJson("/memory-context/exclude-next", { method: "POST", body: JSON.stringify({ session_id: sessionId, memory_id: item.id }) }), "Запись исключена из следующего контекста текущего разговора.")}>Исключить из следующего ответа</MaterialButton>
    </>}
    {error && <p className="error-text" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
  </article>;
}

export function MemoryContextDetails({ messageId, count, sessionId }: { messageId: string; count: number; sessionId?: string | null }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<ContextRecord[] | null>(null);
  const [error, setError] = useState("");
  const show = async () => {
    setOpen(true); setError(""); setItems(null);
    try { const response = await requestJson<{ items: ContextRecord[] }>(`/memory-context/${encodeURIComponent(messageId)}`); setItems(response.items); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Контекст недоступен"); }
  };
  return <>
    <MaterialButton materialKey={`context.open.${messageId}`} className="text-button" type="button" onClick={event => { event.stopPropagation(); void show(); }}>В контексте {count} записей памяти · DEV</MaterialButton>
    <AppDialog open={open} onClose={() => setOpen(false)} title="Память во входном контексте" icon={<Brain size={24} aria-hidden="true" />} variant="info" size="wide">
      <div className="memory-context-details"><p className="settings-apply-note">Это фактические записи, переданные модели. Список не доказывает, что каждый факт повлиял на формулировку ответа. Новые сохранения показаны отдельно в деталях сообщения. Исключение отключает одну запись памяти на следующий ход; тот же факт может оставаться в истории разговора.</p>
        {error && <p className="error-text" role="alert">{error}</p>}{!items && !error && <p role="status">Загружаю контекст…</p>}
        {items?.map(item => <ContextRecordRow key={item.id} item={item} sessionId={sessionId} />)}
      </div>
    </AppDialog>
  </>;
}

export function DocumentSources({ value }: { value: unknown }) {
  if (!value || typeof value !== "object") return null;
  const data = value as { name?: string; partial?: boolean; sources?: Array<{ id: string; label: string; text?: string }> };
  if (!Array.isArray(data.sources)) return null;
  const sources = data.sources.filter(source => source && typeof source.id === "string" && typeof source.label === "string");
  return <details className="document-sources" onClick={event => event.stopPropagation()}><summary>Документ: <span data-i18n-skip>{typeof data.name === "string" ? data.name : "Файл"}</span> · {sources.length} фрагментов</summary>
    {data.partial && <p className="settings-apply-note">В ответ были переданы выбранные части документа.</p>}
    {sources.map(source => <details key={source.id}><summary>{source.id} · {source.label}</summary>{typeof source.text === "string"
      ? <p className="document-source-text" data-i18n-skip>{source.text}</p>
      : <p className="settings-apply-note">Исходный текст не сохраняется в истории. Пока вложение доступно, откройте фрагмент через скрепку в беседе; после удаления или истечения срока прикрепите файл заново.</p>}</details>)}
  </details>;
}
