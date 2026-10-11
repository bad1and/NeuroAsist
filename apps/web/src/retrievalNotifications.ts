import { notify } from "./notifications";
import type { BackendEvent } from "./types";

const labels: Record<string, string> = {
  searching: "Проверяет информацию", reading: "Читает источники", refining: "Уточняет запрос",
};
const outcomes: Record<string, string> = {
  sufficient: "Проверка завершена", partial: "Найдена часть информации", none: "Подтверждения не найдены",
  ok: "Проверка завершена", empty: "Подходящие сведения не найдены", timeout: "Проверка заняла слишком много времени",
  blocked: "Источники сейчас недоступны", error: "Не удалось завершить проверку", cancelled: "Проверка отменена",
};
type SearchNotice = { id: string; sequence: number; startedAt: string; closed: boolean; shown: boolean; phases: string[] };

/** Consumes live events only, not the historic event list returned on reconnect. */
export class RetrievalNotifications {
  private enabled = false;
  private turns = new Map<string, SearchNotice>();
  private active = new Map<string, string>();
  private acceptedSequences = new Map<string, number>();

  setEnabled(enabled: boolean) {
    this.enabled = enabled;
    if (!enabled) this.disconnect();
  }

  disconnect() {
    for (const state of this.turns.values()) {
      if (state.shown) notify.dismiss(state.id);
      state.closed = true;
    }
    this.active.clear();
  }

  consume(event: BackendEvent) {
    const m = event.metadata;
    const session = String(m.session_id ?? "");
    const turnSequence = Number(m.turn_sequence ?? 0);
    if (event.type === "turn.accepted" && Number.isFinite(turnSequence)) {
      this.acceptedSequences.set(session, Math.max(turnSequence, this.acceptedSequences.get(session) ?? 0));
    }
    if (["turn.accepted", "conversation.cancelled", "session.ended"].includes(event.type)) {
      const key = this.active.get(session);
      const state = key ? this.turns.get(key) : undefined;
      if (state) { notify.dismiss(state.id); state.closed = true; }
      this.active.delete(session);
      return;
    }
    if (event.type !== "retrieval.progress" || !session || !m.turn_id) return;
    // Voice and typed generation counters have different owners; durable order is shared.
    if (turnSequence > 0 && turnSequence < (this.acceptedSequences.get(session) ?? 0)) return;
    const key = `${session}:${m.turn_id}:${m.generation ?? ""}`;
    const sequence = Number(m.sequence ?? 0);
    const phase = String(m.phase ?? "");
    const terminal = phase === "finished";
    let state = this.turns.get(key);
    const isNew = !state;
    if (state && (state.closed || sequence <= state.sequence)) return;
    if (!state) {
      // A terminal event or an old replay must not flash a new card.
      if (terminal || !labels[phase] || Date.now() - Date.parse(event.created_at) > 30_000) return;
      const previousKey = this.active.get(session);
      const previous = previousKey ? this.turns.get(previousKey) : undefined;
      if (previous && event.created_at < previous.startedAt) return;
      if (previous) { notify.dismiss(previous.id); previous.closed = true; }
      state = { id: `retrieval:${key}`, sequence: -1, startedAt: event.created_at, closed: false, shown: this.enabled, phases: [] };
      this.turns.set(key, state);
      this.active.set(session, key);
      while (this.turns.size > 256) this.turns.delete(this.turns.keys().next().value!);
    }
    state.sequence = sequence;
    const outcome = m.status === "cancelled" || m.status === "error" ? m.status : m.evidence_status || m.status;
    const label = terminal ? outcomes[String(outcome)] ?? "Проверка завершена" : labels[phase];
    if (!label) return;
    if (state.phases[state.phases.length - 1] !== label) state.phases.push(label);
    const sources = Array.isArray(m.sources) ? m.sources as { title?: string; url?: string }[] : [];
    const details = [
      m.query ? `Запрос: ${String(m.query)}` : "",
      `Этапы: ${state.phases.join(" → ")}`,
      m.provider ? `Источники поиска: ${String(m.provider)}` : "",
      typeof m.latency_ms === "number" ? `Время: ${(m.latency_ms / 1000).toFixed(1)} с` : "",
      ...sources.slice(0, 3).map(source => `${source.title ?? "Источник"}\n${source.url ?? ""}`),
    ].filter(Boolean).join("\n");
    if (state.shown) {
      const patch = { message: label, details, duration: terminal ? 4500 : "persistent" as const };
      if (isNew && !terminal) {
        notify.info("Поиск Ирис", label, { id: state.id, details, duration: "persistent" });
      } else {
        notify.update(state.id, patch);
      }
    }
    if (terminal) { state.closed = true; this.active.delete(session); }
  }
}
