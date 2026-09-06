import { CustomSelect } from "./components/CustomSelect";
import { AppSwitch } from "./components/AppSwitch";
import { InfoRow } from "./components/InfoRow";
import { ChevronLeft, X } from "lucide-react";
import { notify } from "./notifications";
import {
  IconProgrammingScript2,
  IconInterfaceSpirals,
  IconInterfaceAlertAlarmBell2,
  IconInterfaceCursorArrow2,
  IconInterfaceDeleteBin3,
  IconInterfaceTimeStopWatchCircle,
  IconInterfaceFavoriteLike1,
  IconInterfaceFilesFolderCopy2,
  IconMailSendEnvelope,
  IconComputerDatabase,
  IconInterfacePageControllerSettings,
  IconInterfaceSearch,
  IconComputerRobotCyborg1,
  IconInterfaceSettingGaugeDashboard1,
} from "./CustomIcons";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState, type ComponentType } from "react";

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

type CodingSection = "tasks" | "new-task" | "environment" | "settings";
type TaskFilter = "all" | "active" | "review" | "completed";

const ACTIVE_TASKS = new Set(["pending", "running", "waiting_for_input"]);

function statusLabel(status: string): string {
  return (
    ({
      pending: "в очереди",
      running: "выполняется",
      waiting_for_input: "ждёт решения",
      review_ready: "готово к ревью",
      failed: "ошибка",
      cancelled: "остановлено",
      applied: "применено",
      conflicted: "конфликт исходников",
    } as Record<string, string>)[status] ?? status
  );
}

function formatTaskTime(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const now = new Date();
  const isToday = date.toDateString() === now.toDateString();
  const time = date.toLocaleTimeString(interfaceIntlLocale(), { hour: "2-digit", minute: "2-digit" });
  if (isToday) return currentInterfaceLocale() === "en" ? `Today, ${time}` : `Сегодня, ${time}`;
  return date.toLocaleDateString(interfaceIntlLocale(), {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const CODING_SECTIONS: Array<{ id: CodingSection; label: string; icon: ComponentType<{ size?: number; className?: string }> }> = [
  { id: "tasks", label: "Задачи", icon: IconProgrammingScript2 },
  { id: "new-task", label: "Новая задача", icon: IconInterfaceCursorArrow2 },
  { id: "environment", label: "Песочница Docker", icon: IconComputerDatabase },
  { id: "settings", label: "Параметры", icon: IconInterfacePageControllerSettings },
];

function formatDockerAvailabilityReason(reason?: string | null): string {
  if (!reason) return "Docker daemon готов к запуску контейнеров";
  const r = reason.toLowerCase();
  if (r.includes("docker cli is not installed") || r.includes("docker cli is") || r.includes("не установлены")) {
    return "Утилита Docker CLI не установлена или недоступна в PATH";
  }
  if (r.includes("docker daemon is not running") || r.includes("daemon is not")) {
    return "Служба Docker daemon не запущена";
  }
  return reason;
}

const CodingSwitch = AppSwitch;
const InfoCard = InfoRow;

export function CodingAgentPage({
  settings,
  events,
  sessionId,
  onOpenApiSettings,
  onSettingsChanged,
}: {
  settings: PublicSettings | null;
  events: BackendEvent[];
  sessionId: string | null;
  onOpenApiSettings: () => void;
  onSettingsChanged: (settings: PublicSettings) => void;
}) {
  const [activeSection, setActiveSection] = useState<CodingSection>("tasks");
  const [status, setStatus] = useState<CodingStatus | null>(null);
  const [tasks, setTasks] = useState<CodingTask[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<CodingTask | null>(null);
  const [taskFilter, setTaskFilter] = useState<TaskFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");

  const [objective, setObjective] = useState("");
  const [targetProjectRoot, setTargetProjectRoot] = useState("");
  const [contextFiles, setContextFiles] = useState("");

  const [instruction, setInstruction] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const containerRef = useAnimeScope<HTMLElement>((scope, root) => {
    animatePageEnter(root);
  }, []);

  const contentRef = useRef<HTMLDivElement | null>(null);
  const tasksListRef = useRef<HTMLDivElement | null>(null);
  const detailRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (contentRef.current) {
      animatePageEnter(contentRef.current);
    }
  }, [activeSection]);

  const refresh = useCallback(async (refreshDocker = false) => {
    try {
      const [nextStatus, nextTasks] = await Promise.all([
        getCodingStatus(refreshDocker),
        getCodingTasks(100),
      ]);
      setStatus(nextStatus);
      setTasks(nextTasks);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось получить состояние Coding Agent.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    setWorkspaceName(settings?.coding_workspace_name ?? "");
    if (!targetProjectRoot && settings?.coding_project_root) {
      setTargetProjectRoot(settings.coding_project_root);
    }
  }, [settings?.coding_workspace_name, settings?.coding_project_root, targetProjectRoot]);

  useEffect(() => {
    if (events.some((event) => event.type.startsWith("coding."))) {
      void refresh();
    }
  }, [events, refresh]);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      return;
    }
    void getCodingTask(selectedId).then(setSelected).catch(() => setSelected(null));
  }, [selectedId, tasks]);

  useEffect(() => {
    const hasActiveTask = tasks.some((task) => ACTIVE_TASKS.has(task.status));
    const timer = window.setInterval(() => void refresh(), hasActiveTask ? 2500 : 6000);
    return () => window.clearInterval(timer);
  }, [tasks, refresh]);

  const active = useMemo(() => tasks.find((task) => ACTIVE_TASKS.has(task.status)), [tasks]);

  const filteredTasks = useMemo(() => {
    let result = tasks;
    if (taskFilter === "active") {
      result = result.filter((t) => ACTIVE_TASKS.has(t.status));
    } else if (taskFilter === "review") {
      result = result.filter((t) => t.status === "review_ready");
    } else if (taskFilter === "completed") {
      result = result.filter((t) => !ACTIVE_TASKS.has(t.status) && t.status !== "review_ready");
    }

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      result = result.filter(
        (t) =>
          t.objective.toLowerCase().includes(q) ||
          t.model.toLowerCase().includes(q) ||
          (t.project_root && t.project_root.toLowerCase().includes(q)),
      );
    }
    return result;
  }, [tasks, taskFilter, searchQuery]);

  useEffect(() => {
    if (tasksListRef.current && filteredTasks.length > 0) {
      animateStaggerCards(tasksListRef.current, ".coding-task-card", 35);
    }
  }, [filteredTasks.length, taskFilter]);

  useEffect(() => {
    if (detailRef.current && selected) {
      animatePageEnter(detailRef.current);
    }
  }, [selectedId]);

  const changeSettings = async (payload: Parameters<typeof updateRuntimeSettings>[0]) => {
    setBusy(true);
    try {
      const updated = await updateRuntimeSettings(payload);
      onSettingsChanged(updated);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось сохранить настройки Coding Agent.");
    } finally {
      setBusy(false);
    }
  };

  const submitTask = async (event: FormEvent) => {
    event.preventDefault();
    if (!objective.trim()) return;
    const requestedFiles = contextFiles
      .split(/[\n,]/)
      .map((val) => val.trim())
      .filter(Boolean)
      .slice(0, 40);

    setBusy(true);
    try {
      const task = await createCodingTask({
        objective: objective.trim(),
        ...(sessionId ? { session_id: sessionId } : {}),
        ...(targetProjectRoot ? { project_root: targetProjectRoot } : {}),
        ...(requestedFiles.length ? { context_files: requestedFiles } : {}),
      });
      setObjective("");
      setContextFiles("");
      setSelectedId(task.id);
      setActiveSection("tasks");
      await refresh();
    } catch (cause) {
      const msg = cause instanceof Error ? cause.message : "Не удалось поставить задачу в очередь.";
      setError(msg);
      notify.error("Coding Agent", msg);
    } finally {
      setBusy(false);
    }
  };

  const act = async (operation: () => Promise<CodingTask>) => {
    setBusy(true);
    try {
      const task = await operation();
      setSelected(task);
      setSelectedId(task.id);
      await refresh();
    } catch (cause) {
      const msg = cause instanceof Error ? cause.message : "Операция не выполнена.";
      setError(msg);
      notify.error("Coding Agent", msg);
    } finally {
      setBusy(false);
    }
  };

  const submitInstruction = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected || !instruction.trim()) return;
    await act(() => addCodingInstruction(selected.id, instruction.trim()));
    setInstruction("");
  };

  const clearTaskList = async () => {
    if (active || tasks.length === 0) return;
    if (
      !window.confirm(
        translateInterfaceText(
          "Очистить список завершённых задач? Рабочие папки и созданные файлы сохранятся.",
          currentInterfaceLocale(),
        ),
      )
    )
      return;
    setBusy(true);
    try {
      await clearCodingTasks();
      setSelectedId(null);
      setSelected(null);
      await refresh();
      notify.success("Coding Agent", "Список задач очищен.");
    } catch (cause) {
      const msg = cause instanceof Error ? cause.message : "Не удалось очистить список задач.";
      setError(msg);
      notify.error("Coding Agent", msg);
    } finally {
      setBusy(false);
    }
  };

  const dockerReady = Boolean(status?.docker_daemon_available && status?.docker_image_available);

  return (
    <section className="panel coding-panel" ref={containerRef} aria-labelledby="coding-agent-title">
      <nav className="settings-navigation coding-navigation" aria-label="Разделы Coding Agent">
        {CODING_SECTIONS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            className={`settings-nav-direct${activeSection === id ? " is-active" : ""}`}
            aria-current={activeSection === id ? "page" : undefined}
            onClick={(e) => {
              animateButtonPress(e.currentTarget);
              setActiveSection(id);
            }}
          >
            <Icon size={20} aria-hidden="true" />
            <span>{label}</span>
          </button>
        ))}
      </nav>

      {/* Основная рабочая область */}
      <div className="coding-content" ref={contentRef}>
        {/* ================= РАЗДЕЛ: ЗАДАЧИ ================= */}
        {activeSection === "tasks" && (
          <>
            {error && (
              <div className="notice is-error" role="alert">
                <IconInterfaceAlertAlarmBell2 size={17} /> {error}
              </div>
            )}

            {selected ? (
              /* Полноэкранный детальный просмотр выбранной задачи */
              <main className="coding-detail-panel" ref={detailRef}>
                <div className="coding-detail-nav">
                  <button
                    type="button"
                    className="secondary coding-back-button"
                    onClick={(e) => {
                      animateButtonPress(e.currentTarget);
                      setSelectedId(null);
                      setSelected(null);
                    }}
                  >
                    <ChevronLeft size={16} aria-hidden="true" />
                    <span>Назад к списку задач</span>
                  </button>

                  <div className="coding-detail-actions">
                    {ACTIVE_TASKS.has(selected.status) && (
                      <button
                        className="danger-button"
                        type="button"
                        disabled={busy}
                        onClick={(e) => {
                          animateButtonPress(e.currentTarget);
                          void act(() => cancelCodingTask(selected.id));
                        }}
                      >
                        <IconInterfaceTimeStopWatchCircle size={15} /> Остановить
                      </button>
                    )}
                    {["failed", "cancelled", "waiting_for_input", "conflicted"].includes(selected.status) && (
                      <button
                        className="secondary"
                        type="button"
                        disabled={busy}
                        onClick={(e) => {
                          animateButtonPress(e.currentTarget);
                          void act(() => retryCodingTask(selected.id));
                        }}
                      >
                        <IconInterfaceSpirals size={15} /> Повторить
                      </button>
                    )}
                    {selected.status === "review_ready" && (
                      <button
                        className="primary-button"
                        type="button"
                        disabled={busy}
                        onClick={(e) => {
                          animateButtonPress(e.currentTarget);
                          void act(() => applyCodingTask(selected.id));
                        }}
                      >
                        <IconInterfaceFavoriteLike1 size={16} />{" "}
                        {selected.project_root ? "Применить изменения" : "Подтвердить результат"}
                      </button>
                    )}
                  </div>
                </div>

                <header className="coding-detail-header">
                  <div className="coding-detail-title-group">
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <span className={`coding-status-pill status-${selected.status}`}>
                        {ACTIVE_TASKS.has(selected.status) && <span className="journal-pulse-dot" />}
                        {statusLabel(selected.status)}
                      </span>
                      <span style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>
                        {formatTaskTime(selected.created_at)}
                      </span>
                    </div>
                    <h2 data-i18n-skip>{selected.objective}</h2>
                    <div className="coding-detail-meta">
                      <span><strong>Модель:</strong> {selected.model}</span>
                      <span><strong>Каталог:</strong> {selected.project_root || "отдельная песочница"}</span>
                      {selected.workspace_path && (
                        <span title={selected.workspace_path}>
                          <strong>Workspace:</strong> {selected.workspace_path.split(/[\\/]/).pop()}
                        </span>
                      )}
                    </div>
                  </div>
                </header>

                {selected.error_text && (
                  <div className="notice is-error" role="alert">
                    <IconInterfaceAlertAlarmBell2 size={17} />
                    <div>
                      <strong>Ошибка выполнения:</strong>
                      <p data-i18n-skip>{selected.error_text}</p>
                    </div>
                  </div>
                )}

                {selected.status === "waiting_for_input" && (
                  <div className="notice is-warning">
                    <IconInterfaceAlertAlarmBell2 size={17} />
                    <div>
                      <strong>Агент ожидает вашего ответа:</strong>
                      <p data-i18n-skip>
                        {selected.result.question !== undefined
                          ? String(selected.result.question)
                          : "Уточните инструкцию для продолжения выполнения."}
                      </p>
                    </div>
                  </div>
                )}

                {(selected.result.summary !== undefined || selected.result.tests !== undefined) && (
                  <div className="coding-result-box">
                    <h3>Результат выполнения</h3>
                    {selected.result.summary !== undefined && (
                      <p data-i18n-skip>{String(selected.result.summary)}</p>
                    )}
                    {selected.result.tests !== undefined && <pre>{String(selected.result.tests)}</pre>}
                  </div>
                )}

                {selected.patch_text && (
                  <details className="coding-diff" open>
                    <summary>
                      <IconInterfaceFilesFolderCopy2 size={16} /> Diff и изменённые файлы
                    </summary>
                    <pre>{selected.patch_text}</pre>
                  </details>
                )}

                <div className="coding-subgrid">
                  <section className="coding-card coding-events-container">
                    <div className="coding-card-heading">
                      <div className="coding-card-label">
                        <IconProgrammingScript2 size={16} />
                        <strong>Логи и события ({selected.events.length})</strong>
                      </div>
                    </div>
                    <div className="coding-events-list">
                      {selected.events.length === 0 ? (
                        <p className="muted" style={{ margin: "10px 0" }}>
                          Событий пока нет.
                        </p>
                      ) : (
                        selected.events.map((item) => (
                          <article
                            key={item.id}
                            className={`coding-event-item ${
                              item.level === "error"
                                ? "is-error"
                                : item.level === "warning"
                                ? "is-warning"
                                : ""
                            }`}
                          >
                            <div className="coding-event-header">
                              <strong>{item.message}</strong>
                              <time>{new Date(item.created_at).toLocaleTimeString(interfaceIntlLocale())}</time>
                            </div>
                            {Object.keys(item.payload).length > 0 && (
                              <pre>{JSON.stringify(item.payload, null, 2)}</pre>
                            )}
                          </article>
                        ))
                      )}
                    </div>
                  </section>

                  <section className="coding-card coding-intervention-container">
                    <div className="coding-card-heading">
                      <div className="coding-card-label">
                        <IconMailSendEnvelope size={16} />
                        <strong>Дополнительное указание</strong>
                      </div>
                    </div>
                    <form onSubmit={submitInstruction} className="coding-intervention-form">
                      <textarea
                        value={instruction}
                        onChange={(event) => setInstruction(event.target.value)}
                        placeholder="Например: проверь также обработку пустой строки или добавь комментарии к коду"
                        disabled={busy || !ACTIVE_TASKS.has(selected.status)}
                      />
                      <button
                        className="secondary"
                        type="submit"
                        disabled={busy || !ACTIVE_TASKS.has(selected.status) || !instruction.trim()}
                      >
                        Отправить указание
                      </button>
                    </form>
                    <p className="coding-hint">
                      Уточнение передаётся агенту на следующем шаге. Если задача ожидает решения, она продолжится
                      автоматически.
                    </p>
                  </section>
                </div>
              </main>
            ) : (
              /* Список всех задач (галерея карточек в полный экран) */
              <>
                <header className="settings-heading" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "12px" }}>
                  <div>
                    <h2 id="coding-agent-title">Задачи кодинг-агента</h2>
                    <p>Очередь выполнения, ревью кода, diff изменений и логи событий в реальном времени.</p>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <button
                      className="primary-button"
                      type="button"
                      onClick={(e) => {
                        animateButtonPress(e.currentTarget);
                        setActiveSection("new-task");
                      }}
                    >
                      <IconInterfaceCursorArrow2 size={16} /> Новая задача
                    </button>
                    <button
                      className="secondary"
                      type="button"
                      disabled={busy || tasks.length === 0 || Boolean(active)}
                      onClick={(e) => {
                        animateButtonPress(e.currentTarget);
                        void clearTaskList();
                      }}
                      title="Очистить завершённые задачи"
                    >
                      <IconInterfaceDeleteBin3 size={15} /> Очистить
                    </button>
                  </div>
                </header>

                <div className="coding-toolbar">
                  <form
                    className="search-form compact coding-search-form"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void refresh();
                    }}
                  >
                    <input
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Поиск по задачам"
                      aria-label="Поиск по задачам"
                    />
                    {searchQuery && (
                      <button
                        className="search-clear-btn"
                        type="button"
                        onClick={() => setSearchQuery("")}
                        aria-label="Очистить поиск"
                        title="Очистить поиск"
                      >
                        <X size={12} aria-hidden="true" />
                      </button>
                    )}
                    <button
                      className="icon-button"
                      type="button"
                      onClick={(e) => {
                        animateButtonPress(e.currentTarget);
                        void refresh();
                      }}
                      title="Обновить задачи"
                      aria-label="Обновить задачи"
                    >
                      <IconInterfaceSpirals size={16} className={busy ? "is-spinning" : ""} />
                    </button>
                    <button
                      className="icon-button search-submit"
                      type="submit"
                      title="Найти задачи"
                      aria-label="Найти задачи"
                    >
                      <IconInterfaceSearch size={16} />
                    </button>
                  </form>

                  <div className="coding-filters" role="tablist" aria-label="Фильтр статусов">
                    {(
                      [
                        { id: "all", label: "Все" },
                        { id: "active", label: "В работе" },
                        { id: "review", label: "Ревью" },
                        { id: "completed", label: "Завершены" },
                      ] as Array<{ id: TaskFilter; label: string }>
                    ).map(({ id, label }) => (
                      <button
                        key={id}
                        type="button"
                        className={`coding-filter-pill${taskFilter === id ? " is-active" : ""}`}
                        onClick={(e) => {
                          animateButtonPress(e.currentTarget);
                          setTaskFilter(id);
                        }}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>

                {filteredTasks.length === 0 ? (
                  <div className="empty-state" style={{ minHeight: "340px", padding: "48px 24px" }}>
                    <IconInterfaceTimeStopWatchCircle size={44} />
                    <strong>{searchQuery ? "Задач не найдено" : "Задач пока нет"}</strong>
                    <span>
                      {searchQuery
                        ? "Попробуйте изменить поисковый запрос или фильтр."
                        : "Поставьте агенту задачу для написания кода или тестирования в изолированной Docker-песочнице."}
                    </span>
                    {!searchQuery && (
                      <button
                        className="primary-button"
                        type="button"
                        onClick={(e) => {
                          animateButtonPress(e.currentTarget);
                          setActiveSection("new-task");
                        }}
                      >
                        <IconInterfaceCursorArrow2 size={16} /> Создать первую задачу
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="coding-tasks-grid" ref={tasksListRef}>
                    {filteredTasks.map((task) => (
                      <button
                        type="button"
                        key={task.id}
                        className="coding-task-card"
                        onClick={(e) => {
                          animateButtonPress(e.currentTarget);
                          setSelectedId(task.id);
                          setSelected(task);
                        }}
                      >
                        <div className="coding-task-card-header">
                          <span className={`coding-status-pill status-${task.status}`}>
                            {ACTIVE_TASKS.has(task.status) && <span className="journal-pulse-dot" />}
                            {statusLabel(task.status)}
                          </span>
                          <time style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>
                            {formatTaskTime(task.updated_at)}
                          </time>
                        </div>
                        <strong data-i18n-skip>{task.objective}</strong>
                        <div className="coding-task-card-meta">
                          <span>{task.model}</span>
                          <span>
                            {task.project_root ? (
                              <span data-i18n-skip>{task.project_root.split(/[\\/]/).pop()}</span>
                            ) : (
                              "песочница"
                            )}
                          </span>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </>
            )}
          </>
        )}

        {activeSection === "new-task" && (
          <>
            <header className="settings-heading">
              <h2>Новая задача кодинг-агента</h2>
              <p>Сформулируйте цель. Агент создаст или модифицирует файлы в изолированной Docker-песочнице.</p>
            </header>

            {error && (
              <div className="notice is-error" role="alert">
                <IconInterfaceAlertAlarmBell2 size={17} /> {error}
              </div>
            )}

            {!dockerReady && (
              <div className="notice is-warning" role="alert">
                <IconInterfaceAlertAlarmBell2 size={18} />
                <div style={{ flex: "1 1 auto" }}>
                  <strong>Песочница Docker недоступна:</strong>
                  <p data-i18n-skip>
                    {!status?.docker_cli_available
                      ? "Утилита Docker CLI не найдена в PATH или Docker Desktop не запущен. Запустите Docker Desktop для выполнения задач в контейнере."
                      : !status?.docker_daemon_available
                      ? "Служба Docker не отвечает. Убедитесь, что Docker Desktop запущен."
                      : !status?.docker_image_available
                      ? "Образ песочницы ещё не собран."
                      : formatDockerAvailabilityReason(status?.availability_reason)}
                  </p>
                </div>
                <button
                  type="button"
                  className="secondary"
                  style={{ minHeight: "32px", padding: "4px 10px", fontSize: "12px", alignSelf: "center" }}
                  onClick={(e) => {
                    animateButtonPress(e.currentTarget);
                    setActiveSection("environment");
                  }}
                >
                  Диагностика Docker
                </button>
              </div>
            )}

            <form onSubmit={submitTask} className="settings-form coding-cards-layout">
              <div className="coding-card">
                <div className="coding-card-heading">
                  <div className="coding-card-label">
                    <IconInterfaceCursorArrow2 size={16} aria-hidden="true" />
                    <strong>Постановка задачи</strong>
                  </div>
                </div>
                <div className="coding-field">
                  <label htmlFor="coding-task-objective">
                    Цель задачи
                  </label>
                  <textarea
                    id="coding-task-objective"
                    rows={5}
                    value={objective}
                    onChange={(event) => setObjective(event.target.value)}
                    placeholder="Например: напиши вспомогательный модуль parse_csv.py и юнит-тесты к нему с проверкой в sandbox"
                    disabled={busy || !status?.enabled}
                    required
                  />
                  <small>Опишите желаемый результат, формат входных и выходных данных, а также требования к тестам.</small>
                </div>
              </div>

              <div className="coding-card">
                <div className="coding-card-heading">
                  <div className="coding-card-label">
                    <IconInterfaceFilesFolderCopy2 size={16} aria-hidden="true" />
                    <strong>Контекст и файлы проекта</strong>
                  </div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                  <div className="coding-field">
                    <label htmlFor="coding-target-project">Проект для контекста</label>
                    <CustomSelect
                      id="coding-target-project"
                      value={targetProjectRoot}
                      disabled={busy || !status?.enabled}
                      onChange={(event) => setTargetProjectRoot(event.target.value)}
                    >
                      <option value="">Без проекта (изолированная папка)</option>
                      {(settings?.coding_allowed_project_roots ?? status?.allowed_project_roots ?? []).map((root) => (
                        <option key={root} value={root}>
                          {root}
                        </option>
                      ))}
                    </CustomSelect>
                    <small>Корневая папка репозитория, из которой агент может запросить исходный код.</small>
                  </div>

                  <div className="coding-field">
                    <label htmlFor="coding-context-files">Файлы для контекста</label>
                    <textarea
                      id="coding-context-files"
                      rows={4}
                      value={contextFiles}
                      onChange={(event) => setContextFiles(event.target.value)}
                      placeholder={"apps/backend/app/main.py\ntests/test_main.py"}
                      disabled={busy || !status?.enabled}
                    />
                    <small>Необязательно: относительные пути к файлам репозитория, по одному на строку.</small>
                  </div>
                </div>
              </div>

              <div className="coding-form-actions">
                <button
                  className="primary-button"
                  type="submit"
                  disabled={busy || !status?.enabled || !dockerReady || objective.trim().length < 3}
                  onClick={(e) => animateButtonPress(e.currentTarget)}
                >
                  <IconInterfaceCursorArrow2 size={16} /> Передать агенту
                </button>
                <button
                  className="secondary"
                  type="button"
                  onClick={(e) => {
                    animateButtonPress(e.currentTarget);
                    setActiveSection("tasks");
                  }}
                >
                  Отмена
                </button>
              </div>

              <p className="coding-hint" style={{ marginTop: "4px" }}>
                Без контекста задача начнётся в чистой рабочей папке:{" "}
                <span data-i18n-skip>{status?.workspace_root ?? "настройте CODING_WORKSPACE_ROOT"}</span>. Сеть и установка
                пакетов в контейнере запрещены из соображений безопасности.
              </p>
            </form>
          </>
        )}

        {activeSection === "environment" && (
          <>
            <header className="settings-heading" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "12px" }}>
              <div>
                <h2>Песочница и окружение Docker</h2>
                <p>Диагностика контейнеризации, образа песочницы и изоляции рабочих папок.</p>
              </div>
              <button
                className="secondary"
                type="button"
                onClick={(e) => {
                  animateButtonPress(e.currentTarget);
                  void refresh(true);
                }}
                disabled={busy}
              >
                <IconInterfaceSpirals size={16} className={busy ? "is-spinning" : ""} /> Обновить окружение
              </button>
            </header>

            {error && (
              <div className="notice is-error" role="alert">
                <IconInterfaceAlertAlarmBell2 size={17} /> {error}
              </div>
            )}

            <div className="coding-env-grid">
              <article className="coding-env-card">
                <div className="coding-env-card-heading">
                  <div className="coding-env-card-label">
                    <div className="coding-env-card-icon">
                      <IconComputerRobotCyborg1 size={17} aria-hidden="true" />
                    </div>
                    <strong>Кодинг-агент</strong>
                  </div>
                  <span className={`memory-status ${status?.enabled ? "active" : "deleted"}`}>
                    {status?.enabled ? "Включён" : "Отключён"}
                  </span>
                </div>
                <h3>{status?.enabled ? "Включён" : "Отключён"}</h3>
                <p>{status?.configured_enabled ? "Функция доступна в ядре Iris" : "Отключён администратором"}</p>
              </article>

              <article className="coding-env-card">
                <div className="coding-env-card-heading">
                  <div className="coding-env-card-label">
                    <div className="coding-env-card-icon">
                      <IconComputerDatabase size={17} aria-hidden="true" />
                    </div>
                    <strong>Docker Daemon</strong>
                  </div>
                  <span className={`memory-status ${status?.docker_daemon_available ? "active" : "deleted"}`}>
                    {status?.docker_daemon_available ? "Запущен" : "Недоступен"}
                  </span>
                </div>
                <h3>{status?.docker_daemon_available ? "Запущен" : "Недоступен"}</h3>
                <p>{formatDockerAvailabilityReason(status?.availability_reason)}</p>
              </article>

              <article className="coding-env-card">
                <div className="coding-env-card-heading">
                  <div className="coding-env-card-label">
                    <div className="coding-env-card-icon">
                      <IconProgrammingScript2 size={17} aria-hidden="true" />
                    </div>
                    <strong>Образ песочницы</strong>
                  </div>
                  <span className={`memory-status ${status?.docker_image_available ? "active" : "candidate"}`}>
                    {status?.docker_image_available ? "Собран" : "Не собран"}
                  </span>
                </div>
                <h3>{status?.docker_image_available ? "Образ готов" : "Образ не собран"}</h3>
                <p data-i18n-skip>{status?.docker_image_name || "neuroasist-sandbox"}</p>
              </article>

              <article className="coding-env-card">
                <div className="coding-env-card-heading">
                  <div className="coding-env-card-label">
                    <div className="coding-env-card-icon">
                      <IconInterfaceTimeStopWatchCircle size={17} aria-hidden="true" />
                    </div>
                    <strong>Текущая активность</strong>
                  </div>
                  <span className={`memory-status ${active ? "candidate" : "active"}`}>
                    {active ? "В работе" : "Свободен"}
                  </span>
                </div>
                <h3>{active ? statusLabel(active.status) : "Свободен"}</h3>
                <p>
                  {active ? (
                    <span data-i18n-skip>{active.objective.slice(0, 60)}…</span>
                  ) : (
                    `Задач в очереди: ${status?.queued_count ?? 0}`
                  )}
                </p>
              </article>
            </div>

            <section style={{ marginTop: "14px" }}>
              <h3 style={{ fontSize: "15px", fontWeight: 650, margin: "0 0 12px" }}>Параметры окружения</h3>
              <div className="settings-grid system-status-grid">
                <InfoCard label="Docker CLI" value={status?.docker_cli_available ? "Доступен в PATH" : "Не найден"} />
                <InfoCard label="Образ песочницы" value={status?.docker_image_name || "neuroasist-sandbox"} />
                <InfoCard label="Workspace Root" value={status?.workspace_root || "Не задан"} />
                <InfoCard label="Текущая модель" value={status?.model || settings?.coding_model || "—"} />
                <InfoCard label="Задач в очереди" value={String(status?.queued_count ?? 0)} />
                <InfoCard label="Изоляция сети" value="Запрещена (network: none)" />
              </div>
            </section>
          </>
        )}

        {activeSection === "settings" && settings && (
          <>
            <header className="settings-heading">
              <h2>Параметры кодинг-агента</h2>
              <p>Управление моделью, автоматическим делегированием из диалога и репозиториями.</p>
            </header>

            {error && (
              <div className="notice is-error" role="alert">
                <IconInterfaceAlertAlarmBell2 size={17} /> {error}
              </div>
            )}

            {!settings.coding_api_key_configured && (
              <div className="notice is-warning" role="alert">
                <IconInterfaceAlertAlarmBell2 size={17} />
                <div>
                  <strong>API-ключ не настроен:</strong>
                  <p>Для работы кодинг-агента сохраните отдельный Coding API-ключ в настройках приложения.</p>
                  <button className="secondary" type="button" onClick={onOpenApiSettings}>
                    Открыть настройки API
                  </button>
                </div>
              </div>
            )}

            <div className="coding-cards-layout">
              <div className="coding-card">
                <div className="coding-card-heading">
                  <div className="coding-card-label">
                    <IconInterfaceSettingGaugeDashboard1 size={16} aria-hidden="true" />
                    <strong>Режим работы</strong>
                  </div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                  <CodingSwitch
                    checked={settings.coding_agent_enabled}
                    label="Включить Coding Agent"
                    description="Позволяет ставить задачи и делегировать выполнение кода агенту."
                    disabled={busy || !settings.coding_api_key_configured}
                    onChange={(checked) => void changeSettings({ coding_agent_enabled: checked })}
                  />

                  <CodingSwitch
                    checked={settings.coding_auto_delegate}
                    label="Автоделегирование из диалога"
                    description="Основной диалог Iris распознаёт запросы на код и автоматически передаёт их в очередь."
                    disabled={busy || !settings.coding_agent_enabled}
                    onChange={(checked) => void changeSettings({ coding_auto_delegate: checked })}
                  />
                </div>
              </div>

              <div className="coding-card">
                <div className="coding-card-heading">
                  <div className="coding-card-label">
                    <IconComputerDatabase size={16} aria-hidden="true" />
                    <strong>Модель и рабочая папка</strong>
                  </div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                  <div className="coding-field">
                    <label htmlFor="coding-model-select">Модель для кодинга</label>
                    <CustomSelect
                      id="coding-model-select"
                      value={settings.coding_model}
                      disabled={busy}
                      onChange={(event) =>
                        void changeSettings({ coding_model: event.target.value as PublicSettings["coding_model"] })
                      }
                    >
                      {settings.coding_available_models.map((model) => (
                        <option key={model} value={model}>
                          {model}
                        </option>
                      ))}
                    </CustomSelect>
                    <small>Модель, ответственная за анализ контекста, написание кода и формирование diff.</small>
                  </div>

                  <div className="coding-field">
                    <label htmlFor="coding-project-root-select">Проект контекста по умолчанию</label>
                    <CustomSelect
                      id="coding-project-root-select"
                      value={settings.coding_project_root}
                      disabled={busy}
                      onChange={(event) => void changeSettings({ coding_project_root: event.target.value })}
                    >
                      {settings.coding_allowed_project_roots.map((root) => (
                        <option key={root} value={root}>
                          {root}
                        </option>
                      ))}
                    </CustomSelect>
                    <small>Разрешённый локальный проект для чтения контекста.</small>
                  </div>

                  <div className="coding-field">
                    <label htmlFor="coding-workspace-name-input">Префикс имени workspace</label>
                    <input
                      id="coding-workspace-name-input"
                      type="text"
                      value={workspaceName}
                      disabled={busy}
                      maxLength={80}
                      onBlur={(event) => {
                        if (event.target.value && event.target.value !== settings.coding_workspace_name) {
                          void changeSettings({ coding_workspace_name: event.target.value });
                        }
                      }}
                      onChange={(event) => setWorkspaceName(event.target.value)}
                      placeholder="coding-agent-workspace"
                    />
                    <small>Имя директории или префикс для временных рабочих областей песочницы.</small>
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
