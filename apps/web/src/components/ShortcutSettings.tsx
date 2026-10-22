import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { IconInterfaceEditWrite2 as Edit, IconInterfaceReset as Reset } from "../CustomIcons";
import { isDesktopApp } from "../desktop";
import { translateInterfaceText } from "../i18n";
import { SHORTCUTS, bindingError, bindingFromEvent, defaultBindings, formatBinding, getGlobalShortcuts, isGlobalShortcut, mergeGlobalShortcuts, saveBindings, setShortcutRecording, useShortcutBindings, type Bindings, type GlobalShortcutStatus, type ShortcutId } from "../shortcuts";
import { MaterialButton } from "./MaterialButton";
import { AppCheckbox } from "./AppCheckbox";
import { AppDialog } from "./AppDialog";
import "./ShortcutSettings.css";

export function ShortcutKeys({ binding }: { binding: string | null }) {
  if (!binding) return <span className="shortcut-unassigned">Не назначено</span>;
  return <kbd className="shortcut-keys" data-i18n-skip>
    {formatBinding(binding).split("+").map((key, index) => <span className="shortcut-key" key={index}>
      {index > 0 && <span className="shortcut-key-separator">+</span>}{key}
    </span>)}
  </kbd>;
}

export function ShortcutSettings() {
  const bindings = useShortcutBindings();
  const desktop = isDesktopApp();
  const [query, setQuery] = useState("");
  const [changedOnly, setChangedOnly] = useState(false);
  const [editing, setEditing] = useState<ShortcutId | null>(null);
  const [candidate, setCandidate] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const recordingRef = useRef(false);
  const mounted = useRef(true);
  const [ready, setReady] = useState(!desktop);
  const [loadError, setLoadError] = useState("");
  const [nativeErrors, setNativeErrors] = useState<GlobalShortcutStatus["errors"]>({});
  const [resetOpen, setResetOpen] = useState(false);
  const editorRef = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLButtonElement | null>(null);

  const load = async () => {
    setLoadError("");
    try {
      const status = await getGlobalShortcuts();
      if (!mounted.current) return;
      mergeGlobalShortcuts(status); setNativeErrors(status.errors); setReady(true);
    } catch { if (mounted.current) { setReady(false); setLoadError("Не удалось загрузить системные сочетания."); } }
  };
  useEffect(() => {
    mounted.current = true;
    if (desktop) void load();
    return () => {
      mounted.current = false;
      setShortcutRecording(false);
      if (desktop && recordingRef.current) void invoke("set_shortcut_recording", { recording: false }).catch(console.error);
      recordingRef.current = false;
      setEditing(null); setCandidate(null); setResetOpen(false);
    };
  }, [desktop]);

  const endRecording = async () => {
    const ownsBusy = !busyRef.current;
    if (ownsBusy) { busyRef.current = true; setBusy(true); }
    setShortcutRecording(false);
    recordingRef.current = false;
    setEditing(null); setCandidate(null); setMessage("");
    if (desktop) {
      try {
        const status = await invoke<GlobalShortcutStatus>("set_shortcut_recording", { recording: false });
        if (mounted.current) { mergeGlobalShortcuts(status); setNativeErrors(status.errors); }
      } catch { if (mounted.current) {
        const error = "Не удалось восстановить системные сочетания. Нажмите «Повторить подключение».";
        setMessage(error); setNativeErrors({ showWindow: error });
      } }
    }
    if (ownsBusy) { busyRef.current = false; if (mounted.current) setBusy(false); }
  };
  useEffect(() => {
    if (!editing && !busy && opener.current?.isConnected && !opener.current.disabled) {
      opener.current.focus(); opener.current = null;
    }
  }, [editing, busy]);
  const beginRecording = async (id: ShortcutId, button: HTMLButtonElement) => {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setMessage("");
    opener.current = button;
    try {
      if (desktop) await invoke("set_shortcut_recording", { recording: true });
      if (!mounted.current) {
        if (desktop) await invoke("set_shortcut_recording", { recording: false });
        return;
      }
      recordingRef.current = true; setShortcutRecording(true);
      setCandidate(null); setEditing(id);
      return true;
    } catch { if (mounted.current) setMessage("Не удалось начать запись сочетания. Попробуйте ещё раз."); return false; }
    finally { busyRef.current = false; if (mounted.current) setBusy(false); }
  };
  useLayoutEffect(() => {
    if (!editing) return;
    editorRef.current?.focus();
    const capture = (event: KeyboardEvent) => {
      if (event.key === "Tab") return;
      // Let native buttons keep Enter/Space activation for keyboard users.
      if ((event.key === "Enter" || event.key === " ") && !event.ctrlKey && event.target instanceof HTMLButtonElement) return;
      event.preventDefault(); event.stopImmediatePropagation();
      if (event.key === "Escape") { void endRecording(); return; }
      if (event.repeat || event.isComposing || ["Control", "Shift", "Alt", "Meta", "AltGraph"].includes(event.key)) return;
      const chord = bindingFromEvent(event);
      const error = chord ? bindingError(chord) : "Используйте Ctrl и клавишу. Системная клавиша Windows и AltGr недоступны.";
      setCandidate(error ? null : chord); setMessage(error ?? "");
    };
    const blur = () => { if (!busyRef.current) void endRecording(); };
    window.addEventListener("keydown", capture, true);
    window.addEventListener("blur", blur);
    return () => { window.removeEventListener("keydown", capture, true); window.removeEventListener("blur", blur); };
  }, [editing]);

  const apply = async (next: Bindings, reconnectGlobals = false) => {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setMessage("");
    try {
      await saveBindings(next, reconnectGlobals);
      if (mounted.current) {
        setNativeErrors({});
        await endRecording();
        setResetOpen(false); setMessage("Сочетания сохранены.");
      }
    } catch (error) {
      if (mounted.current) {
        setMessage(error instanceof Error ? error.message : String(error));
        if (desktop) void load();
      }
    } finally { busyRef.current = false; if (mounted.current) setBusy(false); }
  };
  const conflict = candidate ? SHORTCUTS.find(item => item.id !== editing && bindings[item.id] === candidate) : undefined;
  const defaults = defaultBindings();
  const visible = SHORTCUTS.filter(item => (!changedOnly || bindings[item.id] !== item.default) && `${item.title} ${item.description} ${translateInterfaceText(item.title + " " + item.description, "en")} ${formatBinding(bindings[item.id])}`.toLocaleLowerCase().includes(query.toLocaleLowerCase().trim()));
  const changedCount = SHORTCUTS.filter(item => bindings[item.id] !== item.default).length;

  return <div className="shortcut-settings" aria-busy={busy}>
    <section className="settings-card shortcut-intro" aria-label="Как работают сочетания">
      <div><h3 className="settings-card-title">Управление с клавиатуры</h3><p className="settings-card-subtitle">Нажмите на сочетание, чтобы назначить другое.</p></div>
      <div className="shortcut-toolbar">
        <label className="shortcut-search"><span className="sr-only">Найти команду</span><input type="search" placeholder="Найти команду или сочетание" value={query} onChange={event => setQuery(event.target.value)} disabled={!!editing} /></label>
        <label className="shortcut-filter"><AppCheckbox checked={changedOnly} onChange={event => setChangedOnly(event.target.checked)} disabled={!!editing} />Изменённые <span>{changedCount}</span></label>
      </div>
      <p className="shortcut-scope-note">Системные сочетания работают и в других приложениях. Чтобы включить их, назначьте клавиши.</p>
    </section>
    {loadError && <div className="notice is-error" role="alert">{loadError}<MaterialButton materialKey="shortcuts.retry" onClick={() => void load()}>Повторить</MaterialButton></div>}
    {message && !editing && <p className="shortcut-feedback" role="status">{message}</p>}
    {["Навигация", "Разговор", "Системные"].map(group => {
      const items = visible.filter(item => item.group === group);
      if (!items.length) return null;
      return <section key={group} className="settings-card shortcut-group" aria-label={group}>
        <div className="shortcut-group-heading"><h3 className="settings-card-title">{group}</h3><span>{group === "Системные" ? "В Windows" : "В окне Iris"}</span></div>
        {group === "Системные" && <p className="settings-card-subtitle">{desktop ? "Выберите сочетание, которое не используется в других приложениях." : "Настройка доступна в настольном приложении Iris."}</p>}
        <div className="shortcut-rows">{items.map(item => <div className={`shortcut-row${editing === item.id ? " is-recording" : ""}`} key={item.id}>
          <div className="shortcut-row-copy">
            <div className="shortcut-row-title">
              <strong id={`shortcut-label-${item.id}`}>{item.title}</strong>
              {bindings[item.id] !== item.default && <span className="shortcut-customized">Изменено</span>}
            </div>
            {item.group !== "Навигация" && <p>{item.description}</p>}
            {nativeErrors[item.id as keyof typeof nativeErrors] && <p className="shortcut-error" role="alert">{nativeErrors[item.id as keyof typeof nativeErrors]}</p>}
          </div>
          <MaterialButton appearance={editing === item.id ? "lens" : "quiet"} tone={editing === item.id ? "accent" : "graphite"}
            surfaceMotion={false} materialKey={`shortcuts.bind.${item.id}`} className="shortcut-bind"
            aria-label={`Изменить: ${item.title}`} title="Изменить сочетание" aria-describedby={`shortcut-label-${item.id}`}
            aria-expanded={editing === item.id} aria-controls={editing === item.id ? `shortcut-editor-${item.id}` : undefined}
            disabled={busy || !!editing || !ready || (isGlobalShortcut(item.id) && !desktop)}
            onClick={event => void beginRecording(item.id, event.currentTarget)}>
            <ShortcutKeys binding={bindings[item.id]} />
            <Edit className="shortcut-edit-icon" size={14} aria-hidden="true" />
          </MaterialButton>
          {editing === item.id && <div className="shortcut-recorder" id={`shortcut-editor-${item.id}`} ref={editorRef} tabIndex={-1} aria-label={`Новое сочетание: ${item.title}`}>
            <span className="shortcut-recorder-label">Новое сочетание</span>
            <div className="shortcut-recorder-preview" aria-live="polite">{candidate ? <ShortcutKeys binding={candidate} /> : <span>Нажмите Ctrl и нужную клавишу…</span>}</div>
            <p className={conflict ? "shortcut-conflict" : undefined} aria-live="polite">{conflict ? <>Уже назначено: <strong>{conflict.title}</strong>. При переносе прежняя команда останется без сочетания.</> : "Можно добавить Shift или Alt вместе с Shift. Esc — отмена, Tab — переход к кнопкам."}</p>
            {message && <p className="shortcut-feedback" role="status">{message}</p>}
            <div className="shortcut-recorder-footer">
              <div className="shortcut-editor-actions">
                <MaterialButton materialKey="shortcuts.save" tone="accent" disabled={!candidate || busy} onClick={() => candidate && void apply({ ...bindings, ...(conflict ? { [conflict.id]: null } : {}), [item.id]: candidate })}>{conflict ? "Перенести сюда" : "Сохранить"}</MaterialButton>
                <MaterialButton materialKey="shortcuts.cancel" appearance="quiet" disabled={busy} onClick={() => void endRecording()}>Отмена</MaterialButton>
              </div>
              <div className="shortcut-editor-utilities">
                {item.default && bindings[item.id] !== item.default && <MaterialButton appearance="quiet" materialKey={`shortcuts.reset.${item.id}`} disabled={busy || candidate === item.default} onClick={() => { setCandidate(item.default); setMessage(""); }}>По умолчанию</MaterialButton>}
                {bindings[item.id] && <MaterialButton appearance="quiet" materialKey={`shortcuts.unbind.${item.id}`} disabled={busy} onClick={() => void apply({ ...bindings, [item.id]: null })}>Отключить сочетание</MaterialButton>}
              </div>
            </div>
          </div>}
        </div>)}</div>
      </section>;
    })}
    {!visible.length && <p className="shortcut-empty">Ничего не найдено. Попробуйте другое название или отключите фильтр.</p>}
    <footer className="shortcut-footer">
      <div className="shortcut-reference">
        <h3 className="shortcut-footer-title">Стандартные клавиши</h3>
        <dl className="shortcut-standard-keys">
          {[
            { keys: "Enter", label: "Отправить сообщение" },
            { keys: "Shift+Enter", label: "Новая строка" },
            { keys: "Esc", label: "Закрыть диалоговое окно" },
          ].map(item => <div key={item.keys}>
            <dt><ShortcutKeys binding={item.keys} /></dt>
            <dd>{item.label}</dd>
          </div>)}
        </dl>
      </div>
      {changedCount > 0 ? <MaterialButton materialKey="shortcuts.reset-all" appearance="quiet" surfaceMotion={false}
        className="shortcut-reset-button" disabled={busy || !!editing || !ready} onClick={() => setResetOpen(true)}>
        <Reset size={16} aria-hidden="true" /><span>Сбросить всё</span>
      </MaterialButton> : <p className="shortcut-default-status">Сочетания по умолчанию</p>}
    </footer>
    {desktop && Object.keys(nativeErrors).length > 0 && <MaterialButton materialKey="shortcuts.reconnect" disabled={busy || !!editing} onClick={() => void apply({ ...bindings }, true)}>Повторить подключение</MaterialButton>}
    <AppDialog open={resetOpen} onClose={() => !busy && setResetOpen(false)} title="Сбросить сочетания?" description="Вернутся исходные сочетания Iris. Системные привязки будут отключены." variant="warning"><div className="shortcut-editor-actions"><MaterialButton materialKey="shortcuts.confirm-reset" disabled={busy} onClick={() => void apply(defaults)}>Сбросить</MaterialButton><MaterialButton materialKey="shortcuts.cancel-reset" appearance="quiet" disabled={busy} onClick={() => setResetOpen(false)}>Отмена</MaterialButton></div></AppDialog>
  </div>;
}
