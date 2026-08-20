import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, CircleAlert, Code2, FileDiff, LoaderCircle, Play, RefreshCw, SendHorizontal, Square, TerminalSquare, Trash2 } from "lucide-react";

import {
  addCodingInstruction,
  applyCodingTask,
  cancelCodingTask,
  clearCodingTasks,
  createCodingTask,
  getCodingStatus,
  getCodingTask,
  getCodingTasks,
  retryCodingTask,
  updateRuntimeSettings,
} from "./api";
import { currentInterfaceLocale, interfaceIntlLocale, translateInterfaceText } from "./i18n";
import type { BackendEvent, CodingStatus, CodingTask, PublicSettings } from "./types";
import { animateButtonPress, animatePageEnter, animateStaggerCards, useAnimeScope } from "./animations";

const ACTIVE_TASKS = new Set(["pending", "running", "waiting_for_input"]);

function statusLabel(status: string): string {
  return ({
    pending: "в очереди", running: "выполняется", waiting_for_input: "ждёт решения",
    review_ready: "готово к ревью", failed: "ошибка", cancelled: "остановлено",
    applied: "применено", conflicted: "конфликт исходников",
  } as Record<string, string>)[status] ?? status;
}

export function CodingAgentPage({
  settings,
  events,
  sessionId,
  onSettingsChanged,
}: {
  settings: PublicSettings | null;
  events: BackendEvent[];
  sessionId: string | null;
  onSettingsChanged: (settings: PublicSettings) => void;
}) {
  const [status, setStatus] = useState<CodingStatus | null>(null);
  const [tasks, setTasks] = useState<CodingTask[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<CodingTask | null>(null);
  const [objective, setObjective] = useState("");
  const [contextFiles, setContextFiles] = useState("");
  const [instruction, setInstruction] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const containerRef = useAnimeScope<HTMLElement>((scope, root) => {
    animatePageEnter(root);
  }, []);

  const tasksListRef = useRef<HTMLDivElement | null>(null);
  const detailRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (tasksListRef.current && tasks.length > 0) {
      animateStaggerCards(tasksListRef.current, ".coding-task-row", 40);
    }
  }, [tasks]);

  useEffect(() => {
    if (detailRef.current && selected) {
      animatePageEnter(detailRef.current);
    }
  }, [selectedId]);

  const refresh = useCallback(async (refreshDocker = false) => {
    try {
      const [nextStatus, nextTasks] = await Promise.all([getCodingStatus(refreshDocker), getCodingTasks()]);
      setStatus(nextStatus);
      setTasks(nextTasks);
      setSelectedId((current) => current ?? nextTasks[0]?.id ?? null);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось получить состояние Coding Agent.");
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { setWorkspaceName(settings?.coding_workspace_name ?? ""); }, [settings?.coding_workspace_name]);
  useEffect(() => {
    if (events.some((event) => event.type.startsWith("coding."))) void refresh();
  }, [events, refresh]);
  useEffect(() => {
    if (!selectedId) { setSelected(null); return; }
    void getCodingTask(selectedId).then(setSelected).catch(() => setSelected(null));
  }, [selectedId, tasks]);
  useEffect(() => {
    const hasActiveTask = tasks.some((task) => ACTIVE_TASKS.has(task.status));
    const timer = window.setInterval(() => void refresh(), hasActiveTask ? 2500 : 5000);
    return () => window.clearInterval(timer);
  }, [tasks, refresh]);

  const active = useMemo(() => tasks.find((task) => ACTIVE_TASKS.has(task.status)), [tasks]);
  const changeSettings = async (payload: Parameters<typeof updateRuntimeSettings>[0]) => {
    setBusy(true);
    try {
      onSettingsChanged(await updateRuntimeSettings(payload));
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось сохранить настройки Coding Agent.");
    } finally { setBusy(false); }
  };
  const submitTask = async (event: FormEvent) => {
    event.preventDefault();
    if (!objective.trim()) return;
    const requestedFiles = contextFiles.split(/[\n,]/).map((value) => value.trim()).filter(Boolean).slice(0, 40);
    setBusy(true);
    try {
      const task = await createCodingTask({
        objective: objective.trim(),
        ...(sessionId ? { session_id: sessionId } : {}),
        ...(requestedFiles.length ? { context_files: requestedFiles } : {}),
      });
      setObjective(""); setContextFiles(""); setSelectedId(task.id); await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Не удалось поставить задачу в очередь."); }
    finally { setBusy(false); }
  };
  const act = async (operation: () => Promise<CodingTask>) => {
    setBusy(true);
    try { const task = await operation(); setSelected(task); setSelectedId(task.id); await refresh(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Операция не выполнена."); }
    finally { setBusy(false); }
  };
  const submitInstruction = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected || !instruction.trim()) return;
    await act(() => addCodingInstruction(selected.id, instruction.trim()));
    setInstruction("");
  };
  const clearTaskList = async () => {
    if (active || tasks.length === 0) return;
    if (!window.confirm(translateInterfaceText(
      "Очистить список завершённых задач? Рабочие папки и созданные файлы сохранятся.",
      currentInterfaceLocale(),
    ))) return;
    setBusy(true);
    try {
      await clearCodingTasks();
      setSelectedId(null);
      setSelected(null);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось очистить список задач.");
    } finally { setBusy(false); }
  };

  return (
    <section className="coding-page" ref={containerRef} aria-labelledby="coding-agent-title">
      <header className="coding-page-header">
        <div><span className="eyebrow">v09 · изолированная среда</span><h1 id="coding-agent-title">Coding Agent</h1><p>По умолчанию агент работает в собственной папке задачи. Файлы проекта передаются только как явно указанный контекст и никогда не монтируются в контейнер напрямую.</p></div>
        <button className="secondary-button" type="button" onClick={(e) => { animateButtonPress(e.currentTarget); void refresh(true); }} disabled={busy}><RefreshCw size={16} /> Обновить среду</button>
      </header>
      {error && <div className="notice is-error"><CircleAlert size={17} /> {error}</div>}
      <div className="coding-status-grid">
        <article><span>Агент</span><strong className={status?.enabled ? "is-success" : "is-muted"}>{status?.enabled ? "Включён" : "Выключен"}</strong><small>{status?.configured_enabled ? "Функция доступна" : "Отключён администратором"}</small></article>
        <article><span>Docker</span><strong className={status?.docker_daemon_available ? "is-success" : "is-danger"}>{status?.docker_daemon_available ? "Запущен" : "Недоступен"}</strong><small>{status?.docker_daemon_available ? (status?.docker_image_available ? "Образ песочницы: готов" : "Образ песочницы: не собран") : (status?.availability_reason ?? "Проверяю Docker daemon")}</small></article>
        <article><span>Текущая работа</span><strong>{active ? statusLabel(active.status) : "Нет задачи"}</strong><small>{active ? <span data-i18n-skip>{active.objective.slice(0, 92)}</span> : "Создайте задачу ниже"}</small></article>
      </div>
      {settings && <section className="coding-settings-panel" aria-label="Настройки Coding Agent">
        <label className="settings-switch-row"><span><strong>Включить Coding Agent</strong><small>Основной агент сможет передавать ему coding-задачи.</small></span><input type="checkbox" checked={settings.coding_agent_enabled} disabled={busy || !settings.coding_api_key_configured} onChange={(event) => void changeSettings({ coding_agent_enabled: event.target.checked })} /></label>
        <label>Модель<select value={settings.coding_model} disabled={busy} onChange={(event) => void changeSettings({ coding_model: event.target.value as PublicSettings["coding_model"] })}>{settings.coding_available_models.map((model) => <option key={model} value={model}>{model}</option>)}</select></label>
        <label>Проект для контекста<select value={settings.coding_project_root} disabled={busy} onChange={(event) => void changeSettings({ coding_project_root: event.target.value })}>{settings.coding_allowed_project_roots.map((root) => <option key={root} value={root}>{root}</option>)}</select></label>
        <label>Имя workspace<input value={workspaceName} disabled={busy} maxLength={80} onBlur={(event) => { if (event.target.value && event.target.value !== settings.coding_workspace_name) void changeSettings({ coding_workspace_name: event.target.value }); }} onChange={(event) => setWorkspaceName(event.target.value)} /></label>
        <label className="settings-switch-row"><span><strong>Автоделегирование</strong><small>Основной агент ставит явно сформулированные coding-запросы в очередь.</small></span><input type="checkbox" checked={settings.coding_auto_delegate} disabled={busy || !settings.coding_agent_enabled} onChange={(event) => void changeSettings({ coding_auto_delegate: event.target.checked })} /></label>
      </section>}
      <div className="coding-workspace-grid">
        <section className="coding-task-panel"><h2>Новая задача</h2><form onSubmit={submitTask}><textarea value={objective} onChange={(event) => setObjective(event.target.value)} placeholder="Например: напиши простой файл hello.py и проверь его в sandbox" disabled={busy || !status?.enabled || !status?.available} /><label className="coding-context-label">Контекст из проекта <small>необязательно: относительные пути, по одному на строку</small><textarea value={contextFiles} onChange={(event) => setContextFiles(event.target.value)} placeholder={"apps/backend/app/main.py\ntests/test_main.py"} disabled={busy || !status?.enabled || !status?.available} /></label><button className="primary-button" type="submit" disabled={busy || !status?.enabled || !status?.available || objective.trim().length < 3}><Play size={16} /> Передать агенту</button><button className="secondary-button" type="button" disabled={busy || tasks.length === 0 || Boolean(active)} onClick={() => void clearTaskList()}><Trash2 size={16} /> Очистка списка задач</button></form><p className="coding-hint">Без контекста задача начнётся в новой отдельной папке: {status?.workspace_root ?? "настройте CODING_WORKSPACE_ROOT"}. Docker обязателен; сеть и установка пакетов запрещены.</p></section>
        <section className="coding-task-list" ref={tasksListRef}><h2>Задачи</h2>{tasks.length === 0 && <p className="muted">Задач пока нет.</p>}{tasks.map((task) => <button type="button" key={task.id} className={`coding-task-row${task.id === selectedId ? " is-selected" : ""}`} onClick={(e) => { animateButtonPress(e.currentTarget); setSelectedId(task.id); }}><span className={`coding-task-status status-${task.status}`}>{statusLabel(task.status)}</span><strong data-i18n-skip>{task.objective}</strong><small>{new Date(task.updated_at).toLocaleString(interfaceIntlLocale())}</small></button>)}</section>
      </div>
      {selected && <section className="coding-detail" ref={detailRef}><header><div><span className={`coding-task-status status-${selected.status}`}>{statusLabel(selected.status)}</span><h2 data-i18n-skip>{selected.objective}</h2><small>{selected.model} · {selected.project_root || "отдельная рабочая папка"}</small>{selected.workspace_path && <small><span>Изолированный workspace: </span><span data-i18n-skip>{selected.workspace_path}</span></small>}</div><div className="coding-actions">{ACTIVE_TASKS.has(selected.status) && <button className="danger-button" type="button" disabled={busy} onClick={() => void act(() => cancelCodingTask(selected.id))}><Square size={15} /> Остановить</button>}{["failed", "cancelled", "waiting_for_input", "conflicted"].includes(selected.status) && <button className="secondary-button" type="button" disabled={busy} onClick={() => void act(() => retryCodingTask(selected.id))}><RefreshCw size={15} /> Повторить</button>}{selected.status === "review_ready" && <button className="primary-button" type="button" disabled={busy} onClick={() => void act(() => applyCodingTask(selected.id))}><Check size={16} /> {selected.project_root ? "Применить изменения" : "Подтвердить результат"}</button>}</div></header>
        {selected.error_text && <div className="notice is-error"><CircleAlert size={17} /> <span data-i18n-skip>{selected.error_text}</span></div>}
        {selected.status === "waiting_for_input" && <div className="notice"><CircleAlert size={17} /> {selected.result.question !== undefined ? <span data-i18n-skip>{String(selected.result.question)}</span> : "Агент ожидает уточнения."}</div>}
        {selected.result.summary !== undefined && <div className="coding-result"><h3>Результат</h3><p data-i18n-skip>{String(selected.result.summary)}</p>{selected.result.tests !== undefined && <pre>{String(selected.result.tests)}</pre>}</div>}
        {selected.patch_text && <details className="coding-diff" open><summary><FileDiff size={17} /> Diff и изменённые файлы</summary><pre>{selected.patch_text}</pre></details>}
        <div className="coding-detail-grid"><section><h3><TerminalSquare size={17} /> Логи, команды и ошибки</h3><div className="coding-events">{selected.events.length === 0 && <p className="muted">Событий ещё нет.</p>}{selected.events.map((item) => <article key={item.id} className={`event-level-${item.level}`}><header><strong>{item.message}</strong><time>{new Date(item.created_at).toLocaleTimeString(interfaceIntlLocale())}</time></header>{Object.keys(item.payload).length > 0 && <pre>{JSON.stringify(item.payload, null, 2)}</pre>}</article>)}</div></section><section><h3><SendHorizontal size={17} /> Вмешательство</h3><form onSubmit={submitInstruction}><textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="Дополнительная инструкция для задачи" disabled={busy || !ACTIVE_TASKS.has(selected.status)} /><button className="secondary-button" type="submit" disabled={busy || !ACTIVE_TASKS.has(selected.status) || !instruction.trim()}>Отправить инструкцию</button></form><p className="coding-hint">Уточнение доставляется на следующем шаге. Если агент ждёт решения, задача автоматически продолжится.</p></section></div>
      </section>}
    </section>
  );
}
