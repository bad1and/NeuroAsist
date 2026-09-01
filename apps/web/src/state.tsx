import { useCallback, useEffect, useRef, useState, useMemo } from "react";
import { deleteCharacterReflection, getCharacterReflections, getCharacterState, getCharacterStateEvents, getReflectionSettings, resetCharacterState, updateReflectionSettings } from "./api";
import type { CharacterReflection, CharacterStateEvent, CharacterStateView } from "./types";
import { interfaceIntlLocale } from "./i18n";
import { animateButtonPress, animateCardRemove, animatePageEnter, animateStaggerCards, useAnimeScope } from "./animations";
import { Metaballs } from '@paper-design/shaders-react';
import { getMoodVisuals, getStrengthLabel } from './mood-visuals';
import { IconInterfaceSettingGaugeDashboard1, IconInterfaceCalendarMark, IconInterfaceEditMagicWand } from "./CustomIcons";

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
  
  if (isToday) return `Сегодня в ${time}`;
  if (isYesterday) return `Вчера в ${time}`;
  
  return date.toLocaleDateString(interfaceIntlLocale(), { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' }).replace(',', ' в');
}

type TimelineItem =
  | { type: "event"; timestamp: number; key: string; data: CharacterStateEvent }
  | { type: "reflection"; timestamp: number; key: string; data: CharacterReflection };

export function StatePage({ events: liveEvents = [] }: { events?: Array<{ type: string }> }) {
  const [state, setState] = useState<CharacterStateView | null>(null);
  const [events, setEvents] = useState<CharacterStateEvent[]>([]);
  const [reflections, setReflections] = useState<CharacterReflection[]>([]);
  const [reflectionEnabled, setReflectionEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const containerRef = useAnimeScope<HTMLElement>((scope, root) => {
    animatePageEnter(root);
  }, []);

  const timelineRef = useRef<HTMLDivElement | null>(null);

  const timelineItems = useMemo(() => {
    const items: TimelineItem[] = [];
    for (const e of events) {
      items.push({ type: "event", timestamp: new Date(e.created_at).getTime(), key: "evt-" + e.id, data: e });
    }
    for (const r of reflections) {
      items.push({ type: "reflection", timestamp: new Date(r.created_at).getTime(), key: "ref-" + r.id, data: r });
    }
    return items.sort((a, b) => b.timestamp - a.timestamp);
  }, [events, reflections]);

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

  const reset = async (scope: "mood" | "relationship") => {
    const message = scope === "mood" ? "Сбросить настроение Iris? Отношения и память останутся." : "Сбросить отношения Iris? Факты и личные заметки останутся.";
    if (!window.confirm(message)) return;
    await resetCharacterState(scope); await refresh();
  };

  const toggleReflections = async (enabled: boolean) => { setReflectionEnabled(enabled); try { await updateReflectionSettings({ enabled, min_significance: .55 }); } catch { setReflectionEnabled(!enabled); setError("Не удалось сохранить настройку личных заметок."); } };

  const removeReflection = async (e: React.MouseEvent<HTMLElement>, id: string) => {
    if (!window.confirm("Удалить эту субъективную заметку Iris?")) return;
    const itemEl = e.currentTarget.closest(".state-timeline-item") as HTMLElement | null;
    if (itemEl) {
      animateCardRemove(itemEl, async () => {
        await deleteCharacterReflection(id);
        await refresh();
      });
    } else {
      await deleteCharacterReflection(id);
      await refresh();
    }
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
              <div className="state-hero-card mood-card" style={{ padding: '24px', position: 'relative', overflow: 'hidden' }}>
                <div className="mood-visual" style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
                  <div className="mood-metaball-container" style={{ width: 80, height: 80, flexShrink: 0, position: 'relative' }}>
                    {(() => {
                      const visuals = getMoodVisuals(state.mood.primary_emotion);
                      return (
                        <div style={{ 
                          position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%) scale(0.22)', 
                          width: 1280, height: 720,
                          pointerEvents: 'none',
                          mixBlendMode: 'screen'
                        }}>
                          <Metaballs
                            width={1280}
                            height={720}
                            colors={visuals.colors}
                            colorBack="#000000"
                            count={20}
                            size={1}
                            speed={visuals.speed}
                            scale={0.64}
                          />
                        </div>
                      );
                    })()}
                  </div>
                  <div className="mood-info" style={{ zIndex: 1 }}>
                    <h2 style={{ margin: 0, fontSize: '20px', fontWeight: 600 }}>{getMoodVisuals(state.mood.primary_emotion).labelRu}</h2>
                    <span className="mood-strength" style={{ color: 'var(--color-text-muted, #888)', fontSize: '14px', marginTop: '4px', display: 'inline-block' }}>{getStrengthLabel(state.mood.expression_strength)}</span>
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
                <button onClick={(e) => { animateButtonPress(e.currentTarget); void reset("mood"); }}>Сбросить настроение</button>
                <button className="is-danger" onClick={(e) => { animateButtonPress(e.currentTarget); void reset("relationship"); }}>Сбросить отношения</button>
              </div>
            </>
          ) : (
            <div className="state-loading">Загрузка состояния...</div>
          )}
        </aside>

        <main className="state-timeline-container" ref={timelineRef}>
          <div className="state-timeline-header">
            <h2>Живая история</h2>
            <label className="toggle-notes">
              <div className="custom-checkbox-wrapper">
                <input type="checkbox" checked={reflectionEnabled} onChange={(event) => void toggleReflections(event.target.checked)}/>
                <span className="checkbox-indicator"></span>
              </div>
              Личные заметки
            </label>
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
                if (item.type === "event") {
                  const ev = item.data;
                  return (
                    <article className="state-timeline-item type-event" key={item.key}>
                      <div className="timeline-marker">
                        <IconInterfaceSettingGaugeDashboard1 size={14} />
                      </div>
                      <div className="timeline-content card-glass">
                        <div className="timeline-meta">
                          <strong>Событие</strong>
                          <time>{formatTimelineDate(ev.created_at)}</time>
                        </div>
                        <h4 data-i18n-skip>{ev.event_kind.split("_").join(" ")}</h4>
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
                          <button className="text-button" onClick={(e) => void removeReflection(e, r.id)}>Удалить</button>
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
    </section>
  );
}
