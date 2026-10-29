import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  IconInterfaceArrowUpRight as ArrowUpRight, IconInterfaceArrowRight as ArrowRight,
  IconInterfaceRefresh as RotateCw, IconMailChatBubbleTextSquare as MessageCircle,
  IconInterfaceTimeStopWatchCircle, IconInterfaceLayers,
} from "./CustomIcons";
import { MaterialButton } from "./components/MaterialButton";
import { OverviewTips } from "./components/OverviewTips";
import { ArtworkImage, OverviewGallery } from "./components/OverviewGallery";
import type { SettingsSection } from "./settings/registry";
import { getConversationUsage, getLlmTokenStats, getTimelineJournal, getTimelineMessages } from "./api";
import type { ConversationUsage, TimelineJournalItem, TimelineMessage } from "./types";
import { interfaceIntlLocale } from "./i18n";
import { animateStaggerCards } from "./animations";
import { OVERVIEW_HERO_ART } from "./overview-art";

function formatDate(value: string, short = false): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(interfaceIntlLocale(), {
    day: "numeric", month: "long", ...(!short ? { hour: "2-digit", minute: "2-digit" } as const : {}),
    year: date.getFullYear() !== new Date().getFullYear() ? "numeric" : undefined,
  }).format(date);
}

export function formatConversationTime(seconds: number): string {
  const english = interfaceIntlLocale() === "en-US";
  const min = english ? "min" : "мин";
  const hour = english ? "h" : "ч";
  const minutes = Math.floor(Math.max(0, seconds) / 60);
  if (!minutes) return `${seconds > 0 ? "< 1" : "0"} ${min}`;
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours.toLocaleString(interfaceIntlLocale())} ${hour}${minutes % 60 ? ` ${minutes % 60} ${min}` : ""}` : `${minutes} ${min}`;
}

type SourceErrors = { history: boolean; usage: boolean; tokens: boolean };

export function OverviewPage({ isActive = true, onOpenChat, onOpenHistory, onOpenMemory, onOpenSettings }: {
  isActive?: boolean;
  onOpenChat: () => void;
  onOpenHistory: (episode?: TimelineJournalItem) => void;
  onOpenMemory: () => void;
  onOpenPlans?: () => void;
  onOpenSettings?: (section: SettingsSection, focusId?: string) => void;
}) {
  const [journal, setJournal] = useState<TimelineJournalItem[] | null>(null);
  const [usage, setUsage] = useState<ConversationUsage | null>(null);
  const [tokens, setTokens] = useState<number | null>(null);
  const [lastMessage, setLastMessage] = useState<TimelineMessage | null>(null);
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState<SourceErrors>({ history: false, usage: false, tokens: false });
  const revision = useRef(0);
  const inFlight = useRef<number | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    if (inFlight.current !== null) return;
    const request = ++revision.current;
    inFlight.current = request;
    setLoading(true);
    const [history, time, expenses] = await Promise.allSettled([getTimelineJournal(), getConversationUsage(), getLlmTokenStats("all")]);
    if (request !== revision.current) return;
    const historyOk = history.status === "fulfilled" && Array.isArray(history.value?.items);
    const usageOk = time.status === "fulfilled" && Number.isFinite(time.value?.active_seconds) && time.value.active_seconds >= 0 && Number.isFinite(Date.parse(time.value.tracking_started_at));
    const tokensOk = expenses.status === "fulfilled" && Number.isFinite(expenses.value?.total_tokens) && expenses.value.total_tokens >= 0;
    if (historyOk) setJournal(history.value.items);
    if (usageOk) setUsage(time.value);
    if (tokensOk) setTokens(expenses.value.total_tokens);
    setErrors({ history: !historyOk, usage: !usageOk, tokens: !tokensOk });
    setLoading(false);
    inFlight.current = null;
  }, []);

  useEffect(() => {
    if (!isActive) return;
    void refresh();
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 30_000);
    return () => { window.clearInterval(timer); revision.current++; inFlight.current = null; };
  }, [isActive, refresh]);

  useEffect(() => {
    if (!isActive || !gridRef.current) return;
    const motion = animateStaggerCards(gridRef.current, ".overview-reveal", 24);
    return () => { motion?.revert(); };
  }, [isActive]);

  const conversations = useMemo(() => [...(journal ?? [])].filter(item => item.message_count > 0)
    .sort((a, b) => b.last_activity_at.localeCompare(a.last_activity_at)), [journal]);
  const latest = conversations[0];
  const latestId = latest?.id;
  const latestSession = latest?.session_id;
  const latestActivity = latest?.last_activity_at;
  const canOpenLatest = Boolean(latestId || latestSession);
  useEffect(() => {
    let current = true;
    setLastMessage(null);
    if (isActive && canOpenLatest) {
      void getTimelineMessages(4, latestSession, latestId).then(response => {
        if (current) setLastMessage([...(response?.items ?? [])].reverse().find(item => (item.role === "user" || item.role === "assistant") && item.content.trim()) ?? null);
      }).catch(() => { /* History remains accessible without a preview. */ });
    }
    return () => { current = false; };
  }, [isActive, canOpenLatest, latestId, latestSession, latestActivity]);

  const number = (value: number) => value.toLocaleString(interfaceIntlLocale());
  const stats = [
    { id: "time", label: "Время общения", icon: IconInterfaceTimeStopWatchCircle, value: !errors.usage && usage ? formatConversationTime(usage.active_seconds) : "—", error: errors.usage,
      hint: interfaceIntlLocale() === "en-US"
        ? `Text and voice, including pauses of up to five minutes.${usage ? ` Tracking since ${formatDate(usage.tracking_started_at, true)}.` : ""}`
        : `Текст и голос, включая паузы до пяти минут.${usage ? ` Начало учёта: ${formatDate(usage.tracking_started_at, true)}.` : ""}` },
    { id: "conversations", label: "Разговоры", icon: MessageCircle, value: !errors.history && journal ? number(conversations.length) : "—", error: errors.history },
    { id: "tokens", label: "Токены", icon: IconInterfaceLayers, value: !errors.tokens && tokens !== null ? number(tokens) : "—", error: errors.tokens, hint: "По сохранённой статистике расходов" },
  ];

  return <section className="overview-page overview-home" aria-label="Обзор">
    <div className="overview-layout" ref={gridRef}>
      <section className="overview-profile overview-reveal" aria-labelledby="overview-iris-heading">
        <div className="overview-hero-surface" aria-hidden="true" />
        <div className="overview-hero-copy">
          <h1 id="overview-iris-heading">Iris</h1>
          <p>Рядом, чтобы поговорить<br />и подумать вместе</p>
          <MaterialButton materialKey="overview.start" type="button" className="primary-button" onClick={onOpenChat}><span>Начать диалог</span><ArrowRight size={18} aria-hidden="true" /></MaterialButton>
        </div>
        <div className={`overview-hero-art is-${OVERVIEW_HERO_ART.kind}`} aria-hidden="true"><ArtworkImage src={OVERVIEW_HERO_ART.src} alt="" /></div>
      </section>

      <section className="overview-stats" aria-label="Статистика общения" aria-busy={loading}>
        {stats.map(({ id, label, icon: Icon, value, error, hint }) => <article key={id} className={`overview-stat overview-stat-${id} overview-surface overview-reveal`} aria-labelledby={`overview-stat-${id}`} title={error ? "Не удалось обновить" : hint}>
          <div className="overview-stat-copy"><h2 id={`overview-stat-${id}`}>{label}</h2><strong data-testid={`overview-stat-${id}-value`} data-i18n-skip>{value}</strong></div>
          {error ? <MaterialButton materialKey={`overview.retry.${id}`} type="button" className="icon-button overview-stat-retry" aria-label={`Повторить загрузку: ${label}`} disabled={loading} onClick={() => void refresh()}><RotateCw size={20} aria-hidden="true" /></MaterialButton>
            : <span className="overview-stat-icon" aria-hidden="true"><Icon size={24} /></span>}
        </article>)}
      </section>

      <OverviewGallery isActive={isActive} />

      <section className="overview-last overview-surface overview-reveal" aria-labelledby="overview-last-heading">
        <span className="overview-conversation-icon" aria-hidden="true"><MessageCircle size={24} /></span>
        <div className="overview-last-copy">
          <h2 id="overview-last-heading" data-i18n-skip={latest?.title ? "" : undefined}>{latest?.title || (latest ? "Разговор с Iris" : errors.history ? "История недоступна" : journal === null ? "Загружаю разговор…" : "Первый разговор — впереди")}</h2>
          {latest ? <p className="overview-last-meta"><time dateTime={latest.last_activity_at}>{formatDate(latest.last_activity_at)}</time><span> · {latest.message_count} сообщ.</span></p> : <p className="overview-last-meta">{errors.history ? "Попробуйте обновить данные." : journal !== null ? "Расскажите, как прошёл день, или поделитесь идеей." : ""}</p>}
          {lastMessage && <p className="overview-last-message" data-i18n-skip>{lastMessage.content.replace(/\s+/g, " ").trim()}</p>}
        </div>
        <MaterialButton materialKey="overview.last.open" type="button" className="icon-button overview-last-open" appearance="quiet" aria-label={latest ? "Открыть разговор" : errors.history ? "Открыть историю" : "Начать разговор"} disabled={journal === null && loading} onClick={() => latest ? onOpenHistory(canOpenLatest ? latest : undefined) : errors.history ? onOpenHistory() : onOpenChat()}><ArrowUpRight size={22} aria-hidden="true" /></MaterialButton>
      </section>
      <OverviewTips onOpenSettings={onOpenSettings} onOpenMemory={onOpenMemory} />
    </div>
    <span className="overview-loading" role="status">{loading ? "Обновляю обзор…" : ""}</span>
  </section>;
}
