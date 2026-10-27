import { Disclosure, DisclosureTrigger } from "./components/Disclosure";
import type { SearchFocus } from "./search-navigation";
import { LoadingRing } from "./components/LoadingRing";
import { MemeLibraryPanel } from "./meme-library";
import { OpinionsPanel } from "./opinions";
import { MaterialButton } from "./components/MaterialButton";
import { RemindersPanel } from "./components/RemindersPanel";
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
import { AppDialog } from "./components/AppDialog";
import {
  IconInterfaceArrowUpRight as ArrowUpRight,
  IconInterfaceClock as Clock3,
  IconMailChatBubbleTextSquare as MessagesSquare,
  IconInterfaceMore as MoreHorizontal,
  IconInterfaceCross as X,
} from "./CustomIcons";
import { startTransition, useEffect, useId, useRef, useState, type ComponentType, type ReactNode } from "react";

import {
  deleteMemory,
  purgeMemory,
  getMemories,
  getMemoryAudit,
  getMemoryCommitments,
  getMemoryConflicts,
  getMemoryDiagnostics,
  getMemoryTopics,
  restoreMemory,
  updateMemory,
} from "./api";
import type {
  MemoryAuditItem,
  MemoryCommitment,
  MemoryDiagnostics,
  MemoryItem,
  MemoryStatus,
  MemoryTopic,
} from "./types";
import { notify } from "./notifications";
import {
  animateButtonPress,
  animatePageEnter,
  animateStaggerCards,
  animateTabSwitch,
  animate,
  prefersReducedMotion,
  useAnimeScope,
} from "./animations";
import { currentInterfaceLocale, interfaceIntlLocale } from "./i18n";

type MemorySection = "all" | "active" | "topics" | "commitments" | "archive" | "diagnostics" | "memes" | "opinions";

const STATUS_LABELS: Record<MemoryStatus | "all", string> = {
  all: "Все",
  active: "Сохранено",
  superseded: "Есть новая версия",
  deleted: "В архиве",
  rejected: "Не принято",
  expired: "Срок истёк",
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
  "user.dislike": "Не нравится",
  "user.interest": "Интерес",
  "user.habit": "Привычка",
  "user.note": "Заметка",
  "user.relationship.friend": "Друг",
  "user.pet": "Питомец",
  "user.game_detail": "Деталь игры",
  "user.current_mood": "Текущее настроение",
  "user.current_activity": "Текущее занятие",
  "user.current_goal": "Текущая цель",
  "user.occupation": "Работа",
  "user.skill": "Навык",
  "user.learning": "Изучает",
  "user.project": "Проект",
  "user.location": "Местоположение",
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

const memoryDateFormats = new Map<string, {
  time: Intl.DateTimeFormat; short: Intl.DateTimeFormat; year: Intl.DateTimeFormat;
}>();
function getMemoryDateFormats(locale: string) {
  let formats = memoryDateFormats.get(locale);
  if (!formats) {
    formats = {
      time: new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }),
      short: new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" }),
      year: new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", year: "numeric" }),
    };
    memoryDateFormats.set(locale, formats);
  }
  return formats;
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

  const locale = currentInterfaceLocale();
  const formats = getMemoryDateFormats(interfaceIntlLocale());
  const timeStr = formats.time.format(date);
  
  if (isToday) {
    return locale === "en" ? `Today, ${timeStr}` : `Сегодня, ${timeStr}`;
  }
  if (isYesterday) {
    return locale === "en" ? `Yesterday, ${timeStr}` : `Вчера, ${timeStr}`;
  }
  
  const isSameYear = date.getFullYear() === now.getFullYear();
  let dateStr = (isSameYear ? formats.short : formats.year).format(date);
  if (locale === "ru") dateStr = dateStr.replace(" г.", "");
  
  return `${dateStr}, ${timeStr}`;
}

function memorySourceCount(count: number): string {
  if (currentInterfaceLocale() === "en") return `${count} ${count === 1 ? "message" : "messages"}`;
  const last = count % 10, lastTwo = count % 100;
  const word = last === 1 && lastTwo !== 11 ? "сообщение" : last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14) ? "сообщения" : "сообщений";
  return `${count} ${word}`;
}

function MemoryRecordFooter({ memory, archived, onOpenSource }: {
  memory: MemoryItem; archived: boolean; onOpenSource?: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const detailsId = useId();
  const detailsRef = useRef<HTMLDivElement>(null);
  const sourceIds = [...new Set(memory.source_message_ids ?? [])];
  const sourceCount = memory.source_count ?? sourceIds.length;
  const createdAt = formatMemoryDate(memory.created_at, memory.id);
  const preciseDate = (value: string) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? undefined : date.toLocaleString(interfaceIntlLocale(), { dateStyle: "long", timeStyle: "short" });
  };
  useEffect(() => {
    if (!expanded || !detailsRef.current || prefersReducedMotion()) return;
    const motion = animate(detailsRef.current, { opacity: [0, 1], translateY: [-4, 0], duration: 180, ease: "outQuad" });
    return () => { motion.revert(); };
  }, [expanded]);

  return <div className="memory-record-footer">
    <div className="memory-record-meta">
      {createdAt && <time dateTime={memory.created_at || undefined} title={preciseDate(memory.created_at)} data-i18n-skip>
        <Clock3 size={14} aria-hidden="true" />{createdAt}
      </time>}
      <span><MessagesSquare size={14} aria-hidden="true" />{sourceCount > 0 ? <span data-i18n-skip>{memorySourceCount(sourceCount)}</span> : "Источник не указан"}</span>
    </div>
    <div className="memory-record-controls">
      {sourceIds.length > 0 && onOpenSource && <MaterialButton materialKey={`memory.source.${memory.id}`} className="secondary memory-source-button" type="button" onClick={() => onOpenSource(sourceIds[0])}>
        <MessagesSquare size={16} aria-hidden="true" />Открыть источник<ArrowUpRight size={14} aria-hidden="true" />
      </MaterialButton>}
      <DisclosureTrigger materialKey={`memory.details.${memory.id}`} className="memory-details-toggle" open={expanded} aria-controls={detailsId} onClick={() => setExpanded(value => !value)}>
        Подробности записи
      </DisclosureTrigger>
    </div>
    <div className="memory-record-details" id={detailsId} ref={detailsRef} hidden={!expanded} role="region" aria-label="Подробности записи">
      <dl className="memory-record-facts">
        {createdAt && <div><dt>Создана</dt><dd data-i18n-skip>{preciseDate(memory.created_at) || createdAt}</dd></div>}
        {memory.updated_at && preciseDate(memory.updated_at) !== preciseDate(memory.created_at) && <div><dt>Обновлена</dt><dd data-i18n-skip>{preciseDate(memory.updated_at) || formatMemoryDate(memory.updated_at)}</dd></div>}
        <div><dt>{archived ? "Использовалось до замены" : "Использовано"}</dt><dd>{memory.access_count ?? 0}</dd></div>
      </dl>
      {archived && <p className="memory-archive-reason">{memory.status === "superseded" ? "Прежний факт заменён более новым." : memory.status === "rejected" ? "Предложение отклонено пользователем." : "Запись перенесена в архив и не используется как текущий факт."}</p>}
      {expanded && sourceIds.length > 1 && onOpenSource && <div className="memory-record-sources">
        <h4>Источники</h4>
        <div>{sourceIds.map((id, index) => <MaterialButton materialKey={`memory.source.${memory.id}.${id}`} className="secondary" type="button" key={id} onClick={() => onOpenSource(id)}>
          <MessagesSquare size={14} aria-hidden="true" /><span data-i18n-skip>{currentInterfaceLocale() === "en" ? `Message ${index + 1}` : `Сообщение ${index + 1}`}</span><ArrowUpRight size={14} aria-hidden="true" />
        </MaterialButton>)}</div>
      </div>}
    </div>
  </div>;
}

/** Closed menus should not mount five material controls for every record. */
function MemoryActionMenu({ children }: { children: ReactNode }) {
  const [prepared, setPrepared] = useState(false);
  return <details className="memory-action-menu" onToggle={event => {
    if (!event.currentTarget.open) setPrepared(false);
  }}>
    <summary className="icon-button" role="button" aria-label="Дополнительные действия" title="Действия" onClick={() => setPrepared(true)}>
      <MoreHorizontal size={18} aria-hidden="true" />
    </summary>
    {prepared && children}
  </details>;
}

export function MemoryPage({ developerMode = false, focusRequest, onOpenSource }: { developerMode?: boolean; focusRequest?: SearchFocus; onOpenSource?: (id: string) => void }) {
  const [loading, setLoading] = useState(true);
  const [focusApplied, setFocusApplied] = useState("");
  const focused = useRef("");
  const requestRevision = useRef(0);
  const loadedSection = useRef<MemorySection | null>(null);
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const loadedQuery = useRef("");
  const [topics, setTopics] = useState<MemoryTopic[]>([]);
  const [commitments, setCommitments] = useState<MemoryCommitment[]>([]);
  const [conflicts, setConflicts] = useState<Array<{ id: string; reason: string; status: string }>>([]);
  const [diagnostics, setDiagnostics] = useState<MemoryDiagnostics>({ queue: {}, runs: [] });
  const [section, setSection] = useState<MemorySection>("all");
  const [query, setQuery] = useState("");
  const [sortOrder, setSortOrder] = useState<"date-desc" | "date-asc" | "alpha-asc" | "alpha-desc">("date-desc");
  const [audit, setAudit] = useState<Record<string, MemoryAuditItem[]>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [pendingDeleteMemory, setPendingDeleteMemory] = useState<MemoryItem | null>(null);
  const [pendingEditMemory, setPendingEditMemory] = useState<MemoryItem | null>(null);
  const [editedValue, setEditedValue] = useState("");
  useEffect(() => {
    if (!focusRequest) return;
    setSection(focusRequest.section || "all"); setQuery(focusRequest.query); setFocusApplied(focusRequest.requestId);
  }, [focusRequest]);
  useEffect(() => {
    if (loading || !focusRequest || focused.current === focusRequest.requestId) return;
    const target = document.getElementById(`memory-record-${focusRequest.id}`);
    if (target) { target.classList.add("search-focus-target"); target.tabIndex = -1; target.scrollIntoView?.({ block: "center", behavior: "instant" }); target.focus({ preventScroll: true }); focused.current = focusRequest.requestId; }
  }, [items, commitments, loading, focusApplied, focusRequest]);
  useEffect(() => { if (!developerMode && (section === "memes" || section === "opinions" || section === "diagnostics")) setSection("all"); }, [developerMode, section]);

  const containerRef = useAnimeScope<HTMLElement>((scope, root) => {
    animatePageEnter(root);
  }, []);

  const contentRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (contentRef.current) {
      animatePageEnter(contentRef.current);
    }
  }, [section, focusApplied]);

  useEffect(() => {
    if (!loading && listRef.current) {
      animateStaggerCards(listRef.current, ".memory-card", 35);
    }
  }, [loading, section, items, topics, commitments, diagnostics, conflicts]);

  const refresh = async (searchQuery = query) => {
    const revision = ++requestRevision.current;
    setLoadingMore(false);
    setNextOffset(null);
    if (loadedSection.current !== section) setLoading(true);
    try {
      if (section === "memes" || section === "opinions") return;
      if (section === "topics") {
        const response = await getMemoryTopics(searchQuery || undefined);
        if (revision !== requestRevision.current) return;
        loadedQuery.current = searchQuery;
        setTopics(response.items);
        setMessage(null);
        return;
      }
      if (section === "commitments") {
        const response = await getMemoryCommitments(undefined, searchQuery || undefined);
        if (revision !== requestRevision.current) return;
        loadedQuery.current = searchQuery;
        setCommitments(response.items);
        setMessage(null);
        return;
      }
      if (section === "diagnostics") {
        const [conflictData, diagnosticData] = await Promise.all([getMemoryConflicts(), getMemoryDiagnostics()]);
        if (revision !== requestRevision.current) return;
        setConflicts(conflictData.items);
        setDiagnostics(diagnosticData);
        setMessage(null);
        return;
      }
      const result = await getMemories(
        section === "all" ? "active" : section,
        searchQuery || undefined,
      );
      if (revision !== requestRevision.current) return;
      const nextItems = result.items.filter(item => section === "archive" ? item.status !== "active" : item.status === "active");
      loadedQuery.current = searchQuery;
      setNextOffset(result.next_offset ?? null);
      startTransition(() => setItems(current => JSON.stringify(current) === JSON.stringify(nextItems) ? current : nextItems));
      setMessage(null);
    } catch (error) {
      if (revision === requestRevision.current) setMessage(error instanceof Error ? error.message : "Память недоступна");
    } finally {
      if (revision === requestRevision.current) { loadedSection.current = section; startTransition(() => setLoading(false)); }
    }
  };

  const loadMore = async () => {
    if (nextOffset === null || loadingMore) return;
    const revision = requestRevision.current;
    setLoadingMore(true);
    try {
      const result = await getMemories(section === "all" ? "active" : section, loadedQuery.current || undefined, nextOffset);
      if (revision !== requestRevision.current) return;
      setItems(current => [...new Map([...current, ...result.items].map(item => [item.id, item])).values()]);
      setNextOffset(result.next_offset ?? null);
    } catch (error) {
      if (revision === requestRevision.current) setMessage(error instanceof Error ? error.message : "Память недоступна");
    } finally {
      if (revision === requestRevision.current) setLoadingMore(false);
    }
  };

  useEffect(() => {
    void refresh();
    return () => { requestRevision.current += 1; };
  }, [section, focusApplied]);

  const action = async (run: () => Promise<unknown>, successMsg?: string) => {
    try {
      await run();
      await refresh();
      if (successMsg) {
        notify.success("Память", successMsg);
      }
    } catch (error) {
      const err = error instanceof Error ? error.message : "Не удалось выполнить действие";
      setMessage(err);
      notify.error("Память", err);
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
    <section className="memory-panel" ref={containerRef}>
      <nav className="settings-navigation memory-navigation" aria-label="Разделы памяти">
        {[...MEMORY_SECTIONS.filter(item => developerMode || item.id !== "diagnostics"), ...(developerMode ? [{ id: "memes" as const, label: "Мемотека", icon: IconEntertainmentGamingEsports }, { id: "opinions" as const, label: "Взгляды Iris", icon: IconCitiesPoliticsVote }] : [])].map(({ id, label, icon: Icon }) => (
          <MaterialButton materialKey={["memory.button-1", id].join(":")}
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
          </MaterialButton>
        ))}
      </nav>

      <div className="memory-content" ref={contentRef}>
        {section !== "commitments" && <p className="memory-section-description">{({
          all: "Что Iris помнит из ваших разговоров.",
          active: "Факты о вас и ваши предпочтения. Важные записи можно закрепить.",
          topics: "Записи памяти, собранные по темам.",
          archive: "Прежние и убранные записи. Здесь видно, почему они больше не используются.",
          diagnostics: "Состояние индексов и извлечения памяти.", memes: "Мемы и отсылки, которые Iris может использовать в разговоре.", opinions: "Собственные позиции Iris и история их изменений.",
        } as Record<string,string>)[section]}</p>}
        {section === "memes" && developerMode ? <MemeLibraryPanel /> : section === "opinions" && developerMode ? <OpinionsPanel /> : <>
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
                <MaterialButton materialKey={"memory.button-2"}
                  appearance="quiet"
                  type="button"
                  className="search-clear-btn"
                  onClick={() => {
                    setQuery("");
                    void refresh("");
                  }}
                  aria-label="Очистить"
                >
                  <X size={12} aria-hidden="true" />
                </MaterialButton>
              )}
              <MaterialButton materialKey={"memory.button-3"}
                appearance="quiet"
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
              </MaterialButton>
              <MaterialButton materialKey={"memory.button-4"}
                appearance="quiet"
                className="icon-button search-submit"
                type="submit"
                aria-label="Найти в памяти"
                title="Найти в памяти"
              >
                <IconInterfaceSearch size={17} />
              </MaterialButton>
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

        {loading && <LoadingRing label="Загружаю память…" />}
        <div className="memory-list" ref={listRef} hidden={loading}>
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
                      <div className="memory-provenance"><small>{formatMemoryDate((topic as any).created_at, topic.id)}</small><Disclosure materialKey={`memory.topic.${topic.id}.evidence`} label="Связи и основания"><p>Связи: {topic.links.length} · доказательства: {topic.evidence.length}</p></Disclosure></div>
                    </div>
                  </article>
                ))
              ) : (
                <div className="empty-state">
                  <IconMoneyCashierTag size={28} aria-hidden="true" />
                  <strong>Тем пока нет</strong>
                  <span>Здесь появятся темы из ваших разговоров.</span>
                </div>
              )}
            </>
          )}

          {section === "commitments" && <RemindersPanel plans={sortedCommitments} query={loadedQuery.current} sortOrder={sortOrder} onChanged={() => void refresh()} />}

          {section === "diagnostics" && (
            <>
              <div className="memory-diagnostics-grid">
                {diagnostics.capabilities && (
                  <article className="memory-card">
                    <div className="memory-card-main">
                      <div className="memory-card-heading">
                        <div className="memory-card-label">
                          <IconComputerDatabase size={14} aria-hidden="true" />
                          <strong>Возможности</strong>
                        </div>
                        <span className={`memory-status ${diagnostics.capabilities.semantic_enabled ? "active" : "deleted"}`}>
                          {diagnostics.capabilities.retrieval}
                        </span>
                      </div>
                      <strong>Активный контур памяти</strong>
                      <p>
                        Запись: {diagnostics.capabilities.writer} · поиск: {diagnostics.capabilities.backend} ·
                        модель: {diagnostics.capabilities.embedding_provider}
                      </p>
                      <small>
                        Реестр слотов v{diagnostics.capabilities.slot_registry_version}
                        {diagnostics.capabilities.degraded_reason
                          ? ` · ${diagnostics.capabilities.degraded_reason}`
                          : " · без деградации"}
                      </small>
                    </div>
                  </article>
                )}
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
                    <span>Здесь будут результаты обработки памяти и причины ошибок.</span>
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
                    <article className="memory-card memory-fact-card" id={`memory-record-${memory.id}`} key={memory.id}>
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

                        <p className="memory-fact-value" data-i18n-skip>
                          {memory.value_text}
                        </p>

                        {section === "archive" && memory.replacement && (
                          <p className="memory-replacement">
                            <span>Заменено на: </span>
                            <span data-i18n-skip>{memory.replacement.value_text}</span>
                          </p>
                        )}

                        <MemoryRecordFooter memory={memory} archived={section === "archive"} onOpenSource={onOpenSource} />
                      </div>

                      <div className="memory-actions">
                        <MemoryActionMenu>
                          <div>
                            <MaterialButton materialKey={["memory.button-6", memory.id].join(":")}
                              type="button"
                              onClick={async (event) => {
                                event.currentTarget.closest("details")?.removeAttribute("open");
                                const nextAudit = await getMemoryAudit(memory.id);
                                setAudit((current) => ({ ...current, [memory.id]: nextAudit.items }));
                              }}
                            >
                              <IconInterfaceAlertAlarmBell2 size={16} aria-hidden="true" />
                              История записи
                            </MaterialButton>
                            <MaterialButton materialKey={["memory.button-7", memory.id].join(":")}
                              type="button"
                              onClick={(event) => {
                                event.currentTarget.closest("details")?.removeAttribute("open");
                                setPendingEditMemory(memory);
                                setEditedValue(memory.value_text);
                              }}
                            >
                              <IconInterfaceTextFormattingTextStyle size={16} aria-hidden="true" />
                              Изменить
                            </MaterialButton>
                            <MaterialButton materialKey={["memory.button-8", memory.id].join(":")}
                              type="button"
                              onClick={(event) => {
                                event.currentTarget.closest("details")?.removeAttribute("open");
                                void action(
                                  () => updateMemory(memory.id, { user_locked: !memory.user_locked }),
                                  memory.user_locked ? "Запись откреплена." : "Запись закреплена.",
                                );
                              }}
                            >
                              <IconInterfaceBookmark size={16} aria-hidden="true" />
                              {memory.user_locked ? "Открепить" : "Закрепить"}
                            </MaterialButton>
                            {memory.status === "active" ? (
                              <MaterialButton materialKey={["memory.button-9", memory.id].join(":")}
                                type="button"
                                onClick={(event) => {
                                  event.currentTarget.closest("details")?.removeAttribute("open");
                                  void action(() => deleteMemory(memory.id), "Запись перемещена в архив.");
                                }}
                              >
                                <IconInterfaceContentArchive size={16} aria-hidden="true" />
                                Архивировать
                              </MaterialButton>
                            ) : (
                              <MaterialButton materialKey={["memory.button-10", memory.id].join(":")}
                                type="button"
                                onClick={(event) => {
                                  event.currentTarget.closest("details")?.removeAttribute("open");
                                  void action(() => restoreMemory(memory.id), "Запись восстановлена.");
                                }}
                              >
                                <IconInterfaceSpirals size={16} aria-hidden="true" />
                                Восстановить
                              </MaterialButton>
                            )}
                            <MaterialButton materialKey={["memory.button-11", memory.id].join(":")}
                              className="is-danger"
                              type="button"
                              onClick={(e) => {
                                e.currentTarget.closest("details")?.removeAttribute("open");
                                setPendingDeleteMemory(memory);
                              }}
                            >
                              <IconInterfaceDeleteBin3 size={16} aria-hidden="true" />
                              Забыть навсегда
                            </MaterialButton>
                          </div>
                        </MemoryActionMenu>
                      </div>

                      {audit[memory.id] && (
                        <Disclosure materialKey={`memory.audit.${memory.id}`} label="История записи" className="memory-audit" defaultOpen>

                          <p>{audit[memory.id].map((item) => `${item.action} (${item.actor})`).join(" → ")}</p>
                        </Disclosure>
                      )}
                    </article>
                  );
                })
              ) : (
                <div className="empty-state">
                  <IconComputerRobotCyborg1 size={28} aria-hidden="true" />
                  <strong>Записей пока нет</strong>
                  <span>Здесь появятся факты, которые Iris запомнит в разговоре.</span>
                </div>
              )}
              {nextOffset !== null && <MaterialButton materialKey="memory.load-more" type="button" disabled={loadingMore} onClick={() => void loadMore()}>
                {loadingMore ? "Загрузка…" : "Загрузить ещё"}
              </MaterialButton>}
            </>
          )}
        </div>
        </>}
      </div>

      <AppDialog
        open={Boolean(pendingDeleteMemory)}
        title="Забыть эту запись навсегда?"
        description={`Запись «${pendingDeleteMemory ? memoryLabel(pendingDeleteMemory) : ""}» и её журнал памяти будут удалены без восстановления. Исходный текст останется в истории диалога, пока вы отдельно не удалите историю.`}
        onClose={() => setPendingDeleteMemory(null)}
        variant="danger"
      >
        <div className="dialog-actions">
          <MaterialButton materialKey={"memory.button-12"} className="secondary" type="button" onClick={() => setPendingDeleteMemory(null)}>
            Отмена
          </MaterialButton>
          <MaterialButton materialKey={"memory.button-13"}
            className="danger-button"
            type="button"
            onClick={() => {
              if (!pendingDeleteMemory) return;
              const memId = pendingDeleteMemory.id;
              setPendingDeleteMemory(null);
              void action(() => purgeMemory(memId), "Запись забыта без возможности восстановления.");
            }}
          >
            Забыть навсегда
          </MaterialButton>
        </div>
      </AppDialog>

      <AppDialog
        open={Boolean(pendingEditMemory)}
        title="Исправить запись памяти"
        description="Iris будет использовать исправленный текст. Запись будет закреплена."
        onClose={() => setPendingEditMemory(null)}
        variant="info"
      >
        <label className="form-field">
          <span>Значение</span>
          <textarea
            value={editedValue}
            onChange={(event) => setEditedValue(event.target.value)}
            rows={4}
            maxLength={2000}
            data-i18n-skip
          />
        </label>
        <div className="dialog-actions">
          <MaterialButton materialKey={"memory.button-14"} className="secondary" type="button" onClick={() => setPendingEditMemory(null)}>
            Отмена
          </MaterialButton>
          <MaterialButton materialKey={"memory.button-15"}
            type="button"
            disabled={!editedValue.trim()}
            onClick={() => {
              if (!pendingEditMemory || !editedValue.trim()) return;
              const memoryId = pendingEditMemory.id;
              const valueText = editedValue.trim();
              setPendingEditMemory(null);
              void action(
                () => updateMemory(memoryId, { value_text: valueText, user_locked: true }),
                "Запись исправлена и закреплена.",
              );
            }}
          >
            Сохранить
          </MaterialButton>
        </div>
      </AppDialog>
    </section>
  );
}

