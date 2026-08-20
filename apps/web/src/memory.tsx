import { useEffect, useRef, useState } from "react";
import { Archive, Brain, CheckCircle2, CircleHelp, ListChecks, MoreHorizontal, Pin, Search, Tag, Trash2 } from "lucide-react";

import {
  deleteMemory, getMemories, getMemoryAudit, getMemoryCommitments,
  getMemoryConflicts, getMemoryDiagnostics, getMemoryTopics,
} from "./api";
import type { MemoryAuditItem, MemoryCommitment, MemoryDiagnostics, MemoryItem, MemoryStatus, MemoryTopic } from "./types";
import { animateButtonPress, animatePageEnter, animateStaggerCards, useAnimeScope } from "./animations";

type MemorySection = "all" | "active" | "topics" | "commitments" | "archive" | "diagnostics";

const STATUS_LABELS: Record<MemoryStatus | "all", string> = {
  all: "Все", active: "Сохранённые", superseded: "Заменённые", deleted: "Удалённые", rejected: "Отклонённые", expired: "Истёкшие",
};

const MEMORY_SECTIONS: Array<{ id: MemorySection; label: string; icon: typeof Brain }> = [
  { id: "all", label: "Текущие", icon: Brain },
  { id: "active", label: "Сохранённые", icon: CheckCircle2 },
  { id: "topics", label: "Темы", icon: Tag },
  { id: "commitments", label: "Планы и обещания", icon: ListChecks },
  { id: "archive", label: "Архив", icon: Archive },
  { id: "diagnostics", label: "Диагностика", icon: CircleHelp },
];

const MEMORY_LABELS: Record<string, string> = {
  "user.name": "Имя пользователя",
  "assistant.developer": "Разработчик Iris",
  "assistant.developer_count": "Количество разработчиков Iris",
  "user.likes_category": "Любимый жанр",
  "user.likes_game": "Любимая игра",
  "user.preference": "Предпочтение",
  "user.note": "Заметка",
  "user.relationship.friend": "Друг",
  "user.game_detail": "Деталь игры",
  "user.current_mood": "Текущее настроение",
  "user.current_activity": "Текущее занятие",
  "user.current_goal": "Текущая цель",
  "user.prefers_response_length": "Стиль ответов",
  "user.health_constraint": "Ограничение здоровья",
  "user.constraint": "Ограничение",
  name: "Имя пользователя",
  developer: "Разработчик Iris",
  developers: "Разработчики Iris",
  developerof: "Разработчик Iris",
  is_developer_of: "Разработчик Iris",
};

function memoryLabel(memory: MemoryItem): string {
  return MEMORY_LABELS[memory.slot_key ?? ""] ?? MEMORY_LABELS[memory.predicate] ?? memory.predicate;
}

export function MemoryPage() {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [topics, setTopics] = useState<MemoryTopic[]>([]);
  const [commitments, setCommitments] = useState<MemoryCommitment[]>([]);
  const [conflicts, setConflicts] = useState<Array<{ id: string; reason: string; status: string }>>([]);
  const [diagnostics, setDiagnostics] = useState<MemoryDiagnostics>({ queue: {}, runs: [] });
  const [section, setSection] = useState<MemorySection>("all");
  const [query, setQuery] = useState("");
  const [audit, setAudit] = useState<Record<string, MemoryAuditItem[]>>({});
  const [message, setMessage] = useState<string | null>(null);

  const containerRef = useAnimeScope<HTMLElement>((scope, root) => {
    animatePageEnter(root);
  }, []);

  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (listRef.current) {
      animateStaggerCards(listRef.current, ".memory-card", 35);
    }
  }, [section, items, topics, commitments, diagnostics, conflicts]);

  const refresh = async () => {
    try {
      if (section === "topics") { setTopics((await getMemoryTopics()).items); setMessage(null); return; }
      if (section === "commitments") { setCommitments((await getMemoryCommitments()).items); setMessage(null); return; }
      if (section === "diagnostics") {
        const [conflictData, diagnosticData] = await Promise.all([getMemoryConflicts(), getMemoryDiagnostics()]);
        setConflicts(conflictData.items); setDiagnostics(diagnosticData); setMessage(null); return;
      }
      const result = await getMemories(section === "all" || section === "archive" ? undefined : section, query || undefined);
      setItems(
        section === "archive"
          ? result.items.filter((item) => item.status !== "active")
          : section === "all"
            ? result.items.filter((item) => item.status === "active")
            : result.items,
      );
      setMessage(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Память недоступна");
    }
  };

  useEffect(() => { void refresh(); }, [section]);

  const action = async (run: () => Promise<unknown>) => {
    try { await run(); await refresh(); } catch (error) { setMessage(error instanceof Error ? error.message : "Не удалось выполнить действие"); }
  };

  return <section className="panel memory-panel" ref={containerRef}>
    <nav className="settings-navigation memory-navigation" aria-label="Разделы памяти">
      {MEMORY_SECTIONS.map(({ id, label, icon: Icon }) => (
        <button
          className={`settings-nav-button${section === id ? " is-active" : ""}`}
          aria-current={section === id ? "page" : undefined}
          key={id}
          onClick={(e) => { animateButtonPress(e.currentTarget); setSection(id); }}
        >
          <Icon size={17} aria-hidden="true" />
          {label}
        </button>
      ))}
    </nav>
    <div className="memory-toolbar">
      <div className="memory-toolbar-actions">
        <form className="search-form compact" onSubmit={(event) => { event.preventDefault(); void refresh(); }}>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Поиск по памяти" aria-label="Поиск по памяти" />
          <button className="icon-button search-submit" type="submit" aria-label="Найти в памяти" title="Найти в памяти"><Search size={17} /></button>
        </form>
      </div>
    </div>
    {message && <p className="error-text" role="alert">{message}</p>}
    <div className="memory-list" ref={listRef}>
      {section === "topics" && topics.map((topic) => <article className="memory-card" key={topic.id}><div className="memory-card-main"><div className="memory-card-heading"><span className="memory-status active">{topic.status}</span>{topic.user_locked && <Pin size={14} />}</div><strong data-i18n-skip>{topic.title}</strong><p data-i18n-skip>{topic.summary_text || "Краткое описание ещё не сформировано."}</p><small>Связи: {topic.links.length} · доказательства: {topic.evidence.length}</small></div></article>)}
      {section === "commitments" && commitments.map((commitment) => <article className="memory-card" key={commitment.id}><div className="memory-card-main"><div className="memory-card-heading"><span className={`memory-status ${commitment.status === "open" ? "active" : "deleted"}`}>{commitment.status}</span></div><strong data-i18n-skip>{commitment.title}</strong><p data-i18n-skip>{commitment.details}</p><small>{commitment.kind} · уверенность: {Math.round(commitment.confidence * 100)}%</small></div></article>)}
      {section === "diagnostics" && <>
        {diagnostics.integrity && <article className="memory-card"><div className="memory-card-main"><div className="memory-card-heading"><span className={`memory-status ${diagnostics.integrity.state === "healthy" ? "active" : "deleted"}`}>{diagnostics.integrity.state}</span></div><strong>Целостность памяти</strong><p>Активные конфликты: {diagnostics.integrity.active_conflicts} · без канонического слота: {diagnostics.integrity.noncanonical_active} · без источников: {diagnostics.integrity.provenance_missing}</p><small>Рассинхронизация источников: {diagnostics.integrity.source_count_mismatches} · кандидаты: {diagnostics.integrity.candidate_count ?? 0} · ограничения: {diagnostics.integrity.guards_installed ? "включены" : "не установлены"}</small></div></article>}
        {diagnostics.autonomy && <article className="memory-card"><div className="memory-card-main"><div className="memory-card-heading"><span className={`memory-status ${diagnostics.autonomy.candidate_count === 0 ? "active" : "deleted"}`}>{diagnostics.autonomy.candidate_count === 0 ? "автономно" : "нарушение"}</span></div><strong>Автономные решения</strong><p>Принято: {diagnostics.autonomy.decisions.accepted ?? 0} · отклонено: {Object.entries(diagnostics.autonomy.decisions).filter(([key]) => key.startsWith("rejected")).reduce((sum, [, count]) => sum + count, 0)} · открытых уточнений: {diagnostics.autonomy.open_clarifications}</p><small>Ручная очередь: {diagnostics.autonomy.candidate_count}</small></div></article>}
        {diagnostics.index_health && <article className="memory-card"><div className="memory-card-main"><div className="memory-card-heading"><span className={`memory-status ${diagnostics.index_health.state === "healthy" ? "active" : "deleted"}`}>{diagnostics.index_health.state}</span></div><strong>Здоровье поискового индекса</strong><p>SQLite: {Object.values(diagnostics.active_by_namespace ?? {}).reduce((sum, count) => sum + count, 0)} · отсутствует: {diagnostics.index_health.missing_ids.length} · устарело: {diagnostics.index_health.stale_ids.length}</p><small>{diagnostics.index_health.degraded_reason ?? "Chroma синхронизирована; SQLite остаётся источником истины."}</small></div></article>}
        {diagnostics.repair && <article className="memory-card"><div className="memory-card-main"><div className="memory-card-heading"><span className="memory-status active">{diagnostics.repair.status}</span></div><strong>Автопочинка памяти</strong><p>Канонизировано: {Number(diagnostics.repair.result.canonicalized ?? 0)} · устранено дублей: {Number(diagnostics.repair.result.duplicates_superseded ?? diagnostics.repair.result.topics_merged ?? 0)} · перенесено доказательств: {Number(diagnostics.repair.result.evidence_copied ?? 0)}</p><small>{diagnostics.repair.repair_key}</small></div></article>}
        {diagnostics.runs.map((run) => <article className="memory-card" key={run.id}><div className="memory-card-main"><div className="memory-card-heading"><span className={`memory-status ${run.result.outcome === "applied" ? "active" : "deleted"}`}>{run.result.outcome ?? run.status}</span></div><strong>Консолидация памяти</strong><p>Предложено: {run.result.proposed ?? 0} · сохранено: {run.result.saved ?? 0} · отклонено: {run.result.discarded ?? 0}</p><small>{run.diagnostics.error_codes?.length ? `Причина: ${run.diagnostics.error_codes.join(", ")}` : "Ошибок нет"} · {run.diagnostics.model ?? "локальный путь"}</small></div></article>)}
        {conflicts.map((conflict) => <article className="memory-card" key={conflict.id}><div className="memory-card-main"><strong>Конфликт: {conflict.status}</strong><p>{conflict.reason}</p></div></article>)}
        {!diagnostics.runs.length && !conflicts.length && <div className="empty-state"><CircleHelp size={28} /><strong>Диагностических записей пока нет</strong><span>Здесь появятся результаты фоновой консолидации и понятные причины нулевой записи.</span></div>}
      </>}
      {!(["topics", "commitments", "diagnostics"] as MemorySection[]).includes(section) && <>
      {items.length ? items.map((memory) => <article className="memory-card" key={memory.id}>
        <div className="memory-card-main"><div className="memory-card-heading"><span className={`memory-status ${memory.status}`}>{STATUS_LABELS[memory.status]}</span>{memory.user_locked && <Pin size={14} aria-label="Закреплённая запись" />}</div><strong>{memoryLabel(memory)}</strong><p data-i18n-skip>{memory.value_text}</p>{section === "archive" && memory.replacement && <p className="memory-replacement"><span>Заменено на: </span><span data-i18n-skip>{memory.replacement.value_text}</span></p>}<small>{(memory.source_count ?? memory.source_message_ids.length) ? `Источник: ${memory.source_count ?? memory.source_message_ids.length} сообщ.` : "Источник не указан"} · {section === "archive" ? "использовалось до замены" : "использовано"}: {memory.access_count}</small></div>
        <div className="memory-actions">
          <details className="memory-action-menu">
                <summary className="icon-button" role="button" aria-label="Дополнительные действия"><MoreHorizontal size={17} aria-hidden="true" /></summary>
                <div>
                  <button type="button" onClick={async () => { const nextAudit = await getMemoryAudit(memory.id); setAudit((current) => ({ ...current, [memory.id]: nextAudit.items })); }}><CircleHelp size={16} aria-hidden="true" />История записи</button>
                  {memory.status !== "deleted" && <button className="is-danger" type="button" onClick={() => void action(() => deleteMemory(memory.id))}><Trash2 size={16} aria-hidden="true" />Забыть</button>}
                </div>
              </details>
        </div>
        {audit[memory.id] && <details className="memory-audit" open><summary>История записи</summary><p>{audit[memory.id].map((item) => `${item.action} (${item.actor})`).join(" → ")}</p></details>}
      </article>) : <div className="empty-state"><Brain size={28} aria-hidden="true" /><strong>Записей пока нет</strong><span>Помощник предложит факты для сохранения после разговора.</span></div>}
      </>}
    </div>
  </section>;
}
