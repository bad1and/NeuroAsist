import type { BackendEvent } from "../types";

const LABELS: Record<string, string> = {
  searching: "Ищу…", reading: "Читаю источники…", refining: "Уточняю запрос…",
};

export function RetrievalProgress({ events, sessionId }: { events: BackendEvent[]; sessionId: string | null }) {
  const relevant = events.filter((e) => e.type === "retrieval.progress" && e.metadata.session_id === sessionId)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
  const starts = new Map<string, string>();
  for (const event of relevant) {
    const turn = String(event.metadata.turn_id ?? "");
    if (event.metadata.phase !== "finished" && !starts.has(turn)) starts.set(turn, event.created_at);
  }
  const turn = [...starts.entries()].sort((a, b) => b[1].localeCompare(a[1]))[0]?.[0];
  const turnEvents = relevant.filter((e) => String(e.metadata.turn_id ?? "") === turn);
  const latest = turnEvents[turnEvents.length - 1];
  const label = latest && LABELS[String(latest.metadata.phase)];
  return label ? <div role="status" aria-live="polite" className="memory-empty-note">{label}</div> : null;
}
