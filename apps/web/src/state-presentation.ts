import type { CharacterStateEvent, CharacterStateView } from "./types";
import { MOOD_MAP } from "./mood-visuals";

export function timelineEmotion(emotion: string) {
  const visual = Object.prototype.hasOwnProperty.call(MOOD_MAP, emotion) ? MOOD_MAP[emotion] : undefined;
  if (!visual || emotion === "neutral") return null;
  // Timeline surfaces use the button palette, not the orb's luminous shader colours.
  const tone = ["anger", "angry", "annoyed", "irritation", "hurt", "embarrassed", "embarrassment"].includes(emotion) ? "danger"
    : ["fear", "anxiety", "concerned", "confusion"].includes(emotion) ? "warning"
    : ["joy", "happy", "amusement", "grateful"].includes(emotion) ? "success"
    : ["sadness", "sad", "boredom", "fatigue", "sleepy"].includes(emotion) ? "quiet"
    : "accent";
  return { key: emotion, label: visual.labelRu, tone };
}

/** Negative impulses describe an emotion easing, not a new emotional event. */
export function eventEmotion(event: CharacterStateEvent) {
  const impulses = event.delta?.emotion_impulses;
  if (!impulses || typeof impulses !== "object" || Array.isArray(impulses)) return null;
  let strongest = 0;
  let emotion: ReturnType<typeof timelineEmotion> = null;
  for (const [key, value] of Object.entries(impulses)) {
    const candidate = timelineEmotion(key);
    if (candidate && typeof value === "number" && Number.isFinite(value) && value > strongest) {
      emotion = candidate;
      strongest = value;
    }
  }
  return emotion;
}

export const STATE_EVENT_LABELS: Record<string, string> = {
  insult: "Резкость / Защита границ",
  shared_success: "Общий успех",
  important_news: "Яркая новость",
  apology: "Примирение",
  broken_promise: "Нарушенное обещание",
  promise_made: "Обещание",
  fulfilled_promise: "Выполненное обещание",
  teasing: "Шутка / Подкол",
  praise: "Похвала",
  support: "Поддержка",
  disagreement: "Разногласие",
  vulnerability: "Откровенность",
  rejection: "Дистанция",
  affection: "Тёплое общение",
  user_frustration: "Переживания пользователя",
  iris_mistake_corrected: "Исправление ошибки Iris",
  important_negative_event: "Трудный момент",
  interruption: "Прерывание разговора",
  neutral: "Спокойная беседа",
};

const aliases: Record<string, string> = {
  promise: "promise_made",
  promise_fulfilled: "fulfilled_promise",
  "грубость / оскорбление": "insult",
  "подкол / шутка": "teasing",
  переживание: "user_frustration",
};

export function stateEventKind(value: string): string {
  const normalized = value.trim().toLowerCase().replace(/\s+/g, " ");
  const translatedKind = Object.keys(STATE_EVENT_LABELS).find(key => STATE_EVENT_LABELS[key].toLowerCase() === normalized);
  return aliases[normalized] ?? translatedKind ?? normalized.replace(/ /g, "_");
}

export function stateEventLabel(value: string): string {
  return STATE_EVENT_LABELS[stateEventKind(value)]
    // Keep descriptive labels supplied by Iris; hide unknown internal codes.
    ?? (/[а-яё]/i.test(value) ? value.trim() : "Другой эпизод");
}

const causeStatuses: Record<string, { key: string; label: string }> = {
  active: { key: "active", label: "Влияет сейчас" },
  активен: { key: "active", label: "Влияет сейчас" },
  fading: { key: "fading", label: "Затихает" },
  resolved: { key: "resolved", label: "Разрешено" },
  expired: { key: "expired", label: "Больше не влияет" },
};

export type MoodCauseGroup = { key: string; label: string; status: string; count: number };

/** Group only the public presentation; canonical causes remain independent. */
export function groupMoodCauses(causes: CharacterStateView["causes"]): MoodCauseGroup[] {
  const groups = new Map<string, MoodCauseGroup>();
  for (const cause of causes) {
    const kind = stateEventKind(cause.label);
    const status = causeStatuses[cause.status.trim().toLowerCase()] ?? { key: cause.status, label: "Состояние уточняется" };
    const key = `${kind}:${status.key}`;
    const group = groups.get(key);
    if (group) group.count++;
    else groups.set(key, { key, label: stateEventLabel(cause.label), status: status.label, count: 1 });
  }
  return [...groups.values()];
}

export function relationshipValue(key: string, value: unknown): string {
  const text = String(value ?? "—");
  if (text !== "умеренный") return text;
  return key === "warmth_label" || key === "playfulness_label" ? "умеренная" : "умеренное";
}

/** Three categorical steps, derived from public labels rather than percentages. */
export function relationshipLevel(key: string, value: unknown): number | null {
  const label = String(value ?? "").trim().toLowerCase();
  const levels: Record<string, Record<string, number>> = {
    familiarity_label: { начальное: 1, умеренный: 2, умеренное: 2, хорошее: 3 },
    trust_label: { осторожное: 1, умеренный: 2, умеренное: 2, высокое: 3 },
    warmth_label: { сдержанная: 1, умеренный: 2, умеренная: 2, тёплая: 3 },
    tension_label: { нет: 0, есть: 2, высокое: 3 },
    playfulness_label: { низкая: 1, умеренный: 2, умеренная: 2, высокая: 3 },
  };
  return levels[key]?.[label] ?? null;
}
