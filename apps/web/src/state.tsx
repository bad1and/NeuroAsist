import { AppCheckbox } from "./components/AppCheckbox";
import { DisclosureTrigger } from "./components/Disclosure";
import { SlidingSegments } from "./components/SlidingSegments";
import { LoadingRing } from "./components/LoadingRing";
import { ButtonMaterialLayers, MaterialButton } from "./components/MaterialButton";
import { buttonSeed, materialStyle } from "./components/buttonMaterial";
import { Fragment, useCallback, useEffect, useId, useRef, useState, useMemo, type ReactNode } from "react";
import { deleteCharacterReflection, getCharacterReflections, getCharacterState, getCharacterStateEvents, getReflectionSettings, resetCharacterState, updateReflectionSettings } from "./api";
import type { CharacterReflection, CharacterStateEvent, CharacterStateView } from "./types";
import { interfaceIntlLocale } from "./i18n";
import { animateButtonPress, animateCardRemove, animatePageEnter, animateStaggerCards, useAnimeScope } from "./animations";
import { IrisMoodOrb } from "./components/IrisMoodOrb";
import { getMoodVisuals } from './mood-visuals';
import { IconInterfaceCalendarMark, IconInterfaceEditMagicWand } from "./CustomIcons";
import {
  IconInterfaceArrowRight as ArrowRight,
  IconInterfaceCheck as Check,
  IconInterfaceHeart as Heart,
  IconHealthMedicalHeartCare1 as HandHeart,
  IconUsersFeedback as Handshake,
  IconMailChatBubbleTextSquare as MessageCircle,
  IconInterfaceReset as RotateCcw,
  IconInterfaceSecurityShield4 as ShieldAlert,
  IconMailSmileyHappyFace as Smile,
  IconInterfaceSparkles as Sparkles,
  type CustomIconComponent,
} from "./CustomIcons";
import { eventEmotion, groupMoodCauses, relationshipLevel, relationshipValue, stateEventKind, stateEventLabel, timelineEmotion } from "./state-presentation";
import { useTimelineScrollFade } from "./state-timeline-scroll";
import "./state.css";
import { AppDialog } from "./components/AppDialog";
import { notify } from "./notifications";

const labels: Record<string, string> = {
  primary_emotion: "Главная эмоция", expression_strength: "Выразительность", secondary_emotions: "Вторичные эмоции",
  familiarity_label: "Знакомство", trust_label: "Доверие", warmth_label: "Теплота", tension_label: "Напряжение", playfulness_label: "Игривость",
  current_dynamic: "Текущая динамика", unresolved_cause: "Нерешённая причина",
};
function timelineDayKey(timestamp: number) {
  return new Date(timestamp).toDateString();
}

function formatTimelineDay(timestamp: number) {
  const date = new Date(timestamp);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return "Сегодня";
  if (date.toDateString() === yesterday.toDateString()) return "Вчера";
  return date.toLocaleDateString(interfaceIntlLocale(), { day: "numeric", month: "long", ...(date.getFullYear() !== today.getFullYear() ? { year: "numeric" } : {}) });
}

function formatTimelineTime(dateStr: string) {
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return dateStr;
  return date.toLocaleTimeString(interfaceIntlLocale(), { hour: "2-digit", minute: "2-digit" });
}

const EVENT_ICONS: Record<string, CustomIconComponent> = {
  insult: ShieldAlert, broken_promise: ShieldAlert, important_negative_event: ShieldAlert,
  shared_success: Sparkles, important_news: Sparkles, praise: Sparkles,
  teasing: Smile, apology: Handshake, support: HandHeart, affection: Heart,
  vulnerability: Heart, fulfilled_promise: Check,
};

function TimelineCard({ emotion, materialKey, children }: {
  emotion: ReturnType<typeof timelineEmotion>; materialKey: string; children: ReactNode;
}) {
  const seed = buttonSeed(materialKey);
  return <div className={`timeline-content card-glass${emotion ? " timeline-emotion-card dp-lens" : ""}`}
    data-emotion-tone={emotion?.tone}
    style={emotion ? materialStyle(seed, .35) : undefined}>
    {emotion && <ButtonMaterialLayers />}
    {children}
  </div>;
}

type TimelineItem =
  | { type: "event"; timestamp: number; key: string; data: CharacterStateEvent }
  | { type: "reflection"; timestamp: number; key: string; data: CharacterReflection }
  | { type: "neutral_group"; timestamp: number; key: string; count: number };

export function StatePage({ events: liveEvents = [] }: { events?: Array<{ type: string }> }) {
  const [state, setState] = useState<CharacterStateView | null>(null);
  const [events, setEvents] = useState<CharacterStateEvent[]>([]);
  const [reflections, setReflections] = useState<CharacterReflection[]>([]);
  const [reflectionEnabled, setReflectionEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingReset, setPendingReset] = useState<{
    scope: "mood" | "relationship";
    title: string;
    description: string;
  } | null>(null);
  const [pendingDeleteReflection, setPendingDeleteReflection] = useState<{
    id: string;
    el?: HTMLElement | null;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [causesExpanded, setCausesExpanded] = useState(false);
  const causesId = useId();
  const causeListRef = useRef<HTMLUListElement>(null);
  const causeGroups = useMemo(() => groupMoodCauses(state?.causes ?? []), [state?.causes]);
  const visibleCauses = causesExpanded ? causeGroups : causeGroups.slice(0, 3);

  const containerRef = useAnimeScope<HTMLElement>((scope, root) => {
    animatePageEnter(root);
  }, []);

  const [filterOnlyImportant, setFilterOnlyImportant] = useState(true);
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const timelineContentRef = useRef<HTMLDivElement | null>(null);
  useTimelineScrollFade(timelineRef, timelineContentRef);

  const timelineItems = useMemo(() => {
    const rawItems: Array<
      | { type: "event"; timestamp: number; key: string; data: CharacterStateEvent }
      | { type: "reflection"; timestamp: number; key: string; data: CharacterReflection }
    > = [];
    for (const e of events) {
      rawItems.push({ type: "event", timestamp: new Date(e.created_at).getTime(), key: "evt-" + e.id, data: e });
    }
    for (const r of reflections) {
      rawItems.push({ type: "reflection", timestamp: new Date(r.created_at).getTime(), key: "ref-" + r.id, data: r });
    }
    rawItems.sort((a, b) => b.timestamp - a.timestamp);

    if (!filterOnlyImportant) {
      return rawItems as TimelineItem[];
    }

    const filtered: TimelineItem[] = [];
    let neutralGroupCount = 0;
    let latestNeutralTimestamp = 0;
    let latestNeutralKey = "";

    const flushNeutrals = () => {
      if (neutralGroupCount > 0) {
        filtered.push({
          type: "neutral_group",
          timestamp: latestNeutralTimestamp,
          key: `neutrals-${latestNeutralKey}`,
          count: neutralGroupCount,
        });
        neutralGroupCount = 0;
      }
    };

    for (const item of rawItems) {
      if (item.type === "event" && (!item.data.event_kind || stateEventKind(item.data.event_kind) === "neutral") && !eventEmotion(item.data)) {
        if (neutralGroupCount > 0 && timelineDayKey(item.timestamp) !== timelineDayKey(latestNeutralTimestamp)) {
          flushNeutrals();
        }
        if (neutralGroupCount === 0) {
          latestNeutralTimestamp = item.timestamp;
          latestNeutralKey = item.key;
        }
        neutralGroupCount++;
      } else {
        flushNeutrals();
        filtered.push(item);
      }
    }
    flushNeutrals();
    return filtered;
  }, [events, reflections, filterOnlyImportant]);

  useEffect(() => {
    if (timelineRef.current && timelineItems.length > 0) {
      animateStaggerCards(timelineRef.current, ".state-timeline-item", 40);
    }
  }, [timelineItems.length, filterOnlyImportant]);

  const refresh = useCallback(async () => {
    try {
      const [next, eventData, reflectionData, reflectionSettings] = await Promise.all([getCharacterState(), getCharacterStateEvents(), getCharacterReflections(), getReflectionSettings()]);
      setState(next); setEvents(eventData.events); setReflections(reflectionData.reflections); setReflectionEnabled(reflectionSettings.enabled); setError(null);
    } catch (e) { setError(e instanceof Error ? e.message : "Состояние недоступно"); }
  }, []);

  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 10000); return () => window.clearInterval(timer); }, [refresh]);

  useEffect(() => {
    const latest = liveEvents[liveEvents.length - 1]?.type ?? "";
    if (latest.startsWith("character.state.") || latest.startsWith("character.reflection.")) void refresh();
  }, [liveEvents, refresh]);

  const toggleReflections = async (enabled: boolean) => {
    setReflectionEnabled(enabled);
    try {
      await updateReflectionSettings({ enabled, min_significance: 0.55 });
      notify.success("Состояние", enabled ? "Личные заметки включены." : "Личные заметки выключены.");
    } catch {
      setReflectionEnabled(!enabled);
      setError("Не удалось сохранить настройку личных заметок.");
      notify.error("Состояние", "Не удалось сохранить настройку личных заметок.");
    }
  };

  const handleRemoveReflectionClick = (e: React.MouseEvent<HTMLElement>, id: string) => {
    const itemEl = e.currentTarget.closest(".state-timeline-item") as HTMLElement | null;
    setPendingDeleteReflection({ id, el: itemEl });
  };

  const relationshipKeys = ["familiarity_label", "trust_label", "warmth_label", "tension_label", "playfulness_label"];

  return (
    <section className="state-dashboard" ref={containerRef} aria-label="Состояние Iris">
      {error && <div className="notice" role="status">{error}</div>}
      {state?.incognito && <div className="notice">Режим инкогнито: новое состояние и личные заметки не сохраняются.</div>}

      <div className="state-layout">
        <aside className="state-sidebar">
          {state ? (
            <>
              <div className="state-sidebar-panels" tabIndex={0} aria-label="Настроение и отношения">
              <div className="state-hero-card mood-card">
                <IrisMoodOrb
                    emotion={state.mood.primary_emotion}
                    strength={state.mood.expression_strength}
                    variant="surface"
                  />
                <div className="mood-visual">
                  <div className="mood-info">
                    <h2>{getMoodVisuals(state.mood.primary_emotion).labelRu}</h2>
                  </div>
                </div>
                {causeGroups.length > 0 && (
                  <div className="mood-causes">
                    <div className="mood-causes-heading"><h4>Что влияет на настроение</h4><span className="cause-group-total" title="Количество причин">{causeGroups.length}</span></div>
                    <ul id={causesId} ref={causeListRef} tabIndex={causesExpanded && causeGroups.length > 3 ? 0 : undefined} aria-label="Причины настроения">
                      {visibleCauses.map(cause => {
                        const CauseIcon = EVENT_ICONS[stateEventKind(cause.label)] ?? MessageCircle;
                        return (
                        <li key={cause.key}>
                          <CauseIcon className="cause-icon" size={16} aria-hidden="true" />
                          <div className="cause-copy"><strong title={cause.label}>{cause.label}</strong><span>{cause.status}</span></div>
                          {cause.count > 1 && <span className="cause-count" title="Количество событий">×{cause.count}</span>}
                        </li>
                      ); })}
                    </ul>
                    {causeGroups.length > 3 && (
                      <DisclosureTrigger materialKey="state.causes-toggle" className="cause-toggle" open={causesExpanded} aria-controls={causesId}
                        onClick={() => { if (causeListRef.current) causeListRef.current.scrollTop = 0; setCausesExpanded(value => !value); }}>
                        {causesExpanded ? "Свернуть" : <><span>Ещё причины</span><span className="cause-extra-count">{causeGroups.length - 3}</span></>}
                      </DisclosureTrigger>
                    )}
                  </div>
                )}
              </div>

              <div className="state-hero-card relationship-card">
                <div className="relationship-heading">
                <h3>Отношения</h3>
                </div>
                <dl className="relationship-facets">
                  {relationshipKeys.map(k => {
                    const level = relationshipLevel(k, state.relationship[k]);
                    return (
                    state.relationship[k] ? (
                      <div className="relationship-facet" key={k}>
                        <dt>{labels[k] || k}</dt>
                        <dd>
                          <span className="relationship-level" role={level === null ? "img" : "meter"} aria-label={labels[k] || k}
                            aria-valuemin={level === null ? undefined : 0} aria-valuemax={level === null ? undefined : 3} aria-valuenow={level ?? undefined}
                            aria-valuetext={level === null ? undefined : relationshipValue(k, state.relationship[k])}>
                            {level === null && <span className="relationship-level-unavailable">Оценка пока недоступна</span>}
                            {[0, 1, 2].map(step => <i key={step} data-active={level !== null && step < level} aria-hidden="true" />)}
                          </span>
                        </dd>
                      </div>
                    ) : null
                  ); })}
                </dl>
              </div>
              </div>

              <div className="state-sidebar-actions" role="group" aria-label="Сброс состояния">
                <MaterialButton materialKey={"state.button-1"}
                  className="secondary danger-button state-action-mood"
                  type="button"
                  disabled={busy}
                  onClick={(e) => {
                    animateButtonPress(e.currentTarget);
                    setPendingReset({
                      scope: "mood",
                      title: "Сбросить настроение?",
                      description: "Сбросить настроение Iris? Отношения и память останутся.",
                    });
                  }}
                >
                  <RotateCcw size={14} aria-hidden="true" /><span>Сбросить настроение</span>
                </MaterialButton>
                <MaterialButton materialKey={"state.button-2"}
                  className="secondary danger-button state-action-relationship"
                  type="button"
                  disabled={busy}
                  onClick={(e) => {
                    animateButtonPress(e.currentTarget);
                    setPendingReset({
                      scope: "relationship",
                      title: "Сбросить отношения?",
                      description: "Сбросить отношения Iris? Факты и личные заметки останутся.",
                    });
                  }}
                >
                  <RotateCcw size={14} aria-hidden="true" /><span>Сбросить отношения</span>
                </MaterialButton>
              </div>
            </>
          ) : (
            <LoadingRing label="Загружаю состояние…" />
          )}
        </aside>

        <main className="state-timeline-container">
          <div className="state-timeline-header">
            <h2>События и заметки</h2>
            <div className="timeline-header-controls">
              <SlidingSegments className="timeline-filter-pills" value={filterOnlyImportant} aria-label="Фильтр истории">
                <MaterialButton appearance="plain" materialKey={"state.button-3"}
                  type="button"
                  className={`timeline-filter-pill ${filterOnlyImportant ? "active" : ""}`} aria-pressed={filterOnlyImportant}
                  onClick={() => setFilterOnlyImportant(true)}
                >
                  Только важные
                </MaterialButton>
                <MaterialButton appearance="plain" materialKey={"state.button-4"}
                  type="button"
                  className={`timeline-filter-pill ${!filterOnlyImportant ? "active" : ""}`} aria-pressed={!filterOnlyImportant}
                  onClick={() => setFilterOnlyImportant(false)}
                >
                  Все ({events.length + reflections.length})
                </MaterialButton>
              </SlidingSegments>
              <label className="toggle-notes">
                <AppCheckbox checked={reflectionEnabled} onChange={(event) => void toggleReflections(event.target.checked)} />
                Личные заметки
              </label>
            </div>
          </div>

          {!reflectionEnabled && <p className="notice">Создание новых личных заметок отключено.</p>}

          <div className="state-timeline-scroll-shell">
          <div className="state-timeline-scroll" ref={timelineRef} tabIndex={0} aria-label="Лента событий">
          <div className="state-timeline" ref={timelineContentRef}>
            {timelineItems.length === 0 ? (
              <div className="empty-state">
                <IconInterfaceCalendarMark size={28} />
                <strong>История пока пуста.</strong>
              </div>
            ) : (
              timelineItems.map((item, index) => {
                const dayHeading = index === 0 || timelineDayKey(item.timestamp) !== timelineDayKey(timelineItems[index - 1].timestamp)
                  ? <h3 className="timeline-day">{formatTimelineDay(item.timestamp)}</h3> : null;
                if (item.type === "neutral_group") {
                  return (
                    <Fragment key={item.key}>{dayHeading}<article className="state-timeline-item type-neutral-group">
                      <div className="timeline-marker" aria-hidden="true" />
                      <MaterialButton appearance="plain" materialKey={item.key} type="button"
                        className="neutral-summary"
                        onClick={() => setFilterOnlyImportant(false)}
                      >
                        <span>Спокойный диалог <span className="neutral-count">· {item.count}</span></span>
                        <span className="neutral-expand-hint">Показать всё <ArrowRight size={13} aria-hidden="true" /></span>
                      </MaterialButton>
                    </article></Fragment>
                  );
                }
                if (item.type === "event") {
                  const ev = item.data;
                  const kind = stateEventKind(ev.event_kind);
                  const EventIcon = EVENT_ICONS[kind] ?? MessageCircle;
                  const emotion = eventEmotion(ev);
                  return (
                    <Fragment key={item.key}>{dayHeading}<article className="state-timeline-item type-event" data-emotion={emotion?.key}>
                      <div className="timeline-marker" aria-hidden="true">
                        <EventIcon size={18} />
                      </div>
                      <TimelineCard emotion={emotion} materialKey={item.key}>
                        <div className="timeline-meta">
                          <div className="timeline-event-heading">
                            <h4>{stateEventLabel(ev.event_kind)}</h4>
                            {emotion && <span className="timeline-emotion">{emotion.label}</span>}
                          </div>
                          <time dateTime={ev.created_at}>{formatTimelineTime(ev.created_at)}</time>
                        </div>
                        {ev.snippet && (
                          <blockquote className="timeline-quote" data-i18n-skip>
                            «{ev.snippet}»
                          </blockquote>
                        )}
                      </TimelineCard>
                    </article></Fragment>
                  );
                } else {
                  const r = item.data;
                  const emotion = timelineEmotion(r.primary_emotion);
                  return (
                    <Fragment key={item.key}>{dayHeading}<article className="state-timeline-item type-reflection" data-emotion={emotion?.key}>
                      <div className="timeline-marker" aria-hidden="true">
                        <IconInterfaceEditMagicWand size={18} />
                      </div>
                      <TimelineCard emotion={emotion} materialKey={item.key}>
                        <div className="timeline-meta">
                          <strong>Заметка Iris</strong>
                          <time dateTime={r.created_at}>{formatTimelineTime(r.created_at)}</time>
                        </div>
                        <h4 data-i18n-skip>{r.trigger_label}</h4>
                        <p data-i18n-skip>{r.text}</p>
                        <div className="timeline-footer">
                          <span className="reflection-emotion">{getMoodVisuals(r.primary_emotion).labelRu}</span>
                          <MaterialButton materialKey={["state.button-5", item.key].join(":")} className="text-button" onClick={(e) => handleRemoveReflectionClick(e, r.id)}>Удалить</MaterialButton>
                        </div>
                      </TimelineCard>
                    </article></Fragment>
                  );
                }
              })
            )}
          </div>
          </div>
          </div>
        </main>
      </div>

      <AppDialog
        open={Boolean(pendingReset)}
        title={pendingReset?.title ?? ""}
        description={pendingReset?.description}
        onClose={() => !busy && setPendingReset(null)}
        variant="danger"
      >
        <div className="dialog-actions">
          <MaterialButton materialKey={"state.button-6"}
            className="secondary"
            type="button"
            disabled={busy}
            onClick={() => setPendingReset(null)}
          >
            Отмена
          </MaterialButton>
          <MaterialButton materialKey={"state.button-7"}
            className="danger-button"
            type="button"
            disabled={busy}
            onClick={async () => {
              if (!pendingReset) return;
              setBusy(true);
              try {
                await resetCharacterState(pendingReset.scope);
                await refresh();
                notify.success("Состояние", "Состояние успешно сброшено.");
              } catch (e) {
                notify.error("Состояние", e instanceof Error ? e.message : "Не удалось сбросить состояние.");
              } finally {
                setBusy(false);
                setPendingReset(null);
              }
            }}
          >
            {busy ? "Сбрасываю…" : "Сбросить"}
          </MaterialButton>
        </div>
      </AppDialog>

      <AppDialog
        open={Boolean(pendingDeleteReflection)}
        title="Удалить заметку?"
        description="Удалить эту субъективную заметку Iris без возможности восстановления?"
        onClose={() => !busy && setPendingDeleteReflection(null)}
        variant="danger"
      >
        <div className="dialog-actions">
          <MaterialButton materialKey={"state.button-8"}
            className="secondary"
            type="button"
            disabled={busy}
            onClick={() => setPendingDeleteReflection(null)}
          >
            Отмена
          </MaterialButton>
          <MaterialButton materialKey={"state.button-9"}
            className="danger-button"
            type="button"
            disabled={busy}
            onClick={async () => {
              if (!pendingDeleteReflection) return;
              setBusy(true);
              const { id, el } = pendingDeleteReflection;
              try {
                if (el) {
                  animateCardRemove(el, async () => {
                    await deleteCharacterReflection(id);
                    await refresh();
                    notify.info("Состояние", "Заметка удалена.");
                  });
                } else {
                  await deleteCharacterReflection(id);
                  await refresh();
                  notify.info("Состояние", "Заметка удалена.");
                }
              } catch (e) {
                notify.error("Состояние", e instanceof Error ? e.message : "Не удалось удалить заметку.");
              } finally {
                setBusy(false);
                setPendingDeleteReflection(null);
              }
            }}
          >
            {busy ? "Удаляю…" : "Удалить"}
          </MaterialButton>
        </div>
      </AppDialog>
    </section>
  );
}
