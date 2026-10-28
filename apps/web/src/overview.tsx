import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MaterialButton } from "./components/MaterialButton";
import { OverviewTips } from "./components/OverviewTips";
import type { SettingsSection } from "./settings/registry";
import {
  IconComputerRobotCyborg1, IconMailChatBubbleTextSquare,
  IconInterfaceCursorArrow2, IconInterfaceCalendarMark, IconInterfaceArrowUpRight,
} from "./CustomIcons";
import { getMemories, getTimelineJournal, getTimelineMessages } from "./api";
import type { MemoryItem, TimelineJournalItem, TimelineMessage } from "./types";
import { getReminders, type Reminder } from "./product-api";
import { LoadingRing } from "./components/LoadingRing";
import { interfaceIntlLocale } from "./i18n";
import { animateStaggerCards } from "./animations";

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(interfaceIntlLocale(), {
    day: "numeric", month: "long", hour: "2-digit", minute: "2-digit",
    year: date.getFullYear() !== new Date().getFullYear() ? "numeric" : undefined,
  }).format(date);
}

export function OverviewPage({
  isActive = true, onOpenChat, onOpenHistory, onOpenMemory, onOpenPlans, onOpenSettings,
}: {
  isActive?: boolean;
  onOpenChat: () => void;
  onOpenHistory: (episode?: TimelineJournalItem) => void;
  onOpenMemory: () => void;
  onOpenPlans?: () => void;
  onOpenSettings?: (section: SettingsSection, focusId?: string) => void;
}) {
  const [journal, setJournal] = useState<TimelineJournalItem[] | null>(null);
  const [memories, setMemories] = useState<MemoryItem[] | null>(null);
  const [hasMoreMemories, setHasMoreMemories] = useState(false);
  const [reminder, setReminder] = useState<Reminder | null>(null);
  const [lastMessage, setLastMessage] = useState<TimelineMessage | null>(null);
  const [loading, setLoading] = useState(true);
  const [historyError, setHistoryError] = useState(false);
  const [memoryError, setMemoryError] = useState(false);
  const revision = useRef(0);
  const gridRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    const request = ++revision.current;
    setLoading(true);
    const [history, memory, scheduled] = await Promise.allSettled([
      getTimelineJournal(), getMemories("active"), getReminders(),
    ]);
    if (request !== revision.current) return;
    const historyItems = history.status === "fulfilled" && Array.isArray(history.value?.items) ? history.value.items : null;
    const memoryItems = memory.status === "fulfilled" && Array.isArray(memory.value?.items) ? memory.value.items : null;
    setHistoryError(historyItems === null);
    setMemoryError(memoryItems === null);
    if (historyItems !== null) setJournal(historyItems);
    if (memory.status === "fulfilled" && memoryItems !== null) {
      setMemories(memoryItems);
      setHasMoreMemories(memory.value.next_offset != null);
    }
    // Older cores may not expose reminders. Do not retain a stale reminder.
    const openReminders = scheduled.status === "fulfilled" && Array.isArray(scheduled.value?.items)
      ? scheduled.value.items.filter(item => item.status === "open" && Number.isFinite(Date.parse(item.due_at)))
      : [];
    setReminder(openReminders.sort((a, b) => Date.parse(a.due_at) - Date.parse(b.due_at))[0] ?? null);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (isActive) void refresh();
    return () => { revision.current++; };
  }, [isActive, refresh]);

  useEffect(() => {
    if (loading || !gridRef.current) return;
    const motion = animateStaggerCards(gridRef.current, ".overview-reveal", 16);
    return () => { motion?.revert(); };
  }, [loading]);

  const recentConversations = useMemo(() => [...(journal ?? [])]
    .filter(item => item.message_count > 0)
    .sort((a, b) => b.last_activity_at.localeCompare(a.last_activity_at)).slice(0, 3), [journal]);
  const latest = recentConversations[0];
  const canOpenLatest = Boolean(latest?.id || latest?.session_id);
  useEffect(() => {
    let current = true;
    setLastMessage(null);
    if (isActive && latest && (latest.id || latest.session_id)) {
      void getTimelineMessages(4, latest.session_id, latest.id).then(response => {
        if (!current) return;
        const message = [...(response?.items ?? [])].reverse()
          .find(item => (item.role === "user" || item.role === "assistant") && item.content.trim());
        setLastMessage(message ?? null);
      }).catch(() => { /* The conversation remains accessible without a preview. */ });
    }
    return () => { current = false; };
  }, [isActive, latest]);
  const activeMemories = useMemo(() => (memories ?? []).filter(item => item.status === "active"), [memories]);
  const recentMemories = useMemo(() => {
    const seen = new Set<string>();
    return [...activeMemories]
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
      .filter(item => {
        if (item.sensitivity !== "normal") return false;
        const key = item.value_text.trim().replace(/\s+/g, " ").toLocaleLowerCase();
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
      }).slice(0, 3);
  }, [activeMemories]);
  const historyPending = journal === null && loading;
  const memoryPending = memories === null && loading;
  const conversationAction = latest ? canOpenLatest ? "Открыть разговор" : "Открыть историю" : historyError ? "Открыть историю" : "Начать разговор";

  return (
    <section className="overview-page overview-home" aria-label="Обзор">
      {(historyError || memoryError) && <div className="notice overview-notice" role="alert">
        <span>Не удалось обновить часть обзора.</span>
        <MaterialButton materialKey="overview.button-2" className="text-button" disabled={loading} onClick={() => void refresh()}>Повторить</MaterialButton>
      </div>}

      <div className="overview-layout" ref={gridRef} aria-busy={loading}>
        <div className="overview-banner overview-reveal">
          <div className="overview-banner-copy">
            <h2>О чём поговорим?</h2>
            <MaterialButton materialKey="overview.button-1" className="primary-button" aria-label="Начать диалог" onClick={onOpenChat}>
              <span className="overview-action-label">Начать диалог</span><IconInterfaceCursorArrow2 size={18} aria-hidden="true" />
            </MaterialButton>
          </div>
        </div>

        <div className="overview-recap">
          <section className="settings-card overview-recent overview-reveal" aria-labelledby="overview-recent-heading">
            <header className="overview-section-heading">
              <h2 id="overview-recent-heading">Разговоры</h2>
              <MaterialButton materialKey="overview.history-all" className="icon-button" appearance="quiet" aria-label="Открыть историю" title="Открыть историю" onClick={() => onOpenHistory()}>
                <IconInterfaceArrowUpRight size={18} aria-hidden="true" />
              </MaterialButton>
            </header>

            <article className="overview-last-conversation" aria-labelledby="overview-conversation-title">
              <div className="overview-conversation-copy">
                <h3 id="overview-conversation-title" data-i18n-skip={latest?.title && latest.title !== "Разговор с Iris" ? "" : undefined}>
                  {historyPending ? "Загружаю разговор…" : latest?.title || (latest ? "Разговор с Iris" : historyError ? "История недоступна" : "Первый разговор — впереди")}
                </h3>
                {latest ? <p className="overview-conversation-meta">
                  <time dateTime={latest.last_activity_at}>{formatDate(latest.last_activity_at)}</time>
                  <span aria-hidden="true">·</span><span>{latest.message_count} сообщ.</span>
                </p> : <p className="overview-description">{historyPending ? "" : historyError ? "Попробуйте обновить обзор ещё раз." : "Обсудите идею, задайте вопрос или расскажите, как прошёл день. К беседе можно будет вернуться здесь."}</p>}
                {lastMessage && <p className="overview-last-message">
                  <span data-i18n-skip>{lastMessage.content.replace(/\s+/g, " ").trim()}</span>
                </p>}
              </div>
              <MaterialButton materialKey="overview.button-3" className="secondary-button overview-open-conversation" aria-label={conversationAction} disabled={historyPending} onClick={() => latest ? onOpenHistory(canOpenLatest ? latest : undefined) : historyError ? onOpenHistory() : onOpenChat()}>
                <span className="overview-action-label">{conversationAction}</span><IconInterfaceArrowUpRight size={16} aria-hidden="true" />
              </MaterialButton>
            </article>

            {recentConversations.length > 1 && <div className="overview-earlier">
              {recentConversations.slice(1).map((item, index) => <MaterialButton
                key={item.id ?? item.session_id ?? index}
                materialKey={`journal.episode.${item.id ?? item.day}`}
                className="history-item-minimal"
                onClick={() => onOpenHistory(item.id || item.session_id ? item : undefined)}
              >
                <span className="history-item-minimal-icon" aria-hidden="true"><IconMailChatBubbleTextSquare size={18} /></span>
                <span className="history-item-minimal-content">
                  <span className="history-item-minimal-header"><strong data-i18n-skip={item.title && item.title !== "Разговор с Iris" ? "" : undefined}>{item.title && item.title !== "Разговор с Iris" ? item.title : <time dateTime={item.last_activity_at}>{formatDate(item.last_activity_at)}</time>}</strong></span>
                  <span className="history-item-minimal-meta">{item.message_count} сообщ.</span>
                </span>
              </MaterialButton>)}
            </div>}
          </section>

          <section className="settings-card overview-memory-card overview-reveal" aria-labelledby="overview-memory-heading">
            <header className="overview-section-heading">
              <h2 id="overview-memory-heading"><IconComputerRobotCyborg1 size={20} aria-hidden="true" />Память</h2>
              <div className="overview-memory-actions">
                {memories !== null && <span className="memory-status">{activeMemories.length}{hasMoreMemories ? "+" : ""} сохранено</span>}
                <MaterialButton materialKey="overview.button-4" className="icon-button" appearance="quiet" aria-label="Открыть память" title="Открыть память" onClick={onOpenMemory}>
                  <IconInterfaceArrowUpRight size={18} aria-hidden="true" />
                </MaterialButton>
              </div>
            </header>
            {recentMemories.length ? <ul className="overview-memory-list">
              {recentMemories.map(item => <li key={item.id}><p className="memory-fact-value overview-memory-preview" data-i18n-skip>{item.value_text}</p></li>)}
            </ul> : <div className="overview-memory-content">
              <h3>{memoryPending ? "Загружаю память…" : memories === null && memoryError ? "Память недоступна" : activeMemories.length ? "Воспоминания под вашим контролем" : "Давайте знакомиться"}</h3>
              {!memoryPending && <p className="overview-description">{memories === null && memoryError ? "Попробуйте обновить обзор ещё раз." : activeMemories.length ? "Проверьте, что Iris запомнила, и исправьте неточности." : "Здесь появится то, что Iris запомнит из ваших разговоров."}</p>}
            </div>}
            {reminder && <div className="overview-next-plan" aria-label="Ближайшее напоминание">
              <div className="overview-plan-label"><IconInterfaceCalendarMark size={16} aria-hidden="true" /><span>{Date.parse(reminder.due_at) <= Date.now() ? "Пора вспомнить" : "Ближайшее напоминание"}</span></div>
              <h3 data-i18n-skip>{reminder.title}</h3>
              <time dateTime={reminder.due_at}>{formatDate(reminder.due_at)}</time>
              <MaterialButton materialKey="overview.open-reminders" className="icon-button" appearance="quiet" aria-label="Планы и обещания" title="Планы и обещания" onClick={onOpenPlans || onOpenMemory}>
                <IconInterfaceArrowUpRight size={16} aria-hidden="true" />
              </MaterialButton>
            </div>}
          </section>
        </div>
        <OverviewTips onOpenSettings={onOpenSettings} onOpenMemory={onOpenMemory} />
      </div>

      {loading && <span className="overview-loading" role="status">
        <LoadingRing className="is-inline" label="Обновляю обзор…" /><span>Обновляю данные…</span>
      </span>}
    </section>
  );
}
