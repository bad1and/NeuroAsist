import {
  IconCitiesPoliticsVote,
  IconComputerDatabase,
  IconComputerRobotCyborg1,
  IconComputerSmartWatch2,
  IconEntertainmentGamingEsports,
  IconHealthBeautyMoustache,
  IconHealthMedicalHeartCare1,
  IconInterfaceAlertAlarmBell2,
  IconInterfaceBookmark,
  IconInterfaceCalendarMark,
  IconInterfaceContentArchive,
  IconInterfaceContentFire,
  IconInterfaceDeleteBin3,
  IconInterfaceFavoriteLike1,
  IconInterfaceSearch,
  IconInterfaceSettingGaugeDashboard1,
  IconInterfaceSpirals,
  IconInterfaceTextFormattingTextStyle,
  IconInterfaceTextFormattingFilter1,
  IconMoneyCashierTag,
  type CustomIconProps,
} from "./CustomIcons";
import { CustomSelect } from "./components/CustomSelect";
import { useEffect, useRef, useState, type ComponentType } from "react";

import {
  deleteMemory,
  getMemories,
  getMemoryAudit,
  getMemoryCommitments,
  getMemoryConflicts,
  getMemoryDiagnostics,
  getMemoryTopics,
  closeMemoryCommitment,
} from "./api";
import type {
  MemoryAuditItem,
  MemoryCommitment,
  MemoryDiagnostics,
  MemoryItem,
  MemoryStatus,
  MemoryTopic,
} from "./types";
import {
  animateButtonPress,
  animateCardRemove,
  animatePageEnter,
  animateStaggerCards,
  animateTabSwitch,
  useAnimeScope,
} from "./animations";

type MemorySection = "all" | "active" | "topics" | "commitments" | "archive" | "diagnostics";

const STATUS_LABELS: Record<MemoryStatus | "all", string> = {
  all: "Все",
  active: "Сохранённые",
  superseded: "Заменённые",
  deleted: "Удалённые",
  rejected: "Отклонённые",
  expired: "Истёкшие",
};

const MEMORY_SECTIONS: Array<{ id: MemorySection; label: string; icon: ComponentType<CustomIconProps> }> = [
  { id: "all", label: "Текущие", icon: IconComputerRobotCyborg1 },
  { id: "active", label: "Сохранённые", icon: IconInterfaceFavoriteLike1 },
  { id: "topics", label: "Темы", icon: IconMoneyCashierTag },
  { id: "commitments", label: "Планы и обещания", icon: IconInterfaceCalendarMark },
  { id: "archive", label: "Архив", icon: IconInterfaceContentArchive },
  { id: "diagnostics", label: "Диагностика", icon: IconInterfaceSettingGaugeDashboard1 },
];



const MEMORY_LABELS: Record<string, string> = {
  "user.name": "Имя пользователя",
  "assistant.developer": "Разработчик Iris",
  "assistant.developer_count": "Количество разработчиков Iris",
  "user.likes_category": "Любимый жанр",
  "user.likes_game": "Любимая игра",
  "user.preference": "Предпочтение",
  "user.note": "Заметка",
  "user.relationship.friend": "Друг",
  "user.game_detail": "Деталь игры",
  "user.current_mood": "Текущее настроение",
  "user.current_activity": "Текущее занятие",
  "user.current_goal": "Текущая цель",
  "user.prefers_response_length": "Стиль ответов",
  "user.health_constraint": "Ограничение здоровья",
  "user.constraint": "Ограничение",
  name: "Имя пользователя",
  developer: "Разработчик Iris",
  developers: "Разработчики Iris",
  developerof: "Разработчик Iris",
  is_developer_of: "Разработчик Iris",
};

function memoryLabel(memory: MemoryItem): string {
  return MEMORY_LABELS[memory.slot_key ?? ""] ?? MEMORY_LABELS[memory.predicate] ?? memory.predicate;
}

function getSlotIcon(memory: MemoryItem): ComponentType<CustomIconProps> {
  const key = (memory.slot_key ?? memory.predicate ?? "").toLowerCase();
  if (key.includes("name")) return IconHealthBeautyMoustache;
  if (key.includes("developer")) return IconComputerSmartWatch2;
  if (key.includes("game")) return IconEntertainmentGamingEsports;
  if (key.includes("likes") || key.includes("preference")) return IconInterfaceFavoriteLike1;
  if (key.includes("mood") || key.includes("activity") || key.includes("goal")) return IconInterfaceContentFire;
  if (key.includes("style") || key.includes("length") || key.includes("response")) return IconInterfaceTextFormattingTextStyle;
  if (key.includes("health") || key.includes("constraint")) return IconHealthMedicalHeartCare1;
  if (key.includes("friend") || key.includes("relationship")) return IconCitiesPoliticsVote;
  return IconComputerDatabase;
}

function formatMemoryDate(dateString?: string | null, id?: string | null) {
  let time: number | null = null;
  
  if (dateString) {
    const d = new Date(dateString);
    if (!isNaN(d.getTime())) time = d.getTime();
  }
  
  if (!time && id && id.length === 26) {
    const CrockfordBase32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
    let parsed = 0;
    let valid = true;
    for (let i = 0; i < 10; i++) {
      const val = CrockfordBase32.indexOf(id[i].toUpperCase());
      if (val === -1) { valid = false; break; }
      parsed = parsed * 32 + val;
    }
    if (valid && parsed > 1500000000000 && parsed < 2500000000000) {
      time = parsed;
    }
  }

  if (!time) return null;
  
  const date = new Date(time);
  const now = new Date();
  
  const isToday = date.getDate() === now.getDate() && date.getMonth() === now.getMonth() && date.getFullYear() === now.getFullYear();
  
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  const isYesterday = date.getDate() === yesterday.getDate() && date.getMonth() === yesterday.getMonth() && date.getFullYear() === yesterday.getFullYear();

  const timeStr = date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  
  if (isToday) {
    return `Сегодня, ${timeStr}`;
  }
  if (isYesterday) {
    return `Вчера, ${timeStr}`;
  }
  
  const isSameYear = date.getFullYear() === now.getFullYear();
  const dateStr = date.toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "short",
    ...(isSameYear ? {} : { year: "numeric" })
  }).replace(" г.", "");
  
  return `${dateStr}, ${timeStr}`;
}

export function MemoryPage() {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [topics, setTopics] = useState<MemoryTopic[]>([]);
  const [commitments, setCommitments] = useState<MemoryCommitment[]>([]);
  const [conflicts, setConflicts] = useState<Array<{ id: string; reason: string; status: string }>>([]);
  const [diagnostics, setDiagnostics] = useState<MemoryDiagnostics>({ queue: {}, runs: [] });
  const [section, setSection] = useState<MemorySection>("all");
  const [query, setQuery] = useState("");
  const [sortOrder, setSortOrder] = useState<"date-desc" | "date-asc" | "alpha-asc" | "alpha-desc">("date-desc");
  const [audit, setAudit] = useState<Record<string, MemoryAuditItem[]>>({});
  const [message, setMessage] = useState<string | null>(null);

  const containerRef = useAnimeScope<HTMLElement>((scope, root) => {
    animatePageEnter(root);
  }, []);

  const contentRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (contentRef.current) {
      animatePageEnter(contentRef.current);
    }
  }, [section]);

  useEffect(() => {
    if (listRef.current) {
      animateStaggerCards(listRef.current, ".memory-card", 35);
    }
  }, [section, items, topics, commitments, diagnostics, conflicts]);

  const refresh = async () => {
    try {
      if (section === "topics") {
        setTopics((await getMemoryTopics()).items);
        setMessage(null);
        return;
      }
      if (section === "commitments") {
        setCommitments((await getMemoryCommitments()).items);
        setMessage(null);
        return;
      }
      if (section === "diagnostics") {
        const [conflictData, diagnosticData] = await Promise.all([getMemoryConflicts(), getMemoryDiagnostics()]);
        setConflicts(conflictData.items);
        setDiagnostics(diagnosticData);
        setMessage(null);
        return;
      }
      const result = await getMemories(
        section === "all" || section === "archive" ? undefined : section,
        query || undefined,
      );
      setItems(
        section === "archive"
          ? result.items.filter((item) => item.status !== "active")
          : section === "all"
            ? result.items.filter((item) => item.status === "active")
            : result.items,
      );
      setMessage(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Память недоступна");
    }
  };

  useEffect(() => {
    void refresh();
  }, [section]);

  const action = async (run: () => Promise<unknown>) => {
    try {
      await run();
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось выполнить действие");
    }
  };

  const handleForget = async (e: React.MouseEvent<HTMLElement>, id: string) => {
    const cardEl = (e.currentTarget.closest(".memory-card") as HTMLElement) || null;
    if (cardEl) {
      animateCardRemove(cardEl, () => {
        void action(() => deleteMemory(id));
      });
    } else {
      void action(() => deleteMemory(id));
    }
  };

  const sortedItems = [...items].sort((a, b) => {
    if (sortOrder === "date-desc") return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    if (sortOrder === "date-asc") return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
    const aLabel = memoryLabel(a).toLowerCase();
    const bLabel = memoryLabel(b).toLowerCase();
    if (sortOrder === "alpha-asc") return aLabel.localeCompare(bLabel);
    if (sortOrder === "alpha-desc") return bLabel.localeCompare(aLabel);
    return 0;
  });

  const sortedTopics = [...topics].sort((a, b) => {
    if (sortOrder === "date-desc") {
      return (b as any).created_at && (a as any).created_at
        ? new Date((b as any).created_at).getTime() - new Date((a as any).created_at).getTime()
        : b.id.localeCompare(a.id);
    }
    if (sortOrder === "date-asc") {
      return (a as any).created_at && (b as any).created_at
        ? new Date((a as any).created_at).getTime() - new Date((b as any).created_at).getTime()
        : a.id.localeCompare(b.id);
    }
    if (sortOrder === "alpha-asc") return a.title.localeCompare(b.title);
    if (sortOrder === "alpha-desc") return b.title.localeCompare(a.title);
    return 0;
  });

  const sortedCommitments = [...commitments].sort((a, b) => {
    if (sortOrder === "date-desc") {
      return (b as any).created_at && (a as any).created_at
        ? new Date((b as any).created_at).getTime() - new Date((a as any).created_at).getTime()
        : b.id.localeCompare(a.id);
    }
    if (sortOrder === "date-asc") {
      return (a as any).created_at && (b as any).created_at
        ? new Date((a as any).created_at).getTime() - new Date((b as any).created_at).getTime()
        : a.id.localeCompare(b.id);
    }
    if (sortOrder === "alpha-asc") return a.title.localeCompare(b.title);
    if (sortOrder === "alpha-desc") return b.title.localeCompare(a.title);
    return 0;
  });

  return (
    <section className="panel memory-panel" ref={containerRef}>
      <nav className="settings-navigation memory-navigation" aria-label="Разделы памяти">
        {MEMORY_SECTIONS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            className={`settings-nav-direct${section === id ? " is-active" : ""}`}
            aria-current={section === id ? "page" : undefined}
            onClick={(e) => {
              animateButtonPress(e.currentTarget);
              setSection(id);
            }}
          >
            <Icon size={20} aria-hidden="true" />
            <span>{label}</span>
          </button>
        ))}
      </nav>

      <div className="memory-content" ref={contentRef}>
        <header className="memory-heading">
          <div className="memory-toolbar">
            <form
              className="search-form compact"
              onSubmit={(event) => {
                event.preventDefault();
                void refresh();
              }}
            >
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Поиск по памяти"
                aria-label="Поиск по памяти"
              />
              {query && (
                <button
                  type="button"
                  className="search-clear-btn"
                  onClick={() => {
                    setQuery("");
                    void refresh();
                  }}
                  aria-label="Очистить"
                >
                  ✕
                </button>
              )}
              <button
                className="icon-button"
                type="button"
                onClick={(e) => {
                  animateButtonPress(e.currentTarget);
                  void refresh();
                }}
                aria-label="Обновить память"
                title="Обновить память"
              >
                <IconInterfaceSpirals size={17} />
              </button>
              <button
                className="icon-button search-submit"
                type="submit"
                aria-label="Найти в памяти"
                title="Найти в памяти"
              >
                <IconInterfaceSearch size={17} />
              </button>
            </form>
          </div>
          <CustomSelect
            value={sortOrder}
            onChange={(event) => setSortOrder(event.target.value as any)}
            prefixIcon={<IconInterfaceTextFormattingFilter1 size={17} aria-hidden="true" />}
            style={{ width: "auto" }}
          >
            <option value="date-desc">Сначала новые</option>
            <option value="date-asc">Сначала старые</option>
            <option value="alpha-asc">От А до Я</option>
            <option value="alpha-desc">От Я до А</option>
          </CustomSelect>
        </header>

        {message && (
          <p className="error-text" role="alert">
            {message}
          </p>
        )}

        <div className="memory-list" ref={listRef}>
          {section === "topics" && (
            <>
              {sortedTopics.length ? (
                sortedTopics.map((topic) => (
                  <article className="memory-card" key={topic.id}>
                    <div className="memory-card-main">
                      <div className="memory-card-heading">
                        <div className="memory-card-label">
                          <IconMoneyCashierTag size={14} aria-hidden="true" />
                          <strong>Тема</strong>
                        </div>
                        <div className="memory-heading-badges">
                          {topic.user_locked && <IconInterfaceBookmark size={14} aria-label="Закреплённая тема" />}
                        </div>
                      </div>
                      <strong data-i18n-skip>
                        {topic.title}
                      </strong>
                      <p data-i18n-skip>
                        {topic.summary_text || "Краткое описание ещё не сформировано."}
                      </p>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: "8px", marginTop: "auto" }}>
                        <small>Связи: {topic.links.length} · доказательства: {topic.evidence.length}</small>
                      </div>
                      {formatMemoryDate((topic as any).created_at, topic.id) && (
                        <small style={{ position: "absolute", bottom: "14px", right: "18px", color: "var(--color-text-soft)", whiteSpace: "nowrap" }}>
                          {formatMemoryDate((topic as any).created_at, topic.id)}
                        </small>
                      )}
                    </div>
                  </article>
                ))
              ) : (
                <div className="empty-state">
                  <IconMoneyCashierTag size={28} aria-hidden="true" />
                  <strong>Тем пока нет</strong>
                  <span>Iris сформирует тематические кластеры в процессе общения.</span>
                </div>
              )}
            </>
          )}

          {section === "commitments" && (
            <>
              {sortedCommitments.length ? (
                sortedCommitments.map((commitment) => (
                  <article className="memory-card" key={commitment.id}>
                    <div className="memory-card-main">
                      <div className="memory-card-heading">
                        <div className="memory-card-label">
                          <IconInterfaceCalendarMark size={14} aria-hidden="true" />
                          <strong>{commitment.kind || "План"}</strong>
                        </div>
                        <div className="memory-heading-badges">
                          <span className={`memory-status ${commitment.status === "open" ? "active" : "deleted"}`}>
                            {commitment.status}
                          </span>
                        </div>
                      </div>
                      <strong data-i18n-skip>
                        {commitment.title}
                      </strong>
                      <p data-i18n-skip>
                        {commitment.details}
                      </p>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: "8px", marginTop: "auto" }}>
                        <small>{commitment.kind} · уверенность: {Math.round(commitment.confidence * 100)}%</small>
                      </div>
                      {formatMemoryDate((commitment as any).created_at, commitment.id) && (
                        <small style={{ position: "absolute", bottom: "14px", right: "18px", color: "var(--color-text-soft)", whiteSpace: "nowrap" }}>
                          {formatMemoryDate((commitment as any).created_at, commitment.id)}
                        </small>
                      )}
                    </div>
                    {commitment.status === "open" && (
                      <div className="memory-actions">
                        <button
                          className="secondary memory-close-btn"
                          type="button"
                          onClick={() => void action(() => closeMemoryCommitment(commitment.id))}
                          title="Отметить выполненным"
                        >
                          Завершить
                        </button>
                      </div>
                    )}
                  </article>
                ))
              ) : (
                <div className="empty-state">
                  <IconInterfaceCalendarMark size={28} aria-hidden="true" />
                  <strong>Планов и обещаний пока нет</strong>
                  <span>Договорённости и задачи из разговоров появятся здесь автоматически.</span>
                </div>
              )}
            </>
          )}

          {section === "diagnostics" && (
            <>
              <div className="memory-diagnostics-grid">
                {diagnostics.integrity && (
                  <article className="memory-card">
                    <div className="memory-card-main">
                      <div className="memory-card-heading">
                        <div className="memory-card-label">
                          <IconInterfaceSettingGaugeDashboard1
                            size={14}
                            aria-hidden="true"
                          />
                          <strong>Целостность</strong>
                        </div>
                        <span
                          className={`memory-status ${diagnostics.integrity.state === "healthy" ? "active" : "deleted"}`}
                        >
                          {diagnostics.integrity.state}
                        </span>
                      </div>
                      <strong>Целостность памяти</strong>
                      <p>
                        Активные конфликты: {diagnostics.integrity.active_conflicts} · без канонического слота:{" "}
                        {diagnostics.integrity.noncanonical_active} · без источников:{" "}
                        {diagnostics.integrity.provenance_missing}
                      </p>
                      <small>
                        Рассинхронизация источников: {diagnostics.integrity.source_count_mismatches} · кандидаты:{" "}
                        {diagnostics.integrity.candidate_count ?? 0} · ограничения:{" "}
                        {diagnostics.integrity.guards_installed ? "включены" : "не установлены"}
                      </small>
                    </div>
                  </article>
                )}
                {diagnostics.autonomy && (
                  <article className="memory-card">
                    <div className="memory-card-main">
                      <div className="memory-card-heading">
                        <div className="memory-card-label">
                          <IconComputerRobotCyborg1 size={14} aria-hidden="true" />
                          <strong>Автономия</strong>
                        </div>
                        <span
                          className={`memory-status ${diagnostics.autonomy.candidate_count === 0 ? "active" : "deleted"}`}
                        >
                          {diagnostics.autonomy.candidate_count === 0 ? "автономно" : "нарушение"}
                        </span>
                      </div>
                      <strong>Автономные решения</strong>
                      <p>
                        Принято: {diagnostics.autonomy.decisions.accepted ?? 0} · отклонено:{" "}
                        {Object.entries(diagnostics.autonomy.decisions)
                          .filter(([key]) => key.startsWith("rejected"))
                          .reduce((sum, [, count]) => sum + count, 0)}{" "}
                        · открытых уточнений: {diagnostics.autonomy.open_clarifications}
                      </p>
                      <small>Ручная очередь: {diagnostics.autonomy.candidate_count}</small>
                    </div>
                  </article>
                )}
                {diagnostics.index_health && (
                  <article className="memory-card">
                    <div className="memory-card-main">
                      <div className="memory-card-heading">
                        <div className="memory-card-label">
                          <IconInterfaceSearch size={14} aria-hidden="true" />
                          <strong>Индекс</strong>
                        </div>
                        <span
                          className={`memory-status ${diagnostics.index_health.state === "healthy" ? "active" : "deleted"}`}
                        >
                          {diagnostics.index_health.state}
                        </span>
                      </div>
                      <strong>Здоровье поискового индекса</strong>
                      <p>
                        SQLite:{" "}
                        {Object.values(diagnostics.active_by_namespace ?? {}).reduce((sum, count) => sum + count, 0)} ·
                        отсутствует: {diagnostics.index_health.missing_ids.length} · устарело:{" "}
                        {diagnostics.index_health.stale_ids.length}
                      </p>
                      <small>
                        {diagnostics.index_health.degraded_reason ??
                          "Chroma синхронизирована; SQLite остаётся источником истины."}
                      </small>
                    </div>
                  </article>
                )}
                {diagnostics.repair && (
                  <article className="memory-card">
                    <div className="memory-card-main">
                      <div className="memory-card-heading">
                        <div className="memory-card-label">
                          <IconInterfaceSpirals size={14} aria-hidden="true" />
                          <strong>Автопочинка</strong>
                        </div>
                        <span className="memory-status active">{diagnostics.repair.status}</span>
                      </div>
                      <strong>Автопочинка памяти</strong>
                      <p>
                        Канонизировано: {Number(diagnostics.repair.result.canonicalized ?? 0)} · устранено дублей:{" "}
                        {Number(
                          diagnostics.repair.result.duplicates_superseded ??
                            diagnostics.repair.result.topics_merged ??
                            0,
                        )}{" "}
                        · перенесено доказательств: {Number(diagnostics.repair.result.evidence_copied ?? 0)}
                      </p>
                      <small>{diagnostics.repair.repair_key}</small>
                    </div>
                  </article>
                )}
                {diagnostics.runs.map((run) => (
                  <article className="memory-card" key={run.id}>
                    <div className="memory-card-main">
                      <div className="memory-card-heading">
                        <div className="memory-card-label">
                          <IconInterfaceContentArchive size={14} aria-hidden="true" />
                          <strong>Консолидация</strong>
                        </div>
                        <span className={`memory-status ${run.result.outcome === "applied" ? "active" : "deleted"}`}>
                          {run.result.outcome ?? run.status}
                        </span>
                      </div>
                      <strong>Консолидация памяти</strong>
                      <p>
                        Предложено: {run.result.proposed ?? 0} · сохранено: {run.result.saved ?? 0} · отклонено:{" "}
                        {run.result.discarded ?? 0}
                      </p>
                      <small>
                        {run.diagnostics.error_codes?.length
                          ? `Причина: ${run.diagnostics.error_codes.join(", ")}`
                          : "Ошибок нет"}{" "}
                        · {run.diagnostics.model ?? "локальный путь"}
                      </small>
                    </div>
                  </article>
                ))}
                {conflicts.map((conflict) => (
                  <article className="memory-card" key={conflict.id}>
                    <div className="memory-card-main">
                      <strong>Конфликт: {conflict.status}</strong>
                      <p>{conflict.reason}</p>
                    </div>
                  </article>
                ))}
              </div>
              {!diagnostics.runs.length &&
                !conflicts.length &&
                !diagnostics.integrity &&
                !diagnostics.autonomy &&
                !diagnostics.index_health &&
                !diagnostics.repair && (
                  <div className="empty-state">
                    <IconInterfaceAlertAlarmBell2 size={28} />
                    <strong>Диагностических записей пока нет</strong>
                    <span>Здесь появятся результаты фоновой консолидации и понятные причины нулевой записи.</span>
                  </div>
                )}
            </>
          )}

          {!(["topics", "commitments", "diagnostics"] as MemorySection[]).includes(section) && (
            <>
              {sortedItems.length ? (
                sortedItems.map((memory) => {
                  const SlotIcon = getSlotIcon(memory);
                  return (
                    <article className="memory-card" key={memory.id}>
                      <div className="memory-card-main">
                        <div className="memory-card-heading">
                          <div className="memory-card-label">
                            <SlotIcon size={14} aria-hidden="true" />
                            <strong>{memoryLabel(memory)}</strong>
                          </div>
                          <div className="memory-heading-badges">
                            {section === "archive" && (
                              <span className={`memory-status ${memory.status}`}>{STATUS_LABELS[memory.status]}</span>
                            )}
                            {memory.user_locked && (
                              <IconInterfaceBookmark size={14} aria-label="Закреплённая запись" />
                            )}
                          </div>
                        </div>

                        <p data-i18n-skip>
                          {memory.value_text}
                        </p>

                        {section === "archive" && memory.replacement && (
                          <p className="memory-replacement">
                            <span>Заменено на: </span>
                            <span data-i18n-skip>{memory.replacement.value_text}</span>
                          </p>
                        )}

                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: "8px", marginTop: "auto" }}>
                          <small>
                            {(memory.source_count ?? memory.source_message_ids.length)
                              ? `Источник: ${memory.source_count ?? memory.source_message_ids.length} сообщ.`
                              : "Источник не указан"}{" "}
                            · {section === "archive" ? "использовалось до замены" : "использовано"}:{" "}
                            {memory.access_count}
                          </small>
                        </div>
                        {formatMemoryDate(memory.created_at, memory.id) && (
                          <small style={{ position: "absolute", bottom: "14px", right: "18px", color: "var(--color-text-soft)", whiteSpace: "nowrap" }}>
                            {formatMemoryDate(memory.created_at, memory.id)}
                          </small>
                        )}
                      </div>

                      <div className="memory-actions">
                        <details className="memory-action-menu">
                          <summary className="icon-button" role="button" aria-label="Дополнительные действия">
                            <IconInterfaceSpirals size={17} aria-hidden="true" />
                          </summary>
                          <div>
                            <button
                              type="button"
                              onClick={async () => {
                                const nextAudit = await getMemoryAudit(memory.id);
                                setAudit((current) => ({ ...current, [memory.id]: nextAudit.items }));
                              }}
                            >
                              <IconInterfaceAlertAlarmBell2 size={16} aria-hidden="true" />
                              История записи
                            </button>
                            {memory.status !== "deleted" && (
                              <button
                                className="is-danger"
                                type="button"
                                onClick={(e) => void handleForget(e, memory.id)}
                              >
                                <IconInterfaceDeleteBin3 size={16} aria-hidden="true" />
                                Забыть
                              </button>
                            )}
                          </div>
                        </details>
                      </div>

                      {audit[memory.id] && (
                        <details className="memory-audit" open>
                          <summary>История записи</summary>
                          <p>{audit[memory.id].map((item) => `${item.action} (${item.actor})`).join(" → ")}</p>
                        </details>
                      )}
                    </article>
                  );
                })
              ) : (
                <div className="empty-state">
                  <IconComputerRobotCyborg1 size={28} aria-hidden="true" />
                  <strong>Записей пока нет</strong>
                  <span>Помощник предложит факты для сохранения после разговора.</span>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}

