import { useCallback, useEffect, useRef, useState } from "react";
import { deleteCharacterReflection, getCharacterReflections, getCharacterState, getCharacterStateEvents, getReflectionSettings, resetCharacterState, updateReflectionSettings } from "./api";
import type { CharacterReflection, CharacterStateEvent, CharacterStateView } from "./types";
import { interfaceIntlLocale } from "./i18n";
import { animateButtonPress, animateCardRemove, animatePageEnter, animateStaggerCards, useAnimeScope } from "./animations";

const labels: Record<string, string> = {
  primary_emotion: "Главная эмоция", expression_strength: "Выразительность", secondary_emotions: "Вторичные эмоции",
  familiarity_label: "Знакомство", trust_label: "Доверие", warmth_label: "Теплота", tension_label: "Напряжение", playfulness_label: "Игривость",
  current_dynamic: "Текущая динамика", unresolved_cause: "Нерешённая причина",
};
const show = (value: unknown) => Array.isArray(value) ? value.join(", ") || "нет" : String(value ?? "—");

export function StatePage({ events: liveEvents = [] }: { events?: Array<{ type: string }> }) {
  const [state, setState] = useState<CharacterStateView | null>(null);
  const [events, setEvents] = useState<CharacterStateEvent[]>([]);
  const [reflections, setReflections] = useState<CharacterReflection[]>([]);
  const [reflectionEnabled, setReflectionEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const containerRef = useAnimeScope<HTMLElement>((scope, root) => {
    animatePageEnter(root);
  }, []);

  const contentRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (contentRef.current && state) {
      animateStaggerCards(contentRef.current, ".state-card, .state-list li", 40);
    }
  }, [state, events, reflections]);

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
    const itemEl = e.currentTarget.closest("li") as HTMLElement | null;
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
  return <section className="state-page" ref={containerRef} aria-label="Состояние Iris">
    <header className="page-header"><div><span className="eyebrow">Внутренняя жизнь</span><h1>Состояние Iris</h1><p>{state ? `Сейчас: ${state.mood.primary_emotion}` : "Загружаем состояние…"}</p></div><button className="secondary" onClick={(e) => { animateButtonPress(e.currentTarget); void refresh(); }}>Обновить</button></header>
    {error && <div className="notice" role="status">{error}</div>}
    {state?.incognito && <div className="notice">Режим инкогнито: новое состояние и личные заметки не сохраняются.</div>}
    <div ref={contentRef}>
      {state && <><div className="state-grid"><StateCard title="Настроение" data={state.mood} keys={["primary_emotion", "expression_strength", "secondary_emotions"]}/><StateCard title="Отношения" data={state.relationship} keys={["familiarity_label", "trust_label", "warmth_label", "tension_label", "playfulness_label"]}/><StateCard title="Динамика" data={state.relationship} keys={["current_dynamic", "unresolved_cause"]}/></div>
        <section className="state-card"><h2>Причины настроения</h2>{state.causes.length ? <ul className="state-list">{state.causes.map((cause, index) => <li key={`${cause.label}-${index}`}><strong>{cause.label}</strong><span>{cause.status}</span></li>)}</ul> : <p>Активных причин сейчас нет.</p>}</section>
        <div className="state-actions"><button className="secondary" onClick={(e) => { animateButtonPress(e.currentTarget); void reset("mood"); }}>Сбросить настроение</button><button className="secondary danger-button" onClick={(e) => { animateButtonPress(e.currentTarget); void reset("relationship"); }}>Сбросить отношения</button></div></>}
      <section className="state-card"><h2>Недавние события</h2>{events.length ? <ul className="state-list">{events.map(event => <li key={event.id}><strong data-i18n-skip>{event.event_kind.split("_").join(" ")}</strong><span>{new Date(event.created_at).toLocaleString(interfaceIntlLocale())}</span></li>)}</ul> : <p>Значимых событий пока нет.</p>}</section>
      <section className="state-card"><div className="panel-header"><div><h2>Личные заметки Iris</h2><span>Субъективные внутренние заметки Iris, а не факты о вас.</span></div><label className="settings-checkbox"><input type="checkbox" checked={reflectionEnabled} onChange={(event) => void toggleReflections(event.target.checked)}/>Создавать</label></div>{!reflectionEnabled ? <p>Создание новых личных заметок отключено.</p> : reflections.length ? <ul className="state-list">{reflections.map(item => <li key={item.id}><div><strong data-i18n-skip>{item.trigger_label}</strong><span data-i18n-skip>{item.text}</span><small>{item.primary_emotion} · {new Date(item.created_at).toLocaleString(interfaceIntlLocale())}</small></div><button className="text-button" onClick={(e) => void removeReflection(e, item.id)}>Удалить</button></li>)}</ul> : <p>Пока нет субъективных заметок Iris.</p>}</section>
    </div>
  </section>;
}

function StateCard({ title, data, keys }: { title: string; data: Record<string, unknown>; keys: string[] }) {
  return <section className="state-card"><h2>{title}</h2><dl>{keys.filter(key => data[key] !== undefined && data[key] !== null).map(key => <div key={key}><dt>{labels[key] ?? key}</dt><dd>{show(data[key])}</dd></div>)}</dl></section>;
}
