import { MaterialButton } from "./components/MaterialButton";
import {
  IconComputerRobotCyborg1,
  IconMailChatBubbleTextSquare,
  IconInterfaceSpirals,
  IconInterfaceCursorArrow2,
} from "./CustomIcons";
import { useEffect, useMemo, useRef, useState } from "react";

import { getMemories, getTimelineJournal } from "./api";
import type { AvatarStatusResponse, MemoryItem, ReadinessResponse, StatusResponse, TimelineJournalItem } from "./types";
import { getReminders, type Reminder } from "./product-api";
import { LoadingRing } from "./components/LoadingRing";
import { notify } from "./notifications";
import { interfaceIntlLocale } from "./i18n";
import {
  animate,
  animateButtonPress,
  animateNumberCounter,
  animateOrb,
  animateStaggerCards,
  prefersReducedMotion,
  stagger,
  useAnimeScope,
} from "./animations";

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 6) return "Доброй ночи";
  if (hour < 12) return "Доброе утро";
  if (hour < 18) return "Добрый день";
  return "Добрый вечер";
}

function formatRelative(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(interfaceIntlLocale(), {
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function OverviewPage({
  status,
  avatarStatus,
  readiness,
  onOpenChat,
  onOpenHistory,
  onOpenMemory,
  onOpenSettings,
  onOpenPlans,
}: {
  status: StatusResponse | null;
  avatarStatus: AvatarStatusResponse | null;
  readiness?: ReadinessResponse | null;
  onOpenChat: () => void;
  onOpenHistory: () => void;
  onOpenMemory: () => void;
  onOpenSettings: () => void;
  onOpenPlans?: () => void;
}) {
  const [journal, setJournal] = useState<TimelineJournalItem[]>([]);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [hasMoreMemories, setHasMoreMemories] = useState(false);
  const [reminder, setReminder] = useState<Reminder | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const containerRef = useAnimeScope<HTMLElement>((scope, root) => {
    const reduced = prefersReducedMotion();

    // Hero content entrance
    const heroElements = root.querySelectorAll(".overview-intro > *");
    if (heroElements.length) {
      animate(heroElements, {
        opacity: [0, 1],
        translateY: reduced ? 0 : [16, 0],
        scale: reduced ? 1 : [0.97, 1],
        duration: reduced ? 100 : 320,
        delay: reduced ? 0 : stagger(60, { from: "first" }),
        ease: "outBack(1.3)",
        onComplete: () => {
          heroElements.forEach((el) => {
            (el as HTMLElement).style.transform = "";
          });
        },
      });
    }

    // Hero visual ambient breathing glow & multi-ring rotation
    const visual = root.querySelector<HTMLElement>(".overview-visual");
    if (visual && !reduced) {
      animateOrb(visual);
    }
  }, []);

  const gridRef = useRef<HTMLDivElement | null>(null);
  const memoryCountRef = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    if (!loading && gridRef.current) {
      animateStaggerCards(gridRef.current, ".overview-card", 60);
    }
  }, [loading]);

  const activeCount = memories.filter((item) => item.status === "active").length;

  useEffect(() => {
    if (!loading && memoryCountRef.current && activeCount > 0) {
      animateNumberCounter(memoryCountRef.current, activeCount);
    }
  }, [loading, activeCount]);

  const refresh = async () => {
    setLoading(true);
    try {
      const [history, memory] = await Promise.all([getTimelineJournal(), getMemories("active")]);
      setJournal(history.items);
      try { const scheduled = await getReminders(); setReminder(scheduled.items.find(item => item.status === "open") || null); } catch { /* Core without reminders still supports the overview. */ }
      setMemories(memory.items);
      setHasMoreMemories(memory.next_offset != null);
      setError(null);
    } catch (cause) {
      const msg = cause instanceof TypeError ? "Не удалось обновить обзор. Проверьте подключение к Iris." : cause instanceof Error ? cause.message : "Данные обзора недоступны";
      setError(msg);
      notify.error("Обзор", msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void refresh(); }, []);

  const latest = useMemo(
    () => [...journal].sort((a, b) => b.last_activity_at.localeCompare(a.last_activity_at))[0],
    [journal],
  );
  const backendReady = status?.backend === "ok";
  const avatarConnected = Boolean(avatarStatus?.enabled && avatarStatus.client_count > 0);

  const handleCtaClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    animateButtonPress(e.currentTarget);
    onOpenChat();
  };

  return (
    <section className="overview-page" ref={containerRef}>
      <div className="overview-hero">
        <div className="overview-intro">
          <p>{greeting()}</p>
          <h2>О чём поговорим?</h2>
          <span>Обсудите идею, задайте вопрос или расскажите, как прошёл день.</span>
          <MaterialButton materialKey={"overview.button-1"} className="primary-button overview-cta" onClick={handleCtaClick}>
            Начать диалог <IconInterfaceCursorArrow2 size={18} aria-hidden="true" />
          </MaterialButton>
        </div>
        <figure className="overview-visual" aria-hidden="true">
          <div className="overview-visual-inner" />
          <div className="overview-visual-ring" />
        </figure>
      </div>

      {error && <div className="notice" role="alert">{error}<MaterialButton materialKey={"overview.button-2"} className="text-button" onClick={() => void refresh()}>Повторить</MaterialButton></div>}

      <div className={`overview-grid${loading ? " is-loading" : ""}`} ref={gridRef} aria-busy={loading}>
        <article className="overview-card">
          <div className="overview-card-icon"><IconMailChatBubbleTextSquare size={20} /></div>
          <div>
            <span>Последний разговор</span>
            <h3 data-i18n-skip={latest?.title && latest.title !== "Разговор с Iris" ? "" : undefined}>{latest?.title || (latest ? "Разговор с Iris" : "История пока пуста")}</h3>
            <p>{latest ? `${latest.message_count} сообщ. · ${formatRelative(latest.last_activity_at)}` : "Здесь появится ваш последний разговор с Iris."}</p>
          </div>
          <MaterialButton materialKey={"overview.button-3"} className="card-link" onClick={(e) => { animateButtonPress(e.currentTarget); if (latest) onOpenHistory(); else onOpenChat(); }}>
            {latest ? "Открыть историю" : "Начать разговор"}<IconInterfaceCursorArrow2 size={15} />
          </MaterialButton>
        </article>

        <article className="overview-card">
          <div className="overview-card-icon"><IconComputerRobotCyborg1 size={20} /></div>
          <div>
            <span>Память</span>
            <h3>
              {activeCount ? (
                <>
                  <span ref={memoryCountRef}>{activeCount}</span>{hasMoreMemories ? "+" : ""} сохранено
                </>
              ) : (
                "Нет сохранённых записей"
              )}
            </h3>
            <p>Проверьте, что Iris запомнила, и исправьте неточности.</p>
          </div>
          <MaterialButton materialKey={"overview.button-4"} className="card-link" onClick={(e) => { animateButtonPress(e.currentTarget); onOpenMemory(); }}>
            Открыть память<IconInterfaceCursorArrow2 size={15} />
          </MaterialButton>
        </article>

        <article className="overview-card">
          <div className="overview-card-icon"><IconInterfaceSpirals size={20} /></div>
          <div>
            <span>Система</span>
            <h3>{!backendReady ? "Нет связи с Iris" : !status?.api_key_configured ? "Нужен ключ модели" : readiness?.live_ready ? "Можно говорить" : readiness?.text_chat === "ready" ? "Текстовый диалог готов" : "Проверяем готовность"}</h3>
            <p>{avatarStatus?.enabled ? (avatarConnected ? "Аватар подключён" : "Аватар ожидает подключения") : "Аватар отключён"}</p>
          </div>
          <MaterialButton materialKey={"overview.button-5"} className="card-link" onClick={(e) => { animateButtonPress(e.currentTarget); onOpenSettings(); }}>
            Проверить готовность<IconInterfaceCursorArrow2 size={15} />
          </MaterialButton>
        </article>
      </div>

      {reminder && <section className="overview-plan"><h3>Ближайшее напоминание</h3><p data-i18n-skip>{reminder.title}</p><p>{new Date(reminder.due_at).toLocaleString()}</p><MaterialButton materialKey="overview.open-reminders" className="text-button" onClick={onOpenPlans || onOpenMemory}>Планы и обещания</MaterialButton></section>}
      {loading && (
        <span className="overview-loading" style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
          <LoadingRing className="is-inline" label="Обновляю обзор…" />
          <span>Обновляю данные…</span>
        </span>
      )}
    </section>
  );
}
