import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Brain, MessageCircle, Orbit, RefreshCw, Sparkles } from "lucide-react";

import { getMemories, getTimelineJournal } from "./api";
import type { AvatarStatusResponse, MemoryItem, StatusResponse, TimelineJournalItem } from "./types";
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
  onOpenChat,
  onOpenHistory,
  onOpenMemory,
  onOpenSettings,
}: {
  status: StatusResponse | null;
  avatarStatus: AvatarStatusResponse | null;
  onOpenChat: () => void;
  onOpenHistory: () => void;
  onOpenMemory: () => void;
  onOpenSettings: () => void;
}) {
  const [journal, setJournal] = useState<TimelineJournalItem[]>([]);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
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
      const [history, memory] = await Promise.all([getTimelineJournal(), getMemories()]);
      setJournal(history.items);
      setMemories(memory.items);
      setError(null);
    } catch (cause) {
      setError(cause instanceof TypeError ? "Не удалось обновить обзор. Проверь подключение к Iris." : cause instanceof Error ? cause.message : "Данные обзора недоступны");
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
          <span>Iris рядом, когда хочется обсудить идею, разобрать задачу или просто выговориться.</span>
          <button className="primary-button overview-cta" onClick={handleCtaClick}>
            Начать диалог <ArrowRight size={18} aria-hidden="true" />
          </button>
        </div>
        <figure className="overview-visual" aria-hidden="true">
          <div className="overview-visual-inner" />
          <div className="overview-visual-ring" />
        </figure>
      </div>

      {error && <div className="notice" role="alert">{error}<button className="text-button" onClick={() => void refresh()}>Повторить</button></div>}

      <div className={`overview-grid${loading ? " is-loading" : ""}`} ref={gridRef} aria-busy={loading}>
        <article className="overview-card">
          <div className="overview-card-icon"><MessageCircle size={20} /></div>
          <div>
            <span>Последний разговор</span>
            <h3 data-i18n-skip={latest?.title && latest.title !== "Разговор с Iris" ? "" : undefined}>{latest?.title || (latest ? "Разговор с Iris" : "История пока пуста")}</h3>
            <p>{latest ? `${latest.message_count} сообщ. · ${formatRelative(latest.last_activity_at)}` : "Начни диалог — он появится здесь."}</p>
          </div>
          <button className="card-link" onClick={(e) => { animateButtonPress(e.currentTarget); if (latest) onOpenHistory(); else onOpenChat(); }}>
            {latest ? "Открыть историю" : "Начать разговор"}<ArrowRight size={15} />
          </button>
        </article>

        <article className="overview-card">
          <div className="overview-card-icon"><Brain size={20} /></div>
          <div>
            <span>Память</span>
            <h3>
              {activeCount ? (
                <>
                  <span ref={memoryCountRef}>{activeCount}</span> сохранено
                </>
              ) : (
                "Нет сохранённых записей"
              )}
            </h3>
            <p>Iris самостоятельно поддерживает актуальность фактов.</p>
          </div>
          <button className="card-link" onClick={(e) => { animateButtonPress(e.currentTarget); onOpenMemory(); }}>
            Открыть память<ArrowRight size={15} />
          </button>
        </article>

        <article className="overview-card">
          <div className="overview-card-icon"><Orbit size={20} /></div>
          <div>
            <span>Система</span>
            <h3>{backendReady ? `${status?.llm_provider} · ${status?.llm_model}` : "Backend недоступен"}</h3>
            <p>{avatarStatus?.enabled ? (avatarConnected ? `Аватар подключён: ${avatarStatus.client_count}` : "Аватар ожидает подключения") : "Аватар отключён"}</p>
          </div>
          <button className="card-link" onClick={(e) => { animateButtonPress(e.currentTarget); onOpenSettings(); }}>
            Диагностика<ArrowRight size={15} />
          </button>
        </article>
      </div>

      {loading && <span className="overview-loading"><RefreshCw size={16} className="is-spinning" />Обновляю реальные данные</span>}
    </section>
  );
}
