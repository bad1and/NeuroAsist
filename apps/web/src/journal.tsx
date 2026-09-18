import {
  IconInterfaceTimeStopWatchCircle,
  IconInterfaceSpirals,
  IconInterfaceSearch,
  IconInterfaceDeleteBin3,
  IconMailChatBubbleTextSquare,
  IconInterfaceCursorArrow2,
  IconInterfaceCalendarMark,
  IconComputerRobotCyborg1,
} from "./CustomIcons";
import { FormEvent, Fragment, useEffect, useMemo, useRef, useState } from "react";

import { deleteTimelineRange, getTimelineJournal, getTimelineMessages, searchTimeline } from "./api";
import type { TimelineJournalItem, TimelineMessage } from "./types";
import { AppDialog } from "./components/AppDialog";
import {
  ChevronLeft,
  X,
  Zap,
  Eye,
  Sliders,
  Sparkles,
  Brain,
  Terminal,
  Copy,
  Check,
} from "lucide-react";
import { TokenBadge } from "./components/TokenBadge";
import { notify } from "./notifications";
import { interfaceIntlLocale } from "./i18n";
import { animateButtonPress, animatePageEnter, animateStaggerCards, useAnimeScope } from "./animations";

function formatDate(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(interfaceIntlLocale(), { day: "numeric", month: "long", year: "numeric" }).format(date);
}

function formatTime(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleTimeString(interfaceIntlLocale(), { hour: "2-digit", minute: "2-digit" });
}

function formatShortDate(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(interfaceIntlLocale(), { day: "numeric", month: "short" }).format(date);
}

function shouldShowDateSeparator(prevDate?: string | null, currDate?: string | null): boolean {
  if (!currDate) return false;
  if (!prevDate) return true;
  const prev = new Date(prevDate);
  const curr = new Date(currDate);
  if (Number.isNaN(prev.getTime()) || Number.isNaN(curr.getTime())) return false;
  return prev.toDateString() !== curr.toDateString();
}

function formatDateSeparatorLabel(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const now = new Date();
  const todayStr = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const dateDayTime = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const diffDays = Math.round((todayStr - dateDayTime) / 86400000);
  if (diffDays === 0) return "Сегодня";
  if (diffDays === 1) return "Вчера";
  return new Intl.DateTimeFormat(interfaceIntlLocale(), {
    day: "numeric",
    month: "long",
    year: date.getFullYear() !== now.getFullYear() ? "numeric" : undefined,
  }).format(date);
}

type PeriodGroup = {
  key: string;
  title: string;
  items: TimelineJournalItem[];
};

function groupTimelineItems(items: TimelineJournalItem[]): PeriodGroup[] {
  const now = new Date();
  const todayStr = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const yesterdayStr = todayStr - 86400000;
  const weekStr = todayStr - 6 * 86400000;

  const todayItems: TimelineJournalItem[] = [];
  const yesterdayItems: TimelineJournalItem[] = [];
  const weekItems: TimelineJournalItem[] = [];
  const olderItems: TimelineJournalItem[] = [];

  for (const item of items) {
    const itemDate = new Date(item.day || item.started_at || "");
    const itemDayTime = new Date(itemDate.getFullYear(), itemDate.getMonth(), itemDate.getDate()).getTime();

    if (itemDayTime >= todayStr) {
      todayItems.push(item);
    } else if (itemDayTime >= yesterdayStr) {
      yesterdayItems.push(item);
    } else if (itemDayTime >= weekStr) {
      weekItems.push(item);
    } else {
      olderItems.push(item);
    }
  }

  const groups: PeriodGroup[] = [];
  if (todayItems.length) groups.push({ key: "today", title: "Сегодня", items: todayItems });
  if (yesterdayItems.length) groups.push({ key: "yesterday", title: "Вчера", items: yesterdayItems });
  if (weekItems.length) groups.push({ key: "week", title: "На этой неделе", items: weekItems });
  if (olderItems.length) groups.push({ key: "older", title: "Ранее", items: olderItems });
  return groups;
}

const EMOTION_META: Record<string, { label: string; icon: string }> = {
  neutral: { label: "Спокойствие", icon: "😐" },
  happy: { label: "Радость", icon: "😊" },
  sad: { label: "Грусть", icon: "😔" },
  curious: { label: "Любопытство", icon: "🤔" },
  thinking: { label: "Размышление", icon: "🧐" },
  surprised: { label: "Удивление", icon: "😲" },
  skeptical: { label: "Скепсис", icon: "🤨" },
  teasing: { label: "Игривость", icon: "😜" },
  pouting: { label: "Обида", icon: "😤" },
  frustrated: { label: "Досада", icon: "😣" },
  shy: { label: "Смущение", icon: "😳" },
  excited: { label: "Восторг", icon: "🤩" },
};

const GESTURE_LABELS: Record<string, string> = {
  talk: "Речь",
  auto: "Авто",
  greeting_right: "Приветствие рукой",
  farewell_right: "Прощание рукой",
  nod: "Кивок согласия",
  disagreement: "Покачивание головой",
  shrug: "Пожатие плечами",
  surprise: "Всплеск руками",
  frustration: "Разведение рук",
  head_scratch: "Почесывание затылка",
  clapping: "Аплодисменты",
  laughing: "Смех",
  thumbs_up: "Палец вверх",
  facepalm: "Фейспалм",
  pointing: "Указание",
  bow: "Поклон",
  explanation: "Объяснение",
  question: "Вопросительный жест",
  agreement: "Согласие",
};

const INTENT_LABELS: Record<string, string> = {
  casual_chat: "Разговор",
  task_request: "Выполнение задачи",
  question: "Вопрос",
  unknown: "Неопределенно",
};

function calcMessageCost(tokens?: { prompt_tokens?: number; prompt_cache_hit_tokens?: number; prompt_cache_miss_tokens?: number; completion_tokens?: number }): number {
  if (!tokens) return 0;
  const hit = tokens.prompt_cache_hit_tokens || 0;
  const miss = tokens.prompt_cache_miss_tokens || (tokens.prompt_tokens ? Math.max(0, tokens.prompt_tokens - hit) : 0);
  const out = tokens.completion_tokens || 0;
  return (hit * 0.00000007) + (miss * 0.00000027) + (out * 0.0000011);
}

function formatCost(usd: number): string {
  if (usd <= 0) return "$0.00";
  if (usd < 0.0001) return "<$0.0001";
  return `$${usd.toFixed(4)}`;
}

function JournalMessageDetails({
  message,
  onInspectJson,
}: {
  message: TimelineMessage;
  onInspectJson: (data: Record<string, unknown>, title: string) => void;
}) {
  const isAssistant = message.role === "assistant";
  const tokens = message.metadata?.tokens;
  const companion = message.metadata?.companion;
  const memoryUpdates = message.metadata?.memory_updates;

  if (!tokens && !companion && (!memoryUpdates || memoryUpdates.length === 0)) {
    return null;
  }

  const emotionInfo = companion?.emotion
    ? EMOTION_META[companion.emotion] || { label: companion.emotion, icon: "✨" }
    : null;
  const gestureLabel = companion?.gesture
    ? GESTURE_LABELS[companion.gesture] || companion.gesture
    : null;
  const intentLabel = companion?.intent
    ? INTENT_LABELS[companion.intent] || companion.intent
    : null;

  return (
    <div className="journal-turn-details" data-testid="journal-turn-details">
      {/* 1. LLM Token & Cost Metrics */}
      {tokens && (
        <div className="details-section details-tokens-section">
          <div className="details-section-title">
            <Zap size={13} className="text-accent" />
            <span>Параметры вызова LLM</span>
            <span className="details-model-tag">{tokens.model || "deepseek"}</span>
          </div>

          <div className="details-metrics-grid">
            <div className="metric-cell">
              <span className="cell-label">Prompt (ввод)</span>
              <span className="cell-val text-prompt">
                {tokens.prompt_tokens?.toLocaleString() ?? 0}
                {Boolean(tokens.prompt_cache_hit_tokens) && (
                  <small className="cache-hit-ratio">
                    {" "}(+{tokens.prompt_cache_hit_tokens?.toLocaleString()} кэш)
                  </small>
                )}
              </span>
            </div>

            <div className="metric-cell">
              <span className="cell-label">Output (генерация)</span>
              <span className="cell-val text-completion">
                {tokens.completion_tokens?.toLocaleString() ?? 0}
              </span>
            </div>

            {Boolean(tokens.reasoning_tokens) && (
              <div className="metric-cell">
                <span className="cell-label">Reasoning</span>
                <span className="cell-val text-reasoning">
                  {tokens.reasoning_tokens?.toLocaleString()}
                </span>
              </div>
            )}

            <div className="metric-cell">
              <span className="cell-label">Всего</span>
              <span className="cell-val text-total">
                {tokens.total_tokens?.toLocaleString() ?? 0}
              </span>
            </div>

            {tokens.latency_ms !== undefined && (
              <div className="metric-cell">
                <span className="cell-label">Задержка</span>
                <span className="cell-val">{tokens.latency_ms} мс</span>
              </div>
            )}

            <div className="metric-cell">
              <span className="cell-label">Расход</span>
              <span className="cell-val text-cost">
                {formatCost(calcMessageCost(tokens))}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* 2. Companion State & Acting Cues */}
      {isAssistant && companion && (
        <div className="details-section details-companion-section">
          <div className="details-section-title">
            <Sparkles size={13} className="text-purple" />
            <span>Состояние и экспрессия Iris</span>
          </div>

          <div className="companion-cues-row">
            {emotionInfo && (
              <div className="cue-badge emotion-cue" title={`Эмоция: ${companion.emotion}`}>
                <span className="cue-icon">{emotionInfo.icon}</span>
                <span className="cue-text">
                  <strong>{emotionInfo.label}</strong>
                  {companion.intensity !== undefined && (
                    <small> ({Math.round(companion.intensity * 100)}%)</small>
                  )}
                </span>
              </div>
            )}

            {gestureLabel && (
              <div className="cue-badge gesture-cue" title={`Жест: ${companion.gesture}`}>
                <span className="cue-icon">👋</span>
                <span className="cue-text">Жест: <strong>{gestureLabel}</strong></span>
              </div>
            )}

            {intentLabel && (
              <div className="cue-badge intent-cue" title={`Намерение: ${companion.intent}`}>
                <span className="cue-icon">🎯</span>
                <span className="cue-text">Режим: <strong>{intentLabel}</strong></span>
              </div>
            )}
          </div>

          {companion.cognitive_appraisal && (
            <div className="companion-note-box appraisal">
              <span className="note-label">Оценка ситуации:</span>
              <p>{companion.cognitive_appraisal}</p>
            </div>
          )}

          {companion.diary_note && (
            <div className="companion-note-box diary">
              <span className="note-label">Внутренний дневник:</span>
              <p>{companion.diary_note}</p>
            </div>
          )}
        </div>
      )}

      {/* 3. Memory Updates */}
      <div className="details-section details-memory-section">
        <div className="details-section-title">
          <Brain size={13} className="text-cyan" />
          <span>Долгосрочная память хода</span>
        </div>

        {memoryUpdates && memoryUpdates.length > 0 ? (
          <div className="memory-updates-list">
            {memoryUpdates.map((mem, i) => {
              if (typeof mem === "string") {
                return (
                  <div key={i} className="memory-update-card">
                    <span className="memory-card-icon">📌</span>
                    <span className="memory-card-text">{mem}</span>
                  </div>
                );
              }
              return (
                <div key={i} className="memory-update-card">
                  <span className="memory-card-icon">📌</span>
                  <div className="memory-card-content">
                    <strong>{mem.subject || mem.kind || "Факт"}</strong>:{" "}
                    {mem.predicate ? `${mem.predicate} → ` : ""}{mem.value_text || JSON.stringify(mem)}
                    {mem.confidence !== undefined && (
                      <small className="memory-conf"> ({Math.round(mem.confidence * 100)}% вер.)</small>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="memory-empty-note">
            <span>В этом ходе новые факты в память не заносились</span>
          </div>
        )}
      </div>

      {/* 4. Raw JSON Inspection Button */}
      <div className="details-footer-actions">
        <button
          type="button"
          className="details-json-btn"
          onClick={() =>
            onInspectJson(
              (message.metadata as Record<string, unknown>) || {},
              `Метаданные сообщения #${message.id.slice(0, 8)}`,
            )
          }
          title="Просмотреть сырой JSON объект хода"
        >
          <Terminal size={12} />
          <span>Сырой JSON хода</span>
        </button>
      </div>
    </div>
  );
}

export function JournalPage({ onOpenChat }: { onOpenChat?: () => void } = {}) {
  const [items, setItems] = useState<TimelineJournalItem[]>([]);
  const [selectedEpisode, setSelectedEpisode] = useState<TimelineJournalItem | null>(null);
  const [messages, setMessages] = useState<TimelineMessage[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [loadingMoreMessages, setLoadingMoreMessages] = useState(false);
  const [hasMoreMessages, setHasMoreMessages] = useState(false);
  const [messageOffset, setMessageOffset] = useState<number | null>(null);
  const [messagesError, setMessagesError] = useState<string | null>(null);
  const [results, setResults] = useState<TimelineMessage[] | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<TimelineJournalItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  const [detailMode, setDetailMode] = useState<"simple" | "detailed">(() => {
    try {
      return (
        (window.localStorage.getItem("journal_detail_mode") as "simple" | "detailed") ||
        "simple"
      );
    } catch {
      return "simple";
    }
  });

  const handleToggleDetailMode = (mode: "simple" | "detailed") => {
    setDetailMode(mode);
    try {
      window.localStorage.setItem("journal_detail_mode", mode);
    } catch {
      // Ignored
    }
  };

  const [inspectModalData, setInspectModalData] = useState<{
    title: string;
    json: Record<string, unknown>;
  } | null>(null);
  const [inspectCopied, setInspectCopied] = useState(false);

  const activeRequestIdRef = useRef(0);

  const containerRef = useAnimeScope<HTMLElement>((scope, root) => {
    animatePageEnter(root);
  }, []);

  const listRef = useRef<HTMLDivElement | null>(null);
  const messagesContainerRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (listRef.current) {
      const selector = results ? ".journal-message" : ".history-item-minimal";
      animateStaggerCards(listRef.current, selector, 30);
    }
  }, [items, results]);

  useEffect(() => {
    if (selectedEpisode && contentRef.current) {
      animatePageEnter(contentRef.current);
    }
  }, [selectedEpisode]);

  const refresh = async () => {
    try {
      const response = await getTimelineJournal();
      setItems(response.items);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "История недоступна");
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const onSelectEpisode = async (episode: TimelineJournalItem) => {
    const requestId = ++activeRequestIdRef.current;
    setSelectedEpisode(episode);
    setLoadingMessages(true);
    setMessagesError(null);
    setHasMoreMessages(false);
    setMessageOffset(null);
    try {
      const response = await getTimelineMessages(200, undefined, episode.id);
      if (activeRequestIdRef.current === requestId) {
        setMessages(response.items);
        setHasMoreMessages(response.next_offset !== null && response.next_offset !== undefined);
        setMessageOffset(response.next_offset ?? null);
      }
    } catch (cause) {
      if (activeRequestIdRef.current === requestId) {
        const msg = cause instanceof Error ? cause.message : "Не удалось загрузить сообщения";
        setMessagesError(msg);
        notify.error("Журнал", msg);
      }
    } finally {
      if (activeRequestIdRef.current === requestId) {
        setLoadingMessages(false);
      }
    }
  };

  const onLoadMoreMessages = async () => {
    if (!selectedEpisode?.id || messageOffset === null || loadingMoreMessages) return;
    setLoadingMoreMessages(true);
    try {
      const response = await getTimelineMessages(100, undefined, selectedEpisode.id, messageOffset);
      setMessages((prev) => [...response.items, ...prev]);
      setHasMoreMessages(response.next_offset !== null && response.next_offset !== undefined);
      setMessageOffset(response.next_offset ?? null);
    } catch (cause) {
      const msg = cause instanceof Error ? cause.message : "Не удалось загрузить ранние сообщения";
      notify.error("Журнал", msg);
    } finally {
      setLoadingMoreMessages(false);
    }
  };

  const onBack = () => {
    activeRequestIdRef.current++;
    setSelectedEpisode(null);
    setMessages([]);
    setMessagesError(null);
    setLoadingMessages(false);
    setHasMoreMessages(false);
    setMessageOffset(null);
  };

  const onSearch = async (event: FormEvent) => {
    event.preventDefault();
    if (!query.trim()) {
      setResults(null);
      return;
    }
    try {
      const response = await searchTimeline(query);
      setResults(response.items);
      setError(null);
    } catch (cause) {
      const msg = cause instanceof Error ? cause.message : "Не удалось выполнить поиск";
      setError(msg);
      notify.error("Журнал", msg);
    }
  };

  const handleResetSearch = () => {
    setQuery("");
    setResults(null);
  };

  const renderHistoryCard = (item: TimelineJournalItem) => {
    const isSelected =
      (selectedEpisode?.id && selectedEpisode.id === item.id) ||
      (!item.id && selectedEpisode?.day === item.day);
    const isCurrent = !item.ended_at;

    return (
      <article
        className={`history-item-minimal ${isSelected ? "is-active" : ""}`}
        key={item.id ?? item.day}
        onClick={() => onSelectEpisode(item)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            void onSelectEpisode(item);
          }
        }}
        aria-label={`Диалог от ${formatDate(item.day)}`}
      >
        <div className="history-item-minimal-icon" aria-hidden="true">
          <IconMailChatBubbleTextSquare size={19} />
        </div>
        <div className="history-item-minimal-content">
          <div className="history-item-minimal-header">
            <strong>{item.title || formatDate(item.day)}</strong>
            {isCurrent && (
              <span title="Текущий диалог" aria-label="Текущий диалог">
                <span className="journal-pulse-dot" />
              </span>
            )}
          </div>
          <div className="history-item-minimal-meta">
            {item.message_count} {item.message_count === 1 ? "сообщение" : "сообщений"}
            {item.last_activity_at && !isCurrent ? ` · ${formatTime(item.last_activity_at)}` : ""}
            {isCurrent ? " · сейчас" : ""}
            {Boolean(item.token_estimate && item.token_estimate > 0) && (
              <span> · {item.token_estimate! >= 1000 ? `${(item.token_estimate! / 1000).toFixed(1)}k` : item.token_estimate} токенов</span>
            )}
          </div>
        </div>
      </article>
    );
  };

  return (
    <section className="history-panel journal-panel" ref={containerRef}>
      <div className={`journal-layout ${selectedEpisode ? "has-selected" : ""}`}>
        <aside className="journal-sidebar journal-sidebar-new" aria-label="Список диалогов">
          <div className="journal-sidebar-header">
            <form className="search-form compact journal-search-form" onSubmit={onSearch}>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Поиск по истории"
                aria-label="Поиск по истории"
              />
              {query && !results && (
                <button
                  className="search-clear-btn"
                  type="button"
                  onClick={() => setQuery("")}
                  aria-label="Очистить поле поиска"
                  title="Очистить"
                >
                  <X size={12} aria-hidden="true" />
                </button>
              )}
              {results && (
                <button
                  className="secondary reset-search-button"
                  type="button"
                  onClick={handleResetSearch}
                >
                  Сбросить
                </button>
              )}

              <button
                className="icon-button search-submit"
                type="submit"
                aria-label="Найти в истории"
                title="Найти в истории"
              >
                <IconInterfaceSearch size={16} />
              </button>
            </form>
          </div>

          {error && <p className="error-text" role="alert">{error}</p>}

          {results ? (
            <div className="history-list search-results" ref={listRef}>
              <div className="journal-search-summary">
                <span>Найдено сообщений: {results.length}</span>
              </div>
              {results.length ? (
                results.map((message) => {
                  const isUser = message.role === "user";
                  const isAssistant = message.role === "assistant";
                  const roleLabel = isUser ? "Вы" : isAssistant ? "Iris" : "Событие";
                  const roleClass = isUser ? "user" : isAssistant ? "assistant" : "system";
                  return (
                    <article
                      className={`journal-message ${roleClass}`}
                      key={message.id}
                    >
                      <div className="message-role">
                        {isAssistant && (
                          <span className="message-role-avatar assistant" aria-hidden="true">
                            <IconComputerRobotCyborg1 size={11} />
                          </span>
                        )}
                        <span>{roleLabel}</span>
                      </div>
                      <p data-i18n-skip>{message.content || message.corrected_content || message.original_content || ""}</p>
                      <div className="journal-message-footer">
                        {message.created_at && (
                          <span className="message-time">{formatTime(message.created_at)}</span>
                        )}
                        {detailMode === "simple" && message.metadata?.companion?.emotion && (
                          <span
                            className="journal-emotion-micro-pill"
                            title={`Эмоция: ${EMOTION_META[message.metadata.companion.emotion]?.label || message.metadata.companion.emotion}${message.metadata.companion.intensity !== undefined ? ` (${Math.round(message.metadata.companion.intensity * 100)}%)` : ""}`}
                          >
                            {EMOTION_META[message.metadata.companion.emotion]?.icon || "✨"}{" "}
                            {EMOTION_META[message.metadata.companion.emotion]?.label || message.metadata.companion.emotion}
                          </span>
                        )}
                        {detailMode === "simple" && Boolean(message.metadata?.memory_updates?.length) && (
                          <span
                            className="journal-memory-micro-pill"
                            title={`Новых записей памяти: ${message.metadata?.memory_updates?.length}`}
                          >
                            🧠 {message.metadata?.memory_updates?.length}
                          </span>
                        )}
                        {message.metadata?.tokens && (
                          <TokenBadge tokens={message.metadata.tokens} role={message.role} />
                        )}
                      </div>
                      {detailMode === "detailed" && (
                        <JournalMessageDetails
                          message={message}
                          onInspectJson={(json, title) => setInspectModalData({ json, title })}
                        />
                      )}
                    </article>
                  );
                })
              ) : (
                <EmptyHistory text="Ничего не найдено" />
              )}
            </div>
          ) : (
            <div className="history-list" ref={listRef}>
              {items.length ? (
                items.map(renderHistoryCard)
              ) : (
                <EmptyHistory text="История пока пуста" />
              )}
            </div>
          )}
        </aside>

        <main className="journal-content settings-content memory-content" ref={contentRef} aria-label="Сообщения выбранного диалога">
          {selectedEpisode ? (
            <>
              <header className="journal-content-header">
                <div className="journal-header-left">
                  <button
                    className="journal-back-button secondary"
                    type="button"
                    onClick={onBack}
                    aria-label="Назад к списку"
                  >
                    <ChevronLeft size={16} aria-hidden="true" />
                    <span>Назад к списку</span>
                  </button>
                  <div className="journal-header-title-group">
                    <h2>{selectedEpisode.title || formatDate(selectedEpisode.day)}</h2>
                    <div className="journal-header-meta">
                      <span>
                        {selectedEpisode.message_count}{" "}
                        {selectedEpisode.message_count === 1 ? "сообщение" : "сообщений"}
                      </span>
                      {selectedEpisode.last_activity_at ? (
                        <span>· Активность в {formatTime(selectedEpisode.last_activity_at)}</span>
                      ) : selectedEpisode.started_at ? (
                        <span>· {formatShortDate(selectedEpisode.started_at)}</span>
                      ) : null}
                      {Boolean(selectedEpisode.token_estimate && selectedEpisode.token_estimate > 0) && (
                        <span className="journal-header-tokens">
                          · <Zap size={11} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 2 }} />
                          {selectedEpisode.token_estimate?.toLocaleString()} токенов
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="journal-header-actions">
                  <div className="journal-view-toggle" role="group" aria-label="Режим детализации">
                    <button
                      type="button"
                      className={`journal-view-toggle-btn ${detailMode === "simple" ? "active" : ""}`}
                      onClick={() => handleToggleDetailMode("simple")}
                      title="Простой режим (только сообщения и компактные бейджи)"
                      aria-pressed={detailMode === "simple"}
                    >
                      <Eye size={13} />
                      <span>Простой</span>
                    </button>
                    <button
                      type="button"
                      className={`journal-view-toggle-btn ${detailMode === "detailed" ? "active" : ""}`}
                      onClick={() => handleToggleDetailMode("detailed")}
                      title="Подробный режим (параметры LLM, эмоции, жесты, память и сырой JSON)"
                      aria-pressed={detailMode === "detailed"}
                    >
                      <Sliders size={13} />
                      <span>Подробный</span>
                    </button>
                  </div>

                  <button
                    className="secondary journal-delete-action"
                    type="button"
                    title="Удалить историю до этой даты"
                    aria-label={`Удалить историю до ${formatDate(selectedEpisode.day)}`}
                    onClick={(e) => {
                      animateButtonPress(e.currentTarget);
                      setPendingDelete(selectedEpisode);
                    }}
                  >
                    <IconInterfaceDeleteBin3 size={15} />
                    <span>Удалить</span>
                  </button>
                </div>
              </header>

              <div className="journal-messages-container" ref={messagesContainerRef}>
                {loadingMessages ? (
                  <div className="journal-loading">
                    <div className="assistant-thinking">
                      <span />
                      <span />
                      <span />
                    </div>
                    <p>Загрузка сообщений…</p>
                  </div>
                ) : messagesError ? (
                  <p className="error-text" role="alert">{messagesError}</p>
                ) : messages.length ? (
                  <div className="journal-message-list">
                    {hasMoreMessages && (
                      <button
                        className="journal-load-more-btn"
                        type="button"
                        disabled={loadingMoreMessages}
                        onClick={() => void onLoadMoreMessages()}
                      >
                        {loadingMoreMessages ? "Загрузка…" : "Загрузить более ранние сообщения"}
                      </button>
                    )}
                    {messages.map((message, idx) => {
                      const isUser = message.role === "user";
                      const isAssistant = message.role === "assistant";
                      const roleLabel = isUser ? "Вы" : isAssistant ? "Iris" : "Событие";
                      const roleClass = isUser ? "user" : isAssistant ? "assistant" : "system";
                      const prevDate = idx > 0 ? messages[idx - 1].created_at : null;
                      const showDateSep = shouldShowDateSeparator(prevDate, message.created_at);

                      return (
                        <Fragment key={message.id}>
                          {showDateSep && (
                            <div className="journal-date-divider" role="separator">
                              <span>{formatDateSeparatorLabel(message.created_at)}</span>
                            </div>
                          )}
                          <article
                            className={`journal-message ${roleClass}`}
                          >
                            <div className="message-role">
                              {isAssistant && (
                                <span className="message-role-avatar assistant" aria-hidden="true">
                                  <IconComputerRobotCyborg1 size={11} />
                                </span>
                              )}
                              <span>{roleLabel}</span>
                            </div>
                            <p data-i18n-skip>{message.content || message.corrected_content || message.original_content || ""}</p>
                            <div className="journal-message-footer">
                              {message.created_at && (
                                <span className="message-time">{formatTime(message.created_at)}</span>
                              )}
                              {detailMode === "simple" && message.metadata?.companion?.emotion && (
                                <span
                                  className="journal-emotion-micro-pill"
                                  title={`Эмоция: ${EMOTION_META[message.metadata.companion.emotion]?.label || message.metadata.companion.emotion}${message.metadata.companion.intensity !== undefined ? ` (${Math.round(message.metadata.companion.intensity * 100)}%)` : ""}`}
                                >
                                  {EMOTION_META[message.metadata.companion.emotion]?.icon || "✨"}{" "}
                                  {EMOTION_META[message.metadata.companion.emotion]?.label || message.metadata.companion.emotion}
                                </span>
                              )}
                              {detailMode === "simple" && Boolean(message.metadata?.memory_updates?.length) && (
                                <span
                                  className="journal-memory-micro-pill"
                                  title={`Новых записей памяти: ${message.metadata?.memory_updates?.length}`}
                                >
                                  🧠 {message.metadata?.memory_updates?.length}
                                </span>
                              )}
                              {message.metadata?.tokens && (
                                <TokenBadge tokens={message.metadata.tokens} role={message.role} />
                              )}
                            </div>
                            {detailMode === "detailed" && (
                              <JournalMessageDetails
                                message={message}
                                onInspectJson={(json, title) => setInspectModalData({ json, title })}
                              />
                            )}
                          </article>
                        </Fragment>
                      );
                    })}
                  </div>
                ) : (
                  <div className="empty-state journal-empty-messages">
                    <IconInterfaceTimeStopWatchCircle size={32} aria-hidden="true" />
                    <strong>В этом диалоге нет сообщений</strong>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="journal-placeholder empty-state">
              <div className="journal-placeholder-icon-wrap" aria-hidden="true">
                <div className="journal-placeholder-icon">
                  <IconInterfaceTimeStopWatchCircle size={36} />
                </div>
              </div>
              <strong>Выберите диалог для просмотра</strong>
              <span>Сообщения выбранного чата появятся здесь. Вы можете просматривать прошлые сессии и искать нужную информацию.</span>
              {items.length > 0 && (
                <div className="journal-placeholder-stats">
                  <span>Всего сессий в истории: {items.length}</span>
                </div>
              )}
            </div>
          )}
        </main>
      </div>

      <AppDialog
        open={Boolean(pendingDelete)}
        title="Удалить часть истории?"
        description={
          pendingDelete
            ? `Все сообщения по ${formatDate(pendingDelete.day)} включительно будут удалены без возможности восстановления.`
            : undefined
        }
        onClose={() => !deleting && setPendingDelete(null)}
        variant="danger"
      >
        <div className="dialog-actions">
          <button
            className="secondary"
            type="button"
            onClick={() => setPendingDelete(null)}
            disabled={deleting}
          >
            Отмена
          </button>
          <button
            className="danger-button"
            type="button"
            disabled={deleting}
            onClick={async () => {
              if (!pendingDelete) return;
              setDeleting(true);
              try {
                await deleteTimelineRange(`${pendingDelete.day}T23:59:59.999Z`);
                if (
                  selectedEpisode &&
                  (selectedEpisode.id === pendingDelete.id ||
                    selectedEpisode.day === pendingDelete.day ||
                    selectedEpisode.day <= pendingDelete.day)
                ) {
                  activeRequestIdRef.current++;
                  setSelectedEpisode(null);
                  setMessages([]);
                  setMessagesError(null);
                }
                setPendingDelete(null);
                await refresh();
              } finally {
                setDeleting(false);
              }
            }}
          >
            {deleting ? "Удаляю…" : "Удалить историю"}
          </button>
        </div>
      </AppDialog>

      <AppDialog
        open={Boolean(inspectModalData)}
        title={inspectModalData?.title || "Метаданные хода"}
        onClose={() => {
          setInspectModalData(null);
          setInspectCopied(false);
        }}
        variant="info"
        icon={<Terminal size={18} />}
      >
        <div className="journal-inspect-dialog-content">
          <div className="journal-inspect-actions">
            <span className="inspect-subtitle">Сырой JSON токенов, эмоций и памяти:</span>
            <button
              type="button"
              className="secondary btn-copy-json"
              onClick={async () => {
                if (!inspectModalData?.json) return;
                try {
                  await navigator.clipboard.writeText(
                    JSON.stringify(inspectModalData.json, null, 2),
                  );
                  setInspectCopied(true);
                  setTimeout(() => setInspectCopied(false), 2000);
                } catch {
                  // Fallback
                }
              }}
            >
              {inspectCopied ? <Check size={13} className="text-emerald" /> : <Copy size={13} />}
              <span>{inspectCopied ? "Скопировано!" : "Копировать JSON"}</span>
            </button>
          </div>
          <pre className="journal-raw-json-block">
            <code>{inspectModalData ? JSON.stringify(inspectModalData.json, null, 2) : ""}</code>
          </pre>
        </div>
      </AppDialog>
    </section>
  );
}

function EmptyHistory({ text }: { text: string }) {
  return (
    <div className="empty-state">
      <IconInterfaceTimeStopWatchCircle size={28} aria-hidden="true" />
      <strong>{text}</strong>
      <span>Здесь появятся прошлые разговоры.</span>
    </div>
  );
}

