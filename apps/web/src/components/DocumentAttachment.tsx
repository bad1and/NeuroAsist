import { Disclosure } from "./Disclosure";
import { useEffect, useRef, useState } from "react";
import {
  IconInterfaceContentFile as FileText,
  IconInterfaceEditAttachment1 as Paperclip,
} from "../CustomIcons";
import { requestJson } from "../api";
import { MaterialButton } from "./MaterialButton";
import { AppDialog } from "./AppDialog";
import { animateButtonPress } from "../animations";
import { notify } from "../notifications";

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
  const [detailsOpen, setDetailsOpen] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const noticeId = useRef<string | null>(null);
  const active = useRef<{ id: string; session: string; controller: AbortController } | null>(null);
  const generation = useRef(0);
  const documentRef = useRef(document);
  documentRef.current = document;
  const busyRef = useRef(false);
  const changeBusy = (value: boolean) => { busyRef.current = value; setBusy(value); onBusyChange(value); };
  const dismissNotice = () => {
    if (noticeId.current) notify.dismiss(noticeId.current);
    noticeId.current = null;
  };
  const chooseFile = () => {
    if (!input.current || button.current?.disabled) return;
    setDetailsOpen(false);
    input.current.click();
  };
  const reportFailure = (message: string, title = "Не удалось прикрепить документ") => {
    setError(message);
    dismissNotice();
    noticeId.current = notify.error(title, message, {
      actions: [{ label: "Выбрать файл", onClick: chooseFile }],
    });
  };
  const remove = async (id: string, session: string) => {
    await requestJson(`/documents/${encodeURIComponent(id)}?session_id=${encodeURIComponent(session)}`, { method: "DELETE" });
  };
  const cancelUpload = () => {
    generation.current++;
    const current = active.current;
    active.current = null;
    current?.controller.abort();
    if (current) void remove(current.id, current.session).catch(() => {});
    dismissNotice();
    changeBusy(false);
  };
  useEffect(() => {
    generation.current++;
    setDocument(null); setError(""); setSource(null); setDetailsOpen(false); changeBusy(false);
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
          setDetailsOpen(false);
          reportFailure("Документ больше не доступен. Прикрепите файл заново.", "Документ недоступен");
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
      dismissNotice();
    };
  }, [sessionId]);
  useEffect(() => {
    if (!document || document.expires_in_seconds == null) return;
    const timer = window.setTimeout(() => {
      setDocument(null); setSource(null); setDetailsOpen(false);
      // An older file expiring must not invalidate its replacement or removal.
      if (busyRef.current) return;
      generation.current++;
      reportFailure("Документ больше не доступен. Прикрепите файл заново.", "Документ недоступен");
    }, document.expires_in_seconds * 1000);
    return () => clearTimeout(timer);
  }, [document]);
  const upload = async (file: File) => {
    if (!sessionId) return;
    if (!/\.(txt|md|pdf)$/i.test(file.name) || file.size === 0 || file.size > 10 * 1024 * 1024) {
      reportFailure("Выберите непустой TXT, MD или текстовый PDF до 10 МБ."); return;
    }
    cancelUpload(); setError(""); changeBusy(true);
    const token = generation.current;
    const id = crypto.randomUUID();
    const controller = new AbortController();
    active.current = { id, session: sessionId, controller };
    const uploadNoticeId = `document-upload.${id}`;
    noticeId.current = uploadNoticeId;
    notify.info("Читаю документ…", file.name, {
      id: uploadNoticeId,
      duration: "persistent",
      actions: [{ label: "Отменить чтение", onClick: cancelUpload }],
    });
    const body = new FormData(); body.append("session_id", sessionId); body.append("upload_id", id); body.append("file", file);
    try {
      const next = await requestJson<AttachedDocument>("/documents", { method: "POST", body, signal: controller.signal });
      if (token !== generation.current) { void remove(next.id, sessionId).catch(() => {}); return; }
      setDocument(next); setSourceId("D1"); setSource(null);
      notify.success("Документ прикреплён", next.name, {
        id: uploadNoticeId,
        actions: [{ label: "Открыть документ", onClick: () => {
          if (documentRef.current?.id === next.id) setDetailsOpen(true);
        } }],
      });
    } catch (cause) { if (!controller.signal.aborted && token === generation.current) reportFailure(cause instanceof Error ? cause.message : "Не удалось прочитать документ"); }
    finally { if (token === generation.current) { active.current = null; changeBusy(false); } }
  };
  const inspectSource = async () => {
    if (!document || !sessionId) return;
    setError("");
    const token = generation.current;
    try { const next = await requestJson<Source>(`/documents/${encodeURIComponent(document.id)}/sources/${encodeURIComponent(sourceId)}?session_id=${encodeURIComponent(sessionId)}`); if (token === generation.current) setSource(next); }
    catch (cause) { if (token === generation.current) setError(cause instanceof Error ? cause.message : "Фрагмент недоступен"); }
  };
  const removeDocument = async () => {
    const current = documentRef.current;
    if (!current || !sessionId || disabled || busyRef.current) return;
    const token = ++generation.current;
    setError(""); changeBusy(true); dismissNotice();
    noticeId.current = notify.info("Убираю документ…", current.name, { duration: "persistent" });
    try {
      await remove(current.id, sessionId);
      if (token !== generation.current) return;
      setDocument(null); setSource(null); setDetailsOpen(false); dismissNotice();
    } catch (cause) {
      if (token === generation.current) reportFailure(cause instanceof Error ? cause.message : "Не удалось убрать документ", "Не удалось убрать документ");
    } finally {
      if (token === generation.current) changeBusy(false);
    }
  };
  return <div className="document-attachment">
    <input ref={input} type="file" accept=".txt,.md,.pdf" hidden aria-label="Выбрать документ" onChange={event => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void upload(file); }} />
    <MaterialButton
      materialKey="document.attach"
      ref={button}
      appearance="plain"
      className="document-attachment-button"
      type="button"
      aria-label={document ? "Открыть прикреплённый документ" : "Приложить документ"}
      aria-haspopup={document ? "dialog" : undefined}
      aria-busy={busy}
      data-attached={Boolean(document)}
      title={document ? document.name : "TXT, MD или текстовый PDF"}
      disabled={disabled || !sessionId || busy}
      onClick={event => {
        animateButtonPress(event.currentTarget);
        if (document) setDetailsOpen(true); else chooseFile();
      }}
    >
      <Paperclip size={20} aria-hidden="true" />
    </MaterialButton>
    <AppDialog open={detailsOpen && Boolean(document) && !source} title="Документ в беседе" description={document?.name} icon={<FileText size={24} aria-hidden="true" />} variant="info" onClose={() => setDetailsOpen(false)}>
      <div className="document-attachment-details">
        <p>Файл доступен Iris в текущей беседе.</p>
        <Disclosure materialKey="document.usage" label={<>Как используется файл</>}>

          <p>Для ответа Iris отправляет нужные фрагменты внешней модели. В личную память они автоматически не добавляются. В истории остаются ответ и ссылки, без исходного текста файла. Прикрепите файл заново после его удаления из беседы, перезапуска Iris или через 2 часа.</p>
        </Disclosure>
        <div className="document-source-actions">
          <label>Ссылка из ответа<input aria-label="ID фрагмента документа" value={sourceId} disabled={busy} onChange={event => setSourceId(event.target.value.toUpperCase().replace(/[^D0-9]/g, ""))} onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); event.stopPropagation(); void inspectSource(); } }} placeholder="D1" /></label>
          <MaterialButton materialKey="document.inspect" className="secondary" type="button" disabled={busy} onClick={() => void inspectSource()}>Открыть фрагмент</MaterialButton>
        </div>
        {error && <p className="error-text" role="alert">{error}</p>}
        <div className="dialog-actions">
          <MaterialButton materialKey="document.replace" className="secondary" type="button" disabled={disabled || busy} onClick={chooseFile}>Заменить файл</MaterialButton>
          <MaterialButton materialKey="document.remove" className="secondary" type="button" disabled={disabled || busy} onClick={() => void removeDocument()}>Убрать из беседы</MaterialButton>
        </div>
      </div>
    </AppDialog>
    <AppDialog open={Boolean(source)} onClose={() => setSource(null)} title={source ? `${source.id} · ${source.label}` : "Фрагмент документа"} icon={<FileText size={24} aria-hidden="true" />} variant="info"><p className="document-source-text" data-i18n-skip>{source?.text}</p></AppDialog>
  </div>;
}
