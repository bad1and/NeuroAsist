import { useCallback, useEffect, useRef, useState, useMemo } from "react";
import { deleteCharacterReflection, getCharacterReflections, getCharacterState, getCharacterStateEvents, getReflectionSettings, resetCharacterState, updateReflectionSettings } from "./api";
import type { CharacterReflection, CharacterStateEvent, CharacterStateView } from "./types";
import { interfaceIntlLocale } from "./i18n";
import { animateButtonPress, animateCardRemove, animatePageEnter, animateStaggerCards, useAnimeScope } from "./animations";
import { IrisMoodOrb } from "./components/IrisMoodOrb";
import { getMoodVisuals, getStrengthLabel } from './mood-visuals';
import { IconInterfaceSettingGaugeDashboard1, IconInterfaceCalendarMark, IconInterfaceEditMagicWand } from "./CustomIcons";
import { AppDialog } from "./components/AppDialog";
import { notify } from "./notifications";

const labels: Record<string, string> = {
  primary_emotion: "Главная эмоция", expression_strength: "Выразительность", secondary_emotions: "Вторичные эмоции",
  familiarity_label: "Знакомство", trust_label: "Доверие", warmth_label: "Теплота", tension_label: "Напряжение", playfulness_label: "Игривость",
  current_dynamic: "Текущая динамика", unresolved_cause: "Нерешённая причина",
};
const show = (value: unknown) => Array.isArray(value) ? value.join(", ") || "нет" : String(value ?? "—");

function formatTimelineDate(dateStr: string) {
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return dateStr;
  const now = new Date();
  
  const isToday = date.getDate() === now.getDate() && date.getMonth() === now.getMonth() && date.getFullYear() === now.getFullYear();
  
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const isYesterday = date.getDate() === yesterday.getDate() && date.getMonth() === yesterday.getMonth() && date.getFullYear() === yesterday.getFullYear();
  
  const time = date.toLocaleTimeString(interfaceIntlLocale(), { hour: '2-digit', minute: '2-digit' });
  
  if (isToday) return interfaceIntlLocale() === "en-US" ? `Today at ${time}` : `Сегодня в ${time}`;
  if (isYesterday) return interfaceIntlLocale() === "en-US" ? `Yesterday at ${time}` : `Вчера в ${time}`;
  
  const locale = interfaceIntlLocale();
  return date
    .toLocaleDateString(locale, { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })
    .replace(',', locale === "en-US" ? ' at' : ' в');
}

const EVENT_KIND_META: Record<string, { label: string; markerClass: string; isImportant?: boolean }> = {
  insult: { label: "Резкость / Защита границ", markerClass: "marker-rose", isImportant: true },
  shared_success: { label: "Общий успех", markerClass: "marker-gold", isImportant: true },
  "shared success": { label: "Общий успех", markerClass: "marker-gold", isImportant: true },
  important_news: { label: "Яркая новость", markerClass: "marker-sky", isImportant: true },
  "important news": { label: "Яркая новость", markerClass: "marker-sky", isImportant: true },
  apology: { label: "Примирение", markerClass: "marker-green", isImportant: true },
  broken_promise: { label: "Нарушенное обещание", markerClass: "marker-rose", isImportant: true },
  promise_made: { label: "Обещание", markerClass: "marker-indigo", isImportant: true },
  teasing: { label: "Шутка / Подкол", markerClass: "marker-purple", isImportant: true },
  praise: { label: "Похвала", markerClass: "marker-gold", isImportant: true },
  support: { label: "Поддержка", markerClass: "marker-teal", isImportant: true },
  disagreement: { label: "Разногласие", markerClass: "marker-orange", isImportant: true },
  vulnerability: { label: "Откровенность", markerClass: "marker-pink", isImportant: true },
  neutral: { label: "Спокойная беседа", markerClass: "marker-neutral", isImportant: false },
};

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

  const containerRef = useAnimeScope<HTMLElement>((scope, root) => {
    animatePageEnter(root);
  }, []);

  const [filterOnlyImportant, setFilterOnlyImportant] = useState(true);
  const timelineRef = useRef<HTMLDivElement | null>(null);

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

    const flushNeutrals = () => {
      if (neutralGroupCount > 0) {
        filtered.push({
          type: "neutral_group",
          timestamp: latestNeutralTimestamp,
          key: `neutrals-${latestNeutralTimestamp}-${neutralGroupCount}`,
          count: neutralGroupCount,
        });
        neutralGroupCount = 0;
      }
    };

    for (const item of rawItems) {
      if (item.type === "event" && (item.data.event_kind === "neutral" || !item.data.event_kind)) {
        neutralGroupCount++;
        if (latestNeutralTimestamp === 0) {
          latestNeutralTimestamp = item.timestamp;
        }
      } else {
        flushNeutrals();
        latestNeutralTimestamp = 0;
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
  }, [timelineItems]);

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
              <div className="state-hero-card mood-card">
                <div className="mood-visual">
                  <div className="mood-metaball-container">
                    <IrisMoodOrb
                      emotion={state.mood.primary_emotion}
                      strength={state.mood.expression_strength}
                      size={80}
                    />
                  </div>
                  <div className="mood-info">
                    <h2>{getMoodVisuals(state.mood.primary_emotion).labelRu}</h2>
                    <span className="mood-strength">{getStrengthLabel(state.mood.expression_strength)}</span>
                  </div>
                </div>
                {state.causes.length > 0 && (
                  <div className="mood-causes">
                    <h4>Причины:</h4>
                    <ul>
                      {state.causes.map((c, i) => (
                        <li key={i}><strong>{c.label}</strong> <span>{c.status}</span></li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              <div className="state-hero-card relationship-card">
                <h3>Отношения</h3>
                <div className="relationship-metrics">
                  {relationshipKeys.map(k => (
                    state.relationship[k] ? (
                      <div className="metric-row" key={k}>
                        <span className="metric-label">{labels[k] || k}</span>
                        <span className="metric-value">{show(state.relationship[k])}</span>
                      </div>
                    ) : null
                  ))}
                </div>
                {Boolean(state.relationship.current_dynamic) && (
                  <div className="relationship-dynamic">
                    <h4>Динамика</h4>
                    <p>{String(state.relationship.current_dynamic)}</p>
                  </div>
                )}
              </div>

              <div className="state-sidebar-actions">
                <button
                  className="state-action-mood"
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
                  Сбросить настроение
                </button>
                <button
                  className="state-action-relationship"
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
                  Сбросить отношения
                </button>
              </div>
            </>
          ) : (
            <div className="state-loading">Загрузка состояния...</div>
          )}
        </aside>

        <main className="state-timeline-container" ref={timelineRef}>
          <div className="state-timeline-header">
            <h2>Живая история</h2>
            <div className="timeline-header-controls">
              <div className="timeline-filter-pills">
                <button
                  type="button"
                  className={`timeline-filter-pill ${filterOnlyImportant ? "active" : ""}`}
                  onClick={() => setFilterOnlyImportant(true)}
                >
                  Только важные
                </button>
                <button
                  type="button"
                  className={`timeline-filter-pill ${!filterOnlyImportant ? "active" : ""}`}
                  onClick={() => setFilterOnlyImportant(false)}
                >
                  Все ({events.length + reflections.length})
                </button>
              </div>
              <label className="toggle-notes">
                <div className="custom-checkbox-wrapper">
                  <input type="checkbox" checked={reflectionEnabled} onChange={(event) => void toggleReflections(event.target.checked)}/>
                  <span className="checkbox-indicator"></span>
                </div>
                Личные заметки
              </label>
            </div>
          </div>

          {!reflectionEnabled && <p className="notice">Создание новых личных заметок отключено.</p>}

          <div className="state-timeline">
            {timelineItems.length === 0 ? (
              <div className="empty-state">
                <IconInterfaceCalendarMark size={28} />
                <strong>История пока пуста.</strong>
              </div>
            ) : (
              timelineItems.map((item) => {
                if (item.type === "neutral_group") {
                  return (
                    <article className="state-timeline-item type-neutral-group" key={item.key}>
                      <div className="timeline-marker" />
                      <div
                        className="timeline-content card-glass neutral-summary"
                        onClick={() => setFilterOnlyImportant(false)}
                        title="Нажмите, чтобы развернуть все сообщения"
                      >
                        <span>Спокойный диалог ({item.count} {item.count === 1 ? "реплика" : item.count < 5 ? "реплики" : "реплик"})</span>
                        <span className="neutral-expand-hint">Показать всё →</span>
                      </div>
                    </article>
                  );
                }
                if (item.type === "event") {
                  const ev = item.data;
                  const meta = EVENT_KIND_META[ev.event_kind] || {
                    label: ev.event_kind.split("_").join(" "),
                    markerClass: "marker-neutral",
                  };
                  return (
                    <article className={`state-timeline-item type-event ${meta.markerClass}`} key={item.key}>
                      <div className="timeline-marker">
                        <IconInterfaceSettingGaugeDashboard1 size={14} />
                      </div>
                      <div className="timeline-content card-glass">
                        <div className="timeline-meta">
                          <strong>Событие</strong>
                          <time>{formatTimelineDate(ev.created_at)}</time>
                        </div>
                        <h4 data-i18n-skip>{meta.label}</h4>
                        {ev.snippet && (
                          <blockquote className="timeline-quote" data-i18n-skip>
                            «{ev.snippet}»
                          </blockquote>
                        )}
                      </div>
                    </article>
                  );
                } else {
                  const r = item.data;
                  return (
                    <article className="state-timeline-item type-reflection" key={item.key}>
                      <div className="timeline-marker">
                        <IconInterfaceEditMagicWand size={14} />
                      </div>
                      <div className="timeline-content card-glass">
                        <div className="timeline-meta">
                          <strong>Заметка Iris</strong>
                          <time>{formatTimelineDate(r.created_at)}</time>
                        </div>
                        <h4 data-i18n-skip>{r.trigger_label}</h4>
                        <p data-i18n-skip>{r.text}</p>
                        <div className="timeline-footer">
                          <span className="reflection-emotion">{r.primary_emotion}</span>
                          <button className="text-button" onClick={(e) => handleRemoveReflectionClick(e, r.id)}>Удалить</button>
                        </div>
                      </div>
                    </article>
                  );
                }
              })
            )}
          </div>
        </main>
      </div>

      <AppDialog
        open={Boolean(pendingReset)}
        title={pendingReset?.title ?? ""}
        description={pendingReset?.description}
        onClose={() => !busy && setPendingReset(null)}
      >
        <div className="dialog-actions">
          <button
            className="secondary"
            type="button"
            disabled={busy}
            onClick={() => setPendingReset(null)}
          >
            Отмена
          </button>
          <button
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
          </button>
        </div>
      </AppDialog>

      <AppDialog
        open={Boolean(pendingDeleteReflection)}
        title="Удалить заметку?"
        description="Удалить эту субъективную заметку Iris без возможности восстановления?"
        onClose={() => !busy && setPendingDeleteReflection(null)}
      >
        <div className="dialog-actions">
          <button
            className="secondary"
            type="button"
            disabled={busy}
            onClick={() => setPendingDeleteReflection(null)}
          >
            Отмена
          </button>
          <button
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
          </button>
        </div>
      </AppDialog>
    </section>
  );
}
