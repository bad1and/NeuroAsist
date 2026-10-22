import { requestJson } from "./api";
import type { SearchFocus } from "./search-navigation";
import { MemoryContextDetails, DocumentSources } from "./components/MemoryContextDetails";
import { LoadingRing } from "./components/LoadingRing";
import { MaterialButton } from "./components/MaterialButton";
import {
  IconInterfaceTimeStopWatchCircle,
  IconInterfaceSpirals,
  IconInterfaceSearch,
  IconInterfaceDeleteBin3,
  IconMailChatBubbleTextSquare,
  IconInterfaceCursorArrow2,
  IconInterfaceCalendarMark,
  IconComputerRobotCyborg1,
  IconMailSmileyHappyFace,
  IconInterfaceFaceNeutral,
  IconInterfaceFaceSad,
  IconInterfaceAlertCircle,
  IconInterfaceHandGesturesOneFingerTap,
  IconShoppingBusinessTarget,
  type CustomIconComponent,
} from "./CustomIcons";
import { FormEvent, Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { deleteTimelineEpisode, getTimelineJournal, getTimelineMessages, searchTimeline } from "./api";
import type { TimelineJournalItem, TimelineMessage, TokenMetadata } from "./types";
import { calculateDeepSeekCostUsd } from "./deepseek";
import { AppDialog } from "./components/AppDialog";
import {
  IconInterfaceChevronLeft as ChevronLeft,
  IconInterfaceChevronDown as ChevronDown,
  IconInterfaceChevronRight as ChevronRight,
  IconInterfaceCross as X,
  IconInterfaceLightning as Zap,
  IconInterfaceEye as Eye,
  IconInterfaceSliders as Sliders,
  IconInterfaceSparkles as Sparkles,
  IconInterfaceBrain as Brain,
  IconInterfaceTerminal as Terminal,
  IconInterfaceCopy as Copy,
  IconInterfaceCheck as Check,
  IconInterfaceExternalLink as ExternalLink,
  IconMailChatBubbleTextSquare as MessageSquare,
  IconInterfaceClock as Clock3,
} from "./CustomIcons";
import { TokenDialogContent } from "./components/TokenBadge";
import { notify } from "./notifications";
import { currentInterfaceLocale, interfaceIntlLocale } from "./i18n";
import { animateButtonPress, animatePageEnter, animateStaggerCards, useAnimeScope } from "./animations";

function formatDate(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(interfaceIntlLocale(), { day: "numeric", month: "long", year: "numeric" }).format(date);
}

function memoryContextCount(value: unknown) { return Array.isArray(value) ? value.length : 0; }

function formatMessageCount(count: number): string {
  const value = new Intl.NumberFormat(interfaceIntlLocale()).format(count);
  if (currentInterfaceLocale() === "en") return `${value} ${count === 1 ? "message" : "messages"}`;
  const form = new Intl.PluralRules("ru").select(count);
  return `${value} ${form === "one" ? "сообщение" : form === "few" ? "сообщения" : "сообщений"}`;
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

const EMOTION_META: Record<string, { label: string; icon: CustomIconComponent }> = {
  neutral: { label: "Спокойствие", icon: IconInterfaceFaceNeutral },
  happy: { label: "Радость", icon: IconMailSmileyHappyFace },
  sad: { label: "Грусть", icon: IconInterfaceFaceSad },
  curious: { label: "Любопытство", icon: Brain },
  thinking: { label: "Размышление", icon: Brain },
  surprised: { label: "Удивление", icon: IconInterfaceAlertCircle },
  skeptical: { label: "Скепсис", icon: Eye },
  teasing: { label: "Игривость", icon: IconMailSmileyHappyFace },
  pouting: { label: "Обида", icon: IconInterfaceFaceSad },
  frustrated: { label: "Досада", icon: IconInterfaceFaceSad },
  shy: { label: "Смущение", icon: IconInterfaceFaceNeutral },
  excited: { label: "Восторг", icon: Sparkles },
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

function formatCost(usd: number): string {
  if (usd <= 0) return "$0.00";
  if (usd < 0.0001) return "<$0.0001";
  return `$${usd.toFixed(4)}`;
}

function JournalMessageFooter({ message, expanded, showToggle, detailsId, onToggle, onOpenTokens }: {
  message: TimelineMessage;
  expanded: boolean;
  showToggle: boolean;
  detailsId: string;
  onToggle: () => void;
  onOpenTokens: (tokens: TokenMetadata) => void;
}) {
  const tokens = message.metadata?.tokens;
  const hasTokens = Boolean(tokens && ((tokens.prompt_tokens ?? 0) > 0 || (tokens.completion_tokens ?? 0) > 0 || (tokens.total_tokens ?? 0) > 0));
  const tokenCount = message.role === "user" ? tokens?.prompt_tokens ?? tokens?.total_tokens ?? 0 : tokens?.completion_tokens ?? tokens?.total_tokens ?? 0;
  const tokenLabel = message.role === "user" ? "Токены запроса" : "Токены ответа";
  const emotion = message.metadata?.companion?.emotion;
  const memoryCount = message.metadata?.memory_updates?.length ?? 0;
  const hasDetails = Boolean(tokens || message.metadata?.companion || message.metadata?.web_search || message.metadata?.news || memoryCount);
  const date = message.created_at ? new Date(message.created_at) : null;

  return <footer className="journal-message-footer">
    <div className="journal-message-meta">
      {message.created_at && <time className="message-time" dateTime={message.created_at} title={date && !Number.isNaN(date.getTime()) ? date.toLocaleString(interfaceIntlLocale()) : undefined} data-i18n-skip>{formatTime(message.created_at)}</time>}
      {emotion && <span className="journal-emotion-micro-pill" title={`Эмоция: ${EMOTION_META[emotion]?.label || emotion}`}><Sparkles size={13} aria-hidden="true" />{EMOTION_META[emotion]?.label || emotion}</span>}
      {memoryCount > 0 && <span className="journal-memory-micro-pill"><Brain size={13} aria-hidden="true" /><span>Память: {memoryCount}</span></span>}
    </div>
    {(hasTokens || (showToggle && hasDetails)) && <div className="journal-message-actions">
      {hasTokens && tokens && <MaterialButton materialKey={`journal.tokens.${message.id}`} type="button" className="secondary journal-message-action journal-token-button" appearance="lens"
        aria-label={tokenLabel} title={`${tokenLabel}: ${tokenCount.toLocaleString(interfaceIntlLocale())}`} onClick={() => onOpenTokens(tokens)}>
        <Zap size={14} aria-hidden="true" /><span data-i18n-skip>{new Intl.NumberFormat(interfaceIntlLocale(), { notation: "compact", maximumFractionDigits: 1 }).format(tokenCount)} {currentInterfaceLocale() === "en" ? "tokens" : "ток."}</span>
      </MaterialButton>}
      {showToggle && hasDetails && <MaterialButton materialKey={`journal.details.${message.id}`} type="button" className="secondary journal-message-action journal-message-details-toggle" appearance="lens"
        aria-expanded={expanded} aria-controls={detailsId} onClick={onToggle}>
        <span>{expanded ? "Свернуть" : "Подробнее"}</span><ChevronDown size={14} aria-hidden="true" />
      </MaterialButton>}
    </div>}
  </footer>;
}

function JournalMessageDetails({
  message,
  onInspectJson,
}: {
  message: TimelineMessage;
  onInspectJson: (data: Record<string, unknown>, title: string) => void;
}) {
  const detailsRef = useAnimeScope<HTMLDivElement>((_scope, element) => {
    animatePageEnter(element);
  }, []);
  const isAssistant = message.role === "assistant";
  const tokens = message.metadata?.tokens;
  const companion = message.metadata?.companion;
  const memoryUpdates = message.metadata?.memory_updates;
  const webSearch = message.metadata?.web_search;
  const news = message.metadata?.news;
  const sourceBlocks = [
    ...(webSearch ? [{ label: "Поиск в интернете", data: webSearch }] : []),
    ...(news ? [{ label: "Новости", data: news }] : []),
  ];

  if (!tokens && !companion && sourceBlocks.length === 0 && (!memoryUpdates || memoryUpdates.length === 0)) {
    return null;
  }

  const emotionInfo = companion?.emotion
    ? EMOTION_META[companion.emotion] || { label: companion.emotion, icon: Sparkles }
    : null;
  const gestureLabel = companion?.gesture
    ? GESTURE_LABELS[companion.gesture] || companion.gesture
    : null;
  const intentLabel = companion?.intent
    ? INTENT_LABELS[companion.intent] || companion.intent
    : null;

  return (
    <div ref={detailsRef} className="journal-turn-details" data-testid="journal-turn-details">
      {/* 1. LLM Token & Cost Metrics */}
      {tokens && (
        <div className="details-section details-tokens-section">
          <div className="details-section-title">
            <Zap size={13} className="text-accent" />
            <span>Запрос к модели</span>
            {tokens.model && <span className="details-model-tag">{tokens.model}</span>}
          </div>

          <div className="details-metrics-grid">
            <div className="metric-cell">
              <span className="cell-label">На входе</span>
              <span className="cell-val text-prompt">
                {tokens.prompt_tokens?.toLocaleString(interfaceIntlLocale()) ?? "—"}
                {Boolean(tokens.prompt_cache_hit_tokens) && (
                  <small className="cache-hit-ratio">
                    <span>Из кэша:</span> {tokens.prompt_cache_hit_tokens?.toLocaleString(interfaceIntlLocale())}
                  </small>
                )}
              </span>
            </div>

            <div className="metric-cell">
              <span className="cell-label">В ответе</span>
              <span className="cell-val text-completion">
                {tokens.completion_tokens?.toLocaleString(interfaceIntlLocale()) ?? "—"}
              </span>
            </div>

            {Boolean(tokens.reasoning_tokens) && (
              <div className="metric-cell">
                <span className="cell-label">Рассуждения</span>
                <span className="cell-val text-reasoning">
                  {tokens.reasoning_tokens?.toLocaleString(interfaceIntlLocale())}
                </span>
              </div>
            )}

            <div className="metric-cell">
              <span className="cell-label">Всего</span>
              <span className="cell-val text-total">
                {tokens.total_tokens?.toLocaleString(interfaceIntlLocale()) ?? "—"}
              </span>
            </div>

            {tokens.latency_ms !== undefined && (
              <div className="metric-cell">
                <span className="cell-label">Задержка</span>
                <span className="cell-val">{tokens.latency_ms} мс</span>
              </div>
            )}

            <div className="metric-cell">
              <span className="cell-label">Оценка стоимости</span>
              <span className="cell-val text-cost">
                {formatCost(calculateDeepSeekCostUsd(tokens))}
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
            <span>Эмоции и жесты Iris</span>
          </div>

          <div className="companion-cues-row">
            {emotionInfo && (
              <div className="cue-badge emotion-cue" title={`Эмоция: ${companion.emotion}`}>
                <span className="cue-icon"><emotionInfo.icon size={14} aria-hidden="true" /></span>
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
                <span className="cue-icon"><IconInterfaceHandGesturesOneFingerTap size={14} aria-hidden="true" /></span>
                <span className="cue-text">Жест: <strong>{gestureLabel}</strong></span>
              </div>
            )}

            {intentLabel && (
              <div className="cue-badge intent-cue" title={`Намерение: ${companion.intent}`}>
                <span className="cue-icon"><IconShoppingBusinessTarget size={14} aria-hidden="true" /></span>
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

      {isAssistant && sourceBlocks.map(({ label, data: webSearch }) => (
        <div key={label} className="details-section details-web-search-section">
          <div className="details-section-title">
            <IconInterfaceSearch size={13} />
            <span>{label}</span>
            <span className={`details-search-status status-${webSearch.status}`}>
              {webSearch.status === "ok" ? "Найдено" : "Без результатов"}
            </span>
          </div>
          <div className="web-search-query">
            <span>Запрос</span>
            <strong>{webSearch.query || "Некорректный поисковый запрос"}</strong>
            {webSearch.cached && <small>из кэша</small>}
            {webSearch.stale && <small>обновление не удалось; данные могут устареть</small>}
            {webSearch.latency_ms !== undefined && <small>{(webSearch.latency_ms / 1000).toFixed(1)} с</small>}
            {webSearch.canonical_entity && <small>Предмет: {webSearch.canonical_entity}</small>}
            {webSearch.evidence_status && <small>Доказательства: {({ sufficient: "достаточно", partial: "частично", none: "не получены", topic_only: "только по теме", provisional: "предварительные", available: "получены" } as Record<string, string>)[webSearch.evidence_status] ?? webSearch.evidence_status}</small>}
            {webSearch.quota?.used !== undefined && <small>Квота: {webSearch.quota.used} / {webSearch.quota.limit}</small>}
          </div>
          {webSearch.attempts?.map((attempt, index) => <div className="web-search-query" key={index}>
            <span>Попытка {index + 1} · {attempt.provider}</span>
            <strong>{attempt.query}</strong>
            <small>{attempt.status} · принято {attempt.accepted} · {(attempt.latency_ms / 1000).toFixed(1)} с{attempt.cached ? " · из кэша" : attempt.searched === false ? " · поиск не отправлен" : ""}</small>
          </div>)}
          {webSearch.sources.length > 0 ? (
            <div className="web-search-sources">
              {webSearch.sources.map((source, index) => (
                <a
                  key={`${source.url}-${index}`}
                  href={source.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="web-search-source"
                >
                  <span>{source.title || source.url}{source.published_at && <small> · {source.published_at.slice(0, 10)}</small>}</span>
                  <ExternalLink size={13} aria-hidden="true" />
                </a>
              ))}
            </div>
          ) : (
            <div className="memory-empty-note">Подтверждённые источники не получены</div>
          )}
        </div>
      ))}

      {/* 3. Memory Updates */}
      {memoryUpdates && memoryUpdates.length > 0 && <div className="details-section details-memory-section">
        <div className="details-section-title">
          <Brain size={13} className="text-cyan" />
          <span>Что Iris запомнила</span>
        </div>

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
      </div>}

      {/* 4. Raw JSON Inspection Button */}
      <div className="details-footer-actions">
        <MaterialButton materialKey={"journal.button-1"}
          type="button"
          className="secondary journal-message-action details-json-btn"
          onClick={() =>
            onInspectJson(
              (message.metadata as Record<string, unknown>) || {},
              `Метаданные сообщения #${message.id.slice(0, 8)}`,
            )
          }
          title="Открыть JSON сообщения"
        >
          <Terminal size={12} />
          <span>JSON сообщения</span>
        </MaterialButton>
      </div>
    </div>
  );
}

export function JournalPage({
  onOpenChat,
  isActive = true,
  focusRequest,
  developerMode = false,
  currentSessionId,
}: {
  onOpenChat?: () => void;
  isActive?: boolean;
  focusRequest?: SearchFocus;
  developerMode?: boolean;
  currentSessionId?: string | null;
} = {}) {
  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState<TimelineJournalItem[]>([]);
  const [selectedEpisode, setSelectedEpisode] = useState<TimelineJournalItem | null>(null);
  const [messages, setMessages] = useState<TimelineMessage[]>([]);
  const [expandedMessageIds, setExpandedMessageIds] = useState<Set<string>>(() => new Set());
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

  // Keep the readable view independent of the removed global preference.
  // Individual messages still expose their existing details disclosure.
  const [detailMode] = useState<"simple" | "detailed">("simple");

  const [inspectModalData, setInspectModalData] = useState<{
    title: string;
    json: Record<string, unknown>;
  } | null>(null);
  const [inspectCopied, setInspectCopied] = useState(false);
  const [tokenDialogData, setTokenDialogData] = useState<{
    tokens: TokenMetadata;
    role: "user" | "assistant" | "system_event";
  } | null>(null);

  const searchContextRef = useRef(false);
  const lastFocusedRequest = useRef("");
  const activeRequestIdRef = useRef(0);
  const searchRequestIdRef = useRef(0);
  useEffect(() => () => {
    activeRequestIdRef.current++;
    searchRequestIdRef.current++;
    lastFocusedRequest.current = "";
  }, []);

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

  const onSelectEpisode = useCallback(async (episode: TimelineJournalItem) => {
    searchContextRef.current = false;
    const requestId = ++activeRequestIdRef.current;
    setSelectedEpisode(episode);
    setExpandedMessageIds(new Set());
    setLoadingMessages(true);
    setLoadingMoreMessages(false);
    setMessagesError(null);
    setHasMoreMessages(false);
    setMessageOffset(null);
    try {
      const response = await getTimelineMessages(200, episode.session_id, episode.id);
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
  }, []);

  const refresh = useCallback(async () => {
    try {
      const response = await getTimelineJournal();
      setItems(response.items);
      setError(null);
      setSelectedEpisode((current) => {
        if (current && response.items.length > 0) {
          const updated = response.items.find(
            (item) => (item.id && item.id === current.id) || (!item.id && item.day === current.day),
          );
          if (updated) {
            if (!searchContextRef.current && (updated.message_count !== current.message_count || !updated.ended_at)) {
              void onSelectEpisode(updated);
            }
            return updated;
          }
        }
        return current;
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "История недоступна");
    } finally {
      setLoading(false);
    }
  }, [onSelectEpisode]);

  useEffect(() => {
    if (isActive) {
      void refresh();
    }
  }, [isActive, refresh]);

  useEffect(() => {
    if (!isActive || !focusRequest || lastFocusedRequest.current === focusRequest.requestId) return;
    lastFocusedRequest.current = focusRequest.requestId;
    searchContextRef.current = true;
    const revision = ++activeRequestIdRef.current;
    setResults(null); setQuery(""); setLoadingMessages(true); setMessagesError(null);
    void requestJson<{ items: TimelineMessage[]; episode: TimelineJournalItem; next_offset: number | null }>(`/timeline/messages/${encodeURIComponent(focusRequest.id)}/context`).then(response => {
      if (revision !== activeRequestIdRef.current) return;
      setSelectedEpisode(response.episode); setMessages(response.items);
      setMessageOffset(response.next_offset); setHasMoreMessages(response.next_offset !== null);
    }).catch(cause => { if (revision === activeRequestIdRef.current) { const message = cause instanceof Error ? cause.message : "Не удалось открыть сообщение"; setMessagesError(message); setError(message); } }).finally(() => { if (revision === activeRequestIdRef.current) setLoadingMessages(false); });
  }, [focusRequest, isActive]);

  useEffect(() => {
    if (loadingMessages || !searchContextRef.current || !focusRequest) return;
    const target = document.getElementById(`history-message-${focusRequest.id}`);
    if (target) { target.classList.add("search-focus-target"); if (!target.hasAttribute("tabindex")) target.tabIndex = -1; target.scrollIntoView?.({ block: "center", behavior: "instant" }); target.focus({ preventScroll: true }); }
  }, [messages, loadingMessages, focusRequest]);

  const onLoadMoreMessages = async () => {
    if (!selectedEpisode || (!selectedEpisode.id && !selectedEpisode.session_id) || messageOffset === null || loadingMoreMessages) return;
    const requestId = activeRequestIdRef.current;
    setLoadingMoreMessages(true);
    try {
      const response = await getTimelineMessages(100, selectedEpisode.session_id, selectedEpisode.id, messageOffset);
      if (requestId !== activeRequestIdRef.current) return;
      setMessages((prev) => [...new Map([...response.items, ...prev].map(message => [message.id, message])).values()]);
      setHasMoreMessages(response.next_offset !== null && response.next_offset !== undefined);
      setMessageOffset(response.next_offset ?? null);
    } catch (cause) {
      if (requestId !== activeRequestIdRef.current) return;
      const msg = cause instanceof Error ? cause.message : "Не удалось загрузить ранние сообщения";
      notify.error("Журнал", msg);
    } finally {
      if (requestId === activeRequestIdRef.current) setLoadingMoreMessages(false);
    }
  };

  const onBack = () => {
    activeRequestIdRef.current++;
    setSelectedEpisode(null);
    setMessages([]);
    setExpandedMessageIds(new Set());
    setMessagesError(null);
    setLoadingMessages(false);
    setHasMoreMessages(false);
    setMessageOffset(null);
  };

  const onSearch = async (event: FormEvent) => {
    event.preventDefault();
    const requestId = ++searchRequestIdRef.current;
    if (!query.trim()) {
      setResults(null);
      return;
    }
    try {
      const response = await searchTimeline(query);
      if (requestId !== searchRequestIdRef.current) return;
      setResults(response.items);
      setError(null);
    } catch (cause) {
      if (requestId !== searchRequestIdRef.current) return;
      const msg = cause instanceof Error ? cause.message : "Не удалось выполнить поиск";
      setError(msg);
      notify.error("Журнал", msg);
    }
  };

  const handleResetSearch = () => {
    searchRequestIdRef.current++;
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
                onChange={(event) => { searchRequestIdRef.current++; setQuery(event.target.value); }}
                placeholder="Поиск по истории"
                aria-label="Поиск по истории"
              />
              {query && !results && (
                <MaterialButton materialKey={"journal.button-2"}
                  appearance="quiet"
                  className="search-clear-btn"
                  type="button"
                  onClick={handleResetSearch}
                  aria-label="Очистить поле поиска"
                  title="Очистить"
                >
                  <X size={12} aria-hidden="true" />
                </MaterialButton>
              )}
              {results && (
                <MaterialButton materialKey={"journal.button-3"}
                  appearance="quiet"
                  className="secondary reset-search-button"
                  type="button"
                  onClick={handleResetSearch}
                >
                  Сбросить
                </MaterialButton>
              )}

              <MaterialButton materialKey={"journal.button-4"}
                appearance="quiet"
                className="icon-button search-submit"
                type="submit"
                aria-label="Найти в истории"
                title="Найти в истории"
              >
                <IconInterfaceSearch size={16} />
              </MaterialButton>
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
                  const isExpanded = detailMode === "detailed" || expandedMessageIds.has(message.id);


                  return (
                    <article
                      className={`journal-message ${roleClass}${isExpanded ? " is-expanded" : ""}`}
                      key={message.id}
                      id={`history-message-${message.id}`}
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
                      {developerMode && memoryContextCount(message.metadata?.context_memories) > 0 && <MemoryContextDetails messageId={message.id} count={memoryContextCount(message.metadata?.context_memories)} sessionId={currentSessionId} />}
                      <DocumentSources value={message.metadata?.document_context} />
                      <JournalMessageFooter message={message} expanded={isExpanded} showToggle={detailMode === "simple"} detailsId={`journal-search-message-details-${message.id}`}
                        onOpenTokens={tokens => setTokenDialogData({ tokens, role: message.role })}
                        onToggle={() => setExpandedMessageIds(current => {
                          const next = new Set(current);
                          if (next.has(message.id)) next.delete(message.id); else next.add(message.id);
                          return next;
                        })} />
                      <div id={`journal-search-message-details-${message.id}`} className="journal-message-details" hidden={!isExpanded} role="region" aria-label="Подробности сообщения">{isExpanded && (
                        <JournalMessageDetails
                          message={message}
                          onInspectJson={(json, title) => setInspectModalData({ json, title })}
                        />
                      )}</div>
                    </article>
                  );
                })
              ) : (
                <EmptyHistory text="Ничего не найдено" />
              )}
            </div>
          ) : (
            <div className="history-list" ref={listRef}>
              {loading && !items.length ? <LoadingRing label="Загружаю историю…" /> : items.length ? (
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
                  <MaterialButton materialKey={"journal.button-5"}
                    className="journal-back-button secondary"
                    type="button"
                    onClick={onBack}
                    aria-label="Назад к списку"
                    title="Назад к списку"
                  >
                    <ChevronLeft size={16} aria-hidden="true" />
                  </MaterialButton>
                  <div className="journal-header-title-group">
                    <h2 data-i18n-skip title={selectedEpisode.title || formatDate(selectedEpisode.day)}>{selectedEpisode.title || formatDate(selectedEpisode.day)}</h2>
                    <div className="journal-header-meta">
                      <span className="journal-header-stat" data-i18n-skip title={formatMessageCount(selectedEpisode.message_count)}>
                        <MessageSquare size={14} aria-hidden="true" />
                        <span className="journal-header-count-label">{formatMessageCount(selectedEpisode.message_count)}</span>
                        <span className="journal-header-count-short" aria-hidden="true">{selectedEpisode.message_count.toLocaleString(interfaceIntlLocale())}</span>
                      </span>
                      {selectedEpisode.last_activity_at ? (
                        <time className="journal-header-stat" dateTime={selectedEpisode.last_activity_at} title={formatDate(selectedEpisode.last_activity_at)}>
                          <Clock3 size={14} aria-hidden="true" />
                          {formatTime(selectedEpisode.last_activity_at)}
                        </time>
                      ) : selectedEpisode.started_at ? (
                        <time className="journal-header-stat" dateTime={selectedEpisode.started_at}>
                          <Clock3 size={14} aria-hidden="true" />
                          {formatShortDate(selectedEpisode.started_at)}
                        </time>
                      ) : null}
                      {Boolean(selectedEpisode.token_estimate && selectedEpisode.token_estimate > 0) && (
                        <MaterialButton materialKey={"journal.button-6"}
                          type="button"
                          className="secondary journal-episode-tokens"
                          appearance="lens"
                          title="Нажмите для просмотра статистики токенов диалога"
                          aria-label={`${currentInterfaceLocale() === "en" ? "Conversation token statistics" : "Статистика токенов диалога"}: ${selectedEpisode.token_estimate?.toLocaleString(interfaceIntlLocale())}`}
                          onClick={() => {
                            const lastMsgWithTokens = [...messages].reverse().find((m) => m.metadata?.tokens);
                            if (lastMsgWithTokens?.metadata?.tokens) {
                              setTokenDialogData({
                                tokens: lastMsgWithTokens.metadata.tokens,
                                role: lastMsgWithTokens.role,
                              });
                            } else {
                              setTokenDialogData({
                                tokens: {
                                  total_tokens: selectedEpisode.token_estimate,
                                  prompt_tokens: Math.round(selectedEpisode.token_estimate! * 0.75),
                                  completion_tokens: Math.round(selectedEpisode.token_estimate! * 0.25),
                                  model: "Оценка сессии",
                                },
                                role: "assistant",
                              });
                            }
                          }}
                        >
                          <Zap size={14} aria-hidden="true" />
                          <span data-i18n-skip>{selectedEpisode.token_estimate?.toLocaleString(interfaceIntlLocale())}<span className="journal-header-token-unit"> {currentInterfaceLocale() === "en" ? "tokens" : "ток."}</span></span>
                          <ChevronRight className="journal-header-token-chevron" size={13} aria-hidden="true" />
                        </MaterialButton>
                      )}
                    </div>
                  </div>
                </div>

                <div className="journal-header-actions">
                  <MaterialButton materialKey={"journal.button-9"}
                    className="secondary journal-delete-action"
                    type="button"
                    title="Удалить этот диалог"
                    aria-label="Удалить этот диалог"
                    disabled={!selectedEpisode.id || deleting}
                    onClick={(e) => {
                      animateButtonPress(e.currentTarget);
                      setPendingDelete(selectedEpisode);
                    }}
                  >
                    <IconInterfaceDeleteBin3 size={17} aria-hidden="true" />
                  </MaterialButton>
                </div>
                {searchContextRef.current && <MaterialButton materialKey="journal.full-context" type="button" className="secondary journal-full-context" onClick={() => void onSelectEpisode(selectedEpisode)}>Показать полный диалог</MaterialButton>}
              </header>

              <div className="journal-messages-container" ref={messagesContainerRef}>
                {loadingMessages ? (
                  <LoadingRing label="Загружаю сообщения…" />
                ) : messagesError ? (
                  <p className="error-text" role="alert">{messagesError}</p>
                ) : messages.length ? (
                  <div className="journal-message-list">
                    {hasMoreMessages && (
                      <MaterialButton materialKey={"journal.button-10"}
                        className="journal-load-more-btn"
                        type="button"
                        disabled={loadingMoreMessages}
                        onClick={() => void onLoadMoreMessages()}
                      >
                        {loadingMoreMessages ? "Загрузка…" : "Загрузить более ранние сообщения"}
                      </MaterialButton>
                    )}
                    {messages.map((message, idx) => {
                      const isUser = message.role === "user";
                      const isAssistant = message.role === "assistant";
                      const roleLabel = isUser ? "Вы" : isAssistant ? "Iris" : "Событие";
                      const roleClass = isUser ? "user" : isAssistant ? "assistant" : "system";
                      const prevDate = idx > 0 ? messages[idx - 1].created_at : null;
                      const showDateSep = shouldShowDateSeparator(prevDate, message.created_at);
                      const isExpanded = detailMode === "detailed" || expandedMessageIds.has(message.id);


                      return (
                        <Fragment key={message.id}>
                          {showDateSep && (
                            <div className="journal-date-divider" role="separator">
                              <span>{formatDateSeparatorLabel(message.created_at)}</span>
                            </div>
                          )}
                          <article
                            id={`history-message-${message.id}`}
                            className={`journal-message ${roleClass}${isExpanded ? " is-expanded" : ""}`}
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
                            {developerMode && memoryContextCount(message.metadata?.context_memories) > 0 && <MemoryContextDetails messageId={message.id} count={memoryContextCount(message.metadata?.context_memories)} sessionId={currentSessionId} />}
                            <DocumentSources value={message.metadata?.document_context} />
                            <JournalMessageFooter message={message} expanded={isExpanded} showToggle={detailMode === "simple"} detailsId={`journal-message-details-${message.id}`}
                              onOpenTokens={tokens => setTokenDialogData({ tokens, role: message.role })}
                              onToggle={() => setExpandedMessageIds(current => {
                                const next = new Set(current);
                                if (next.has(message.id)) next.delete(message.id); else next.add(message.id);
                                return next;
                              })} />
                            <div id={`journal-message-details-${message.id}`} className="journal-message-details" hidden={!isExpanded} role="region" aria-label="Подробности сообщения">{isExpanded && (
                                <JournalMessageDetails
                                  message={message}
                                  onInspectJson={(json, title) => setInspectModalData({ json, title })}
                                />
                            )}</div>
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
        title="Удалить этот диалог?"
        description={
          pendingDelete
            ? `Диалог от ${formatDate(pendingDelete.day)} будет удалён без возможности восстановления. Остальная история сохранится.`
            : undefined
        }
        onClose={() => !deleting && setPendingDelete(null)}
        variant="danger"
      >
        <div className="dialog-actions">
          <MaterialButton materialKey={"journal.button-12"}
            className="secondary"
            type="button"
            onClick={() => setPendingDelete(null)}
            disabled={deleting}
          >
            Отмена
          </MaterialButton>
          <MaterialButton materialKey={"journal.button-13"}
            className="danger-button"
            type="button"
            disabled={deleting}
            onClick={async () => {
              if (!pendingDelete?.id || deleting) return;
              setDeleting(true);
              try {
                await deleteTimelineEpisode(pendingDelete.id);
                if (
                  selectedEpisode &&
                  selectedEpisode.id === pendingDelete.id
                ) {
                  activeRequestIdRef.current++;
                  setSelectedEpisode(null);
                  setMessages([]);
                  setMessagesError(null);
                }
                setPendingDelete(null);
                handleResetSearch();
                await refresh();
              } catch (cause) {
                notify.error("Журнал", cause instanceof Error ? cause.message : "Не удалось удалить диалог.");
              } finally {
                setDeleting(false);
              }
            }}
          >
            {deleting ? "Удаляю…" : "Удалить диалог"}
          </MaterialButton>
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
            <MaterialButton materialKey={"journal.button-14"}
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
            </MaterialButton>
          </div>
          <pre className="journal-raw-json-block">
            <code>{inspectModalData ? JSON.stringify(inspectModalData.json, null, 2) : ""}</code>
          </pre>
        </div>
      </AppDialog>

      <AppDialog
        open={Boolean(tokenDialogData)}
        title="Статистика токенов"
        description={tokenDialogData?.tokens.model || "Детализация использования токенов"}
        onClose={() => setTokenDialogData(null)}
        variant="info"
        icon={<Zap size={22} />}
      >
        {tokenDialogData && (
          <TokenDialogContent
            tokens={tokenDialogData.tokens}
            role={tokenDialogData.role}
            onClose={() => setTokenDialogData(null)}
          />
        )}
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

