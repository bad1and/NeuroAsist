import { useEffect, useRef, useState } from "react";
import {
  IconInterfaceContentFile as FileText,
  IconInterfaceEditAttachment1 as Paperclip,
} from "../CustomIcons";
import { requestJson } from "../api";
import { MaterialButton } from "./MaterialButton";
import { AppDialog } from "./AppDialog";

type AttachedDocument = { id: string; name: string; fragment_count: number; ephemeral: boolean; expires_in_seconds?: number };
type Source = { id: string; label: string; text: string };

export function DocumentAttachment({ sessionId, disabled = false, onBusyChange }: {
  sessionId: string | null; disabled?: boolean; onBusyChange: (busy: boolean) => void;
}) {
  const [document, setDocument] = useState<AttachedDocument | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sourceId, setSourceId] = useState("D1");
  const [source, setSource] = useState<Source | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const active = useRef<{ id: string; session: string; controller: AbortController } | null>(null);
  const generation = useRef(0);
  const documentRef = useRef(document);
  documentRef.current = document;
  const busyRef = useRef(false);
  const changeBusy = (value: boolean) => { busyRef.current = value; setBusy(value); onBusyChange(value); };
  const remove = async (id: string, session: string) => {
    await requestJson(`/documents/${encodeURIComponent(id)}?session_id=${encodeURIComponent(session)}`, { method: "DELETE" });
  };
  const cancelUpload = () => {
    generation.current++;
    const current = active.current;
    active.current = null;
    current?.controller.abort();
    if (current) void remove(current.id, current.session).catch(() => {});
    changeBusy(false);
  };
  useEffect(() => {
    generation.current++;
    setDocument(null); setError(""); setSource(null); changeBusy(false);
    const controller = new AbortController();
    let polling = false;
    const refresh = async () => {
      if (!sessionId || busyRef.current || polling) return;
      polling = true;
      const token = generation.current;
      try {
        const response = await requestJson<{ document: AttachedDocument | null }>(`/documents/current?session_id=${encodeURIComponent(sessionId)}`, { signal: controller.signal });
        if (token !== generation.current) return;
        if (!response.document && documentRef.current) {
          generation.current++; setSource(null);
          setError("Документ больше не доступен. Прикрепите файл заново.");
        }
        setDocument(response.document);
      } catch { /* Keep the attachment through a temporary network outage. */ }
      finally { polling = false; }
    };
    void refresh(); const timer = window.setInterval(() => void refresh(), 30_000);
    window.addEventListener("focus", refresh);
    return () => {
      generation.current++; controller.abort(); clearInterval(timer); window.removeEventListener("focus", refresh);
      const current = active.current; active.current = null;
      current?.controller.abort();
      if (current) void remove(current.id, current.session).catch(() => {});
    };
  }, [sessionId]);
  useEffect(() => {
    if (!document || document.expires_in_seconds == null) return;
    const timer = window.setTimeout(() => { generation.current++; setDocument(null); setSource(null); setError("Документ больше не доступен. Прикрепите файл заново."); }, document.expires_in_seconds * 1000);
    return () => clearTimeout(timer);
  }, [document]);
  const upload = async (file: File) => {
    if (!sessionId) return;
    if (!/\.(txt|md|pdf)$/i.test(file.name) || file.size === 0 || file.size > 10 * 1024 * 1024) {
      setError("Выберите непустой TXT, MD или текстовый PDF до 10 МБ."); return;
    }
    cancelUpload(); setError(""); changeBusy(true);
    const token = generation.current;
    const id = crypto.randomUUID();
    const controller = new AbortController();
    active.current = { id, session: sessionId, controller };
    const body = new FormData(); body.append("session_id", sessionId); body.append("upload_id", id); body.append("file", file);
    try {
      const next = await requestJson<AttachedDocument>("/documents", { method: "POST", body, signal: controller.signal });
      if (token !== generation.current) { void remove(next.id, sessionId).catch(() => {}); return; }
      setDocument(next); setSourceId("D1"); setSource(null);
    } catch (cause) { if (!controller.signal.aborted && token === generation.current) setError(cause instanceof Error ? cause.message : "Не удалось прочитать документ"); }
    finally { if (token === generation.current) { active.current = null; changeBusy(false); } }
  };
  const inspectSource = async () => {
    if (!document || !sessionId) return;
    setError("");
    const token = generation.current;
    try { const next = await requestJson<Source>(`/documents/${encodeURIComponent(document.id)}/sources/${encodeURIComponent(sourceId)}?session_id=${encodeURIComponent(sessionId)}`); if (token === generation.current) setSource(next); }
    catch (cause) { if (token === generation.current) setError(cause instanceof Error ? cause.message : "Фрагмент недоступен"); }
  };
  return <div className="document-attachment">
    <input ref={input} type="file" accept=".txt,.md,.pdf" hidden aria-label="Выбрать документ" onChange={event => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void upload(file); }} />
    <MaterialButton materialKey="document.attach" appearance="quiet" className="icon-button" type="button" aria-label="Приложить документ" title="TXT, MD или текстовый PDF" disabled={disabled || !sessionId || busy} onClick={() => input.current?.click()}><Paperclip size={18} /></MaterialButton>
    {(document || busy || error) && <div className="document-attachment-popover">
      {busy ? <><span role="status">Читаю документ…</span><MaterialButton materialKey="document.cancel" className="text-button" type="button" onClick={cancelUpload}>Отменить чтение</MaterialButton></> : document && <details>
        <summary data-i18n-skip>{document.name}</summary><small>Файл используется в этой беседе. Подходящие фрагменты отправляются внешней модели и не добавляются в личную память автоматически. В истории сохраняются ответ и ссылки на источники, без скрытых копий исходного текста. После удаления, перезапуска Iris или через 2 часа файл нужно прикрепить заново.</small>
        <div className="document-source-actions"><label>Проверить ссылку из ответа<input aria-label="ID фрагмента документа" value={sourceId} onChange={event => setSourceId(event.target.value.toUpperCase().replace(/[^D0-9]/g, ""))} onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); event.stopPropagation(); void inspectSource(); } }} placeholder="D1" /></label><MaterialButton materialKey="document.inspect" className="text-button" type="button" onClick={() => void inspectSource()}>Открыть фрагмент</MaterialButton><MaterialButton materialKey="document.remove" className="text-button" type="button" disabled={disabled} onClick={() => { if (sessionId) { changeBusy(true); void remove(document.id, sessionId).then(() => { generation.current++; setDocument(null); setSource(null); }).catch(cause => setError(String(cause))).finally(() => changeBusy(false)); } }}>Убрать из беседы</MaterialButton></div>
      </details>}
      {error && <p className="error-text" role="alert">{error}</p>}
    </div>}
    <AppDialog open={Boolean(source)} onClose={() => setSource(null)} title={source ? `${source.id} · ${source.label}` : "Фрагмент документа"} icon={<FileText size={24} aria-hidden="true" />} variant="info"><p className="document-source-text" data-i18n-skip>{source?.text}</p></AppDialog>
  </div>;
}
