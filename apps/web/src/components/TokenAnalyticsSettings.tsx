import { useState, useEffect, useCallback, useMemo } from "react";
import {
  Zap,
  RefreshCw,
  Trash2,
  TrendingUp,
  Server,
  ChevronLeft,
  ChevronRight,
  Check,
  Copy,
  Terminal,
  Layers,
} from "lucide-react";
import { getLlmTokenStats, getLlmTokenRecords, resetLlmTokenStats } from "../api";
import { AppDialog } from "./AppDialog";
import { TokenUsageChart } from "./TokenUsageChart";
import type { TokenUsageStats, TokenRecordItem, TokenRecordsResponse } from "../types";

const PURPOSE_LABELS: Record<string, string> = {
  chat_json: "Диалог (JSON)",
  chat_live: "Голосовой стрим",
  chat: "Чат / Диалог",
  live: "Живой разговор",
  chat_json_repair: "Диалог (Repair JSON)",
  chat_json_guard_retry: "Диалог (Guard Retry)",
  chat_live_guard_retry: "Голос (Guard Retry)",
  memory: "Извлечение памяти",
  memory_extraction: "Извлечение памяти",
  memory_repair: "Память (Repair JSON)",
  reflection: "Рефлексия и дневник",
  reflection_repair: "Рефлексия (Repair JSON)",
  memory_synthesis: "Синтез профиля",
  memory_conflict: "Разрешение конфликтов",
  adjudication: "Арбитраж диалога",
  coding: "Coding Agent",
  test: "Тестирование",
};

export type PurposeCategory = "all" | "chat" | "memory" | "guards" | "coding";

export const CATEGORY_TABS: { id: PurposeCategory; label: string; purposes?: string[] }[] = [
  { id: "all", label: "Все назначения" },
  { id: "chat", label: "Диалог и голос", purposes: ["chat_json", "chat_live", "adjudication", "chat", "live"] },
  { id: "memory", label: "Память и рефлексия", purposes: ["memory", "reflection", "memory_extraction", "memory_synthesis", "memory_conflict"] },
  { id: "guards", label: "Защита и Repair", purposes: ["chat_json_repair", "chat_json_guard_retry", "chat_live_guard_retry", "memory_repair", "reflection_repair"] },
  { id: "coding", label: "Coding Agent", purposes: ["coding"] },
];

function formatNum(num?: number): string {
  if (num === undefined || num === null || isNaN(num)) return "0";
  return num.toLocaleString().replace(/\u00a0/g, " ");
}

function formatCost(usd?: number): string {
  if (usd === undefined || usd === null || isNaN(usd)) return "$0.00";
  if (usd > 0 && usd < 0.0001) return "<$0.0001";
  return `$${usd.toFixed(4)}`;
}

function formatTimeOnly(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDateTime(ts: number): string {
  const d = new Date(ts * 1000);
  return `${d.toLocaleDateString([], { month: "short", day: "numeric" })} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
}

export function TokenAnalyticsSettings() {
  const [timeframe, setTimeframe] = useState<"24h" | "7d" | "30d" | "all">("24h");
  const [stats, setStats] = useState<TokenUsageStats | null>(null);
  const [recordsResponse, setRecordsResponse] = useState<TokenRecordsResponse | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<PurposeCategory>("all");
  const [purposeFilter, setPurposeFilter] = useState<string>("");
  const [page, setPage] = useState(0);
  const pageSize = 20;

  const [loading, setLoading] = useState(true);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Modals & Details
  const [showResetDialog, setShowResetDialog] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [inspectRecord, setInspectRecord] = useState<TokenRecordItem | null>(null);
  const [copiedInspect, setCopiedInspect] = useState(false);

  const currentCategory = useMemo(
    () => CATEGORY_TABS.find((c) => c.id === selectedCategory),
    [selectedCategory],
  );

  const effectivePurpose = useMemo(() => {
    if (purposeFilter) return purposeFilter;
    if (currentCategory?.purposes) return currentCategory.purposes.join(",");
    return "";
  }, [purposeFilter, currentCategory]);

  const availablePurposes = useMemo(() => {
    if (!currentCategory?.purposes) {
      return Object.entries(PURPOSE_LABELS);
    }
    return Object.entries(PURPOSE_LABELS).filter(([k]) => currentCategory.purposes?.includes(k));
  }, [currentCategory]);

  const fetchStats = useCallback(async (tf = timeframe) => {
    setLoading(true);
    setError(null);
    try {
      const data = await getLlmTokenStats(tf);
      setStats(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить статистику токенов");
    } finally {
      setLoading(false);
    }
  }, [timeframe]);

  const fetchRecords = useCallback(async (currPage = page, purpose = effectivePurpose) => {
    setRecordsLoading(true);
    try {
      const data = await getLlmTokenRecords(pageSize, currPage * pageSize, purpose || undefined);
      setRecordsResponse(data);
    } catch {
      // Keep previous records
    } finally {
      setRecordsLoading(false);
    }
  }, [page, effectivePurpose]);

  useEffect(() => {
    void fetchStats(timeframe);
  }, [fetchStats, timeframe]);

  useEffect(() => {
    void fetchRecords(page, effectivePurpose);
  }, [fetchRecords, page, effectivePurpose]);

  const handleReset = async () => {
    setResetting(true);
    try {
      await resetLlmTokenStats();
      setShowResetDialog(false);
      await fetchStats();
      await fetchRecords(0, purposeFilter);
      setPage(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сбросить статистику");
    } finally {
      setResetting(false);
    }
  };

  const handleCopyInspectJson = async () => {
    if (!inspectRecord) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(inspectRecord, null, 2));
      setCopiedInspect(true);
      setTimeout(() => setCopiedInspect(false), 2000);
    } catch {
      // Fallback
    }
  };

  const timeseries = stats?.timeseries ?? [];
  const totalPages = recordsResponse ? Math.ceil(recordsResponse.total / pageSize) : 1;

  return (
    <div className="token-analytics-page">
      {/* Top Header */}
      <div className="token-analytics-header">
        <div className="token-analytics-title-group">
          <div className="token-analytics-title-icon">
            <Zap size={20} />
          </div>
          <div>
            <h2>Токены и расходы LLM</h2>
            <p className="token-analytics-subtitle">
              Полный учет входящих и исходящих токенов API DeepSeek, коэффициента кэширования и затрат
            </p>
          </div>
        </div>

        <div className="token-analytics-controls">
          {/* Timeframe pill selector */}
          <div className="token-timeframe-selector" role="group" aria-label="Временной диапазон">
            {(
              [
                { key: "24h", label: "24 ч" },
                { key: "7d", label: "7 дн" },
                { key: "30d", label: "30 дн" },
                { key: "all", label: "Всё время" },
              ] as const
            ).map((tf) => (
              <button
                key={tf.key}
                type="button"
                className={`token-timeframe-btn ${timeframe === tf.key ? "active" : ""}`}
                onClick={() => setTimeframe(tf.key)}
              >
                {tf.label}
              </button>
            ))}
          </div>

          <button
            type="button"
            className="secondary icon-btn-text"
            onClick={() => {
              void fetchStats();
              void fetchRecords();
            }}
            disabled={loading}
            title="Обновить данные"
          >
            <RefreshCw size={15} className={loading ? "spin" : ""} />
            <span>Обновить</span>
          </button>

          <button
            type="button"
            className="secondary icon-btn-text token-reset-btn"
            onClick={() => setShowResetDialog(true)}
            title="Очистить журнал токенов"
          >
            <Trash2 size={15} />
            <span>Сброс</span>
          </button>
        </div>
      </div>

      {error && <div className="notice error-banner">{error}</div>}

      {/* KPI Cards Grid */}
      <div className="token-kpi-grid">
        {/* 1. Total Tokens */}
        <div className="token-kpi-card">
          <div className="token-kpi-header">
            <span className="token-kpi-label">Всего токенов</span>
          </div>
          <div className="token-kpi-value text-total" data-testid="kpi-total-tokens">
            {formatNum(stats?.total_tokens)}
          </div>
          <div className="token-kpi-footer">
            <span className="text-prompt">In: {formatNum(stats?.prompt_tokens)}</span>
            <span className="dot-divider">·</span>
            <span className="text-completion">Out: {formatNum(stats?.completion_tokens)}</span>
          </div>
        </div>

        {/* 2. Cache Hit Rate */}
        <div className="token-kpi-card">
          <div className="token-kpi-header">
            <span className="token-kpi-label">Кэширование промптов</span>
          </div>
          <div className="token-kpi-value text-cache" data-testid="kpi-cache-rate">
            {stats ? `${stats.cache_hit_rate.toFixed(1)}%` : "0.0%"}
          </div>
          <div className="token-kpi-footer">
            <span className="text-hit">Hit: {formatNum(stats?.cache_hit_tokens)}</span>
            <span className="dot-divider">·</span>
            <span className="text-miss">Miss: {formatNum(stats?.cache_miss_tokens)}</span>
          </div>
        </div>

        {/* 3. Requests & Latency */}
        <div className="token-kpi-card">
          <div className="token-kpi-header">
            <span className="token-kpi-label">Запросы и скорость</span>
          </div>
          <div className="token-kpi-value">
            {formatNum(stats?.request_count)} <span className="kpi-unit">вызовов</span>
          </div>
          <div className="token-kpi-footer">
            <span>Средняя: {stats?.latency_avg_ms ?? 0} мс</span>
            <span className="dot-divider">·</span>
            <span>p95: {stats?.latency_p95_ms ?? 0} мс</span>
          </div>
        </div>

        {/* 4. Estimated Cost */}
        <div className="token-kpi-card">
          <div className="token-kpi-header">
            <span className="token-kpi-label">Расходы (DeepSeek)</span>
          </div>
          <div className="token-kpi-value text-cost" data-testid="kpi-cost">
            {formatCost(stats?.estimated_cost_usd)}
          </div>
          <div className="token-kpi-footer">
            <span>$0.07/M cached in · $1.10/M out</span>
          </div>
        </div>
      </div>

      {/* Timeseries Chart Card (Bklit UI) */}
      <div className="token-chart-card">
        <div className="token-chart-header">
          <div className="token-chart-title-wrap">
            <TrendingUp size={16} className="text-accent" />
            <h3>Динамика расхода токенов</h3>
          </div>
          <div className="token-chart-legend">
            <div className="legend-item">
              <span className="legend-dot prompt-dot" />
              <span>Prompt</span>
            </div>
            <div className="legend-item">
              <span className="legend-dot completion-dot" />
              <span>Output</span>
            </div>
            <div className="legend-item">
              <span className="legend-dot cache-dot" />
              <span>Cache Hit</span>
            </div>
          </div>
        </div>

        <TokenUsageChart timeseries={timeseries} timeframe={timeframe} />
      </div>

      {/* Breakdowns 2-Column Section */}
      <div className="token-breakdown-grid">
        {/* By Purpose */}
        <div className="token-breakdown-card">
          <div className="breakdown-card-header">
            <Layers size={16} className="text-accent" />
            <h4>Распределение по назначению</h4>
          </div>
          <div className="breakdown-list">
            {stats && Object.keys(stats.by_purpose).length > 0 ? (
              Object.entries(stats.by_purpose).map(([purposeKey, data]) => {
                const percent = stats.total_tokens > 0
                  ? Math.round((data.total / stats.total_tokens) * 100)
                  : 0;
                return (
                  <div key={purposeKey} className="breakdown-item">
                    <div className="breakdown-item-top">
                      <span className="breakdown-name">
                        {PURPOSE_LABELS[purposeKey] || purposeKey}
                      </span>
                      <span className="breakdown-nums">
                        <strong>{formatNum(data.total)}</strong> ({percent}%) · {data.request_count} вызовов
                      </span>
                    </div>
                    <div className="breakdown-bar-bg">
                      <div
                        className="breakdown-bar-val"
                        style={{ width: `${Math.max(3, percent)}%` }}
                      />
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="empty-subtext">Нет записей за период</div>
            )}
          </div>
        </div>

        {/* By Model */}
        <div className="token-breakdown-card">
          <div className="breakdown-card-header">
            <Server size={16} className="text-accent" />
            <h4>Распределение по моделям</h4>
          </div>
          <div className="breakdown-list">
            {stats && Object.keys(stats.by_model).length > 0 ? (
              Object.entries(stats.by_model).map(([modelKey, data]) => {
                const percent = stats.total_tokens > 0
                  ? Math.round((data.total / stats.total_tokens) * 100)
                  : 0;
                return (
                  <div key={modelKey} className="breakdown-item">
                    <div className="breakdown-item-top">
                      <span className="breakdown-name model-code">{modelKey}</span>
                      <span className="breakdown-nums">
                        <strong>{formatNum(data.total)}</strong> ({percent}%) · {data.request_count} вызовов
                      </span>
                    </div>
                    <div className="breakdown-bar-bg">
                      <div
                        className="breakdown-bar-val model-bar"
                        style={{ width: `${Math.max(3, percent)}%` }}
                      />
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="empty-subtext">Нет записей за период</div>
            )}
          </div>
        </div>
      </div>

      {/* Raw Requests Table Card */}
      <div className="token-records-card">
        <div className="records-card-header">
          <div className="records-card-title-group">
            <Terminal size={17} className="text-accent" />
            <h3>Журнал запросов к LLM</h3>
            <span className="records-count-badge">
              Всего: {recordsResponse?.total ?? 0}
            </span>
          </div>

          <div className="records-filter-group">
            <select
              value={purposeFilter}
              onChange={(e) => {
                setPurposeFilter(e.target.value);
                setPage(0);
              }}
              className="records-purpose-select"
              aria-label="Фильтр по назначению"
            >
              <option value="">
                {selectedCategory === "all" ? "Все операции" : "Все в этой категории"}
              </option>
              {availablePurposes.map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </div>
        </div>

        {/* High-level Category Tabs */}
        <div className="records-category-tabs" role="tablist" aria-label="Категории вызовов LLM">
          {CATEGORY_TABS.map((cat) => (
            <button
              key={cat.id}
              type="button"
              role="tab"
              aria-selected={selectedCategory === cat.id}
              className={`records-category-tab ${selectedCategory === cat.id ? "active" : ""}`}
              onClick={() => {
                setSelectedCategory(cat.id);
                setPurposeFilter("");
                setPage(0);
              }}
            >
              {cat.label}
            </button>
          ))}
        </div>

        <div className="records-table-wrapper">
          <table className="token-records-table">
            <thead>
              <tr>
                <th>Время</th>
                <th>Назначение</th>
                <th>Модель</th>
                <th>Prompt (Hit/Miss)</th>
                <th>Output</th>
                <th>Всего</th>
                <th>Задержка</th>
                <th>Статус</th>
                <th>JSON</th>
              </tr>
            </thead>
            <tbody>
              {recordsResponse?.items && recordsResponse.items.length > 0 ? (
                recordsResponse.items.map((r, i) => (
                  <tr key={`${r.request_id}-${i}`} className="records-table-row">
                    <td className="cell-time" title={formatDateTime(r.timestamp)}>
                      {formatTimeOnly(r.timestamp)}
                    </td>
                    <td>
                      <span className="purpose-badge">
                        {PURPOSE_LABELS[r.purpose] || r.purpose}
                      </span>
                    </td>
                    <td className="cell-model">
                      <code className="model-tag">{r.model}</code>
                    </td>
                    <td>
                      <span className="text-prompt">{formatNum(r.prompt)}</span>
                      {r.cache_hit > 0 && (
                        <span className="cache-mini-tag hit">+{formatNum(r.cache_hit)}</span>
                      )}
                    </td>
                    <td>
                      <span className="text-completion">{formatNum(r.completion)}</span>
                      {r.reasoning > 0 && (
                        <span className="reasoning-mini-tag">R: {formatNum(r.reasoning)}</span>
                      )}
                    </td>
                    <td className="cell-total">
                      <strong>{formatNum(r.total)}</strong>
                    </td>
                    <td className="cell-latency">{r.latency_ms} мс</td>
                    <td>
                      <span className={`status-tag ${r.status === "success" ? "success" : "error"}`}>
                        {r.status === "success" ? "200 OK" : "Ошибка"}
                      </span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="inspect-btn"
                        onClick={() => setInspectRecord(r)}
                        title="Просмотреть сырой JSON"
                        aria-label="Просмотреть сырой JSON"
                      >
                        <Terminal size={13} />
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={9} className="records-empty">
                    {recordsLoading ? "Загрузка журнала запросов…" : "Журнал вызовов пуст"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination footer */}
        {totalPages > 1 && (
          <div className="records-pagination">
            <span>
              Страница {page + 1} из {totalPages}
            </span>
            <div className="pagination-buttons">
              <button
                type="button"
                className="secondary pagination-btn"
                disabled={page === 0 || recordsLoading}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
              >
                <ChevronLeft size={15} />
                <span>Назад</span>
              </button>
              <button
                type="button"
                className="secondary pagination-btn"
                disabled={page >= totalPages - 1 || recordsLoading}
                onClick={() => setPage((p) => p + 1)}
              >
                <span>Вперед</span>
                <ChevronRight size={15} />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Inspect Raw JSON Dialog */}
      <AppDialog
        open={Boolean(inspectRecord)}
        title="Сырые метрики вызова LLM"
        description={inspectRecord ? `Запрос: ${inspectRecord.request_id}` : ""}
        onClose={() => setInspectRecord(null)}
        variant="info"
      >
        <div className="inspect-dialog-body">
          {inspectRecord && (
            <>
              <div className="inspect-meta-grid">
                <div>
                  <span className="meta-label">Модель:</span>
                  <strong>{inspectRecord.model}</strong>
                </div>
                <div>
                  <span className="meta-label">Назначение:</span>
                  <strong>{PURPOSE_LABELS[inspectRecord.purpose] || inspectRecord.purpose}</strong>
                </div>
                <div>
                  <span className="meta-label">Задержка:</span>
                  <strong>{inspectRecord.latency_ms} мс</strong>
                </div>
                <div>
                  <span className="meta-label">Всего токенов:</span>
                  <strong>{formatNum(inspectRecord.total)}</strong>
                </div>
              </div>

              <div className="inspect-json-box">
                <div className="inspect-json-header">
                  <span>Сырой объект записи</span>
                  <button
                    type="button"
                    className="token-copy-btn"
                    onClick={handleCopyInspectJson}
                  >
                    {copiedInspect ? <Check size={13} /> : <Copy size={13} />}
                    <span>{copiedInspect ? "Скопировано!" : "Копировать JSON"}</span>
                  </button>
                </div>
                <pre className="inspect-pre">
                  <code>{JSON.stringify(inspectRecord, null, 2)}</code>
                </pre>
              </div>
            </>
          )}
          <div className="dialog-actions" style={{ marginTop: 16 }}>
            <button
              type="button"
              className="secondary"
              onClick={() => setInspectRecord(null)}
            >
              Закрыть
            </button>
          </div>
        </div>
      </AppDialog>

      {/* Reset Confirmation Dialog */}
      <AppDialog
        open={showResetDialog}
        title="Сбросить статистику токенов?"
        description="Вся накопленная статистика, история запросов и данные о расходах будут безвозвратно удалены из базы данных."
        onClose={() => !resetting && setShowResetDialog(false)}
        variant="danger"
      >
        <div className="dialog-actions">
          <button
            type="button"
            className="secondary"
            disabled={resetting}
            onClick={() => setShowResetDialog(false)}
          >
            Отмена
          </button>
          <button
            type="button"
            className="danger-button"
            disabled={resetting}
            onClick={() => void handleReset()}
          >
            {resetting ? "Удаление…" : "Сбросить все данные токенов"}
          </button>
        </div>
      </AppDialog>
    </div>
  );
}
