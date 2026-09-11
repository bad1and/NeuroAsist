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
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { deleteTimelineRange, getTimelineJournal, getTimelineMessages, searchTimeline } from "./api";
import type { TimelineJournalItem, TimelineMessage } from "./types";
import { AppDialog } from "./components/AppDialog";
import { ChevronLeft, X } from "lucide-react";
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

export function JournalPage({ onOpenChat }: { onOpenChat?: () => void } = {}) {
  const [items, setItems] = useState<TimelineJournalItem[]>([]);
  const [selectedEpisode, setSelectedEpisode] = useState<TimelineJournalItem | null>(null);
  const [messages, setMessages] = useState<TimelineMessage[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [messagesError, setMessagesError] = useState<string | null>(null);
  const [results, setResults] = useState<TimelineMessage[] | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<TimelineJournalItem | null>(null);
  const [deleting, setDeleting] = useState(false);

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
    try {
      const response = await getTimelineMessages(200, undefined, episode.id);
      if (activeRequestIdRef.current === requestId) {
        setMessages(response.items);
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

  const onBack = () => {
    activeRequestIdRef.current++;
    setSelectedEpisode(null);
    setMessages([]);
    setMessagesError(null);
    setLoadingMessages(false);
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
                      {message.created_at && (
                        <span className="message-time">{formatTime(message.created_at)}</span>
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

                    </div>
                  </div>
                </div>

                <div className="journal-header-actions">

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
                    {messages.map((message) => {
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
                          {message.created_at && (
                            <span className="message-time">{formatTime(message.created_at)}</span>
                          )}
                        </article>
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

