import { useLayoutEffect, useRef } from "react";
import { IconInterfaceRefresh as Refresh, IconInterfaceDeleteBin3 as Trash } from "../CustomIcons";
import { animate, prefersReducedMotion } from "../animations/core";
import { MaterialButton } from "./MaterialButton";
import { SlidingSegments } from "./SlidingSegments";
import { TokenUsageChart } from "./TokenUsageChart";
import { TokenBreakdownChart } from "./TokenBreakdownChart";
import { ExpenseNumber } from "./ExpenseNumber";
import { formatTokens } from "./expenses";
import type { TokenUsageStats } from "../types";
import "./charts/bklit.css";
import "./ExpenseDashboard.css";

type Timeframe = "24h" | "7d" | "30d" | "all";
const PERIODS = { "24h": "24 ч", "7d": "7 дн", "30d": "30 дн", all: "Всё время" };
const formatCost = (value: number) => value > 0 && value < .0001 ? "<$0.0001" : `$${value.toFixed(4)}`;
const formatPercent = (value: number) => `${value.toFixed(1)}%`;

export function ExpenseDashboard({ stats, loading, error, timeframe, onTimeframe, onRefresh, onReset, purposeLabels, onPurpose }:
  { stats: TokenUsageStats | null; loading: boolean; error: string | null; timeframe: Timeframe;
    onTimeframe: (value: Timeframe) => void; onRefresh: () => void; onReset: () => void;
    purposeLabels: Record<string, string>; onPurpose: (purpose: string) => void }) {
  const root = useRef<HTMLDivElement>(null);
  const refresh = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    if (!loading || !refresh.current || prefersReducedMotion()) return;
    const motion = animate(refresh.current, { rotate: [0, 360], duration: 1000, loop: true, ease: "linear" });
    return () => { motion.revert(); };
  }, [loading]);
  useLayoutEffect(() => {
    if (!root.current || prefersReducedMotion()) return;
    const plot = root.current.querySelector(".expense-loading-plot");
    if (!plot) return;
    const motion = animate(plot, { opacity: [.25, .65, .25], duration: 1600, ease: "inOutSine", loop: true });
    return () => { motion.revert(); };
  }, [loading]);
  return <div className="expense-dashboard iris-charts" ref={root}>
    <header className="expense-page-heading">
      <div><h2>Расходы и запросы</h2><p>Использование модели — в цифрах и деталях.</p></div>
      <MaterialButton appearance="plain" className="expense-clear" materialKey="expenses.clear" onClick={onReset}
        title="Очистить журнал токенов" aria-label="Очистить журнал токенов"><Trash size={15} /><span>Очистить</span></MaterialButton>
    </header>
    <div className="expense-toolbar">
      <SlidingSegments value={timeframe} className="expense-periods" aria-label="Временной диапазон">
        {(Object.keys(PERIODS) as Timeframe[]).map(key => <MaterialButton key={key} appearance="plain" materialKey={`expenses.period.${key}`}
          className={timeframe === key ? "active" : ""} aria-pressed={timeframe === key} onClick={() => onTimeframe(key)}>{PERIODS[key]}</MaterialButton>)}
      </SlidingSegments>
      <MaterialButton className="secondary expense-refresh" materialKey="expenses.refresh" onClick={onRefresh}
        disabled={loading} title="Обновить данные" aria-label="Обновить данные"><span ref={refresh}><Refresh size={15} /></span><span className="expense-refresh-label">Обновить</span></MaterialButton>
    </div>
    {error && <div className="notice error-banner" role="alert">{error}</div>}
    <section className="expense-overview" aria-label="Итоги за выбранный период" aria-busy={loading}>
      <div className="expense-cost">
        <span className="expense-label">Оценка расходов</span>
        <strong className="expense-cost-value" data-testid="kpi-cost">{stats ? <ExpenseNumber value={stats.estimated_cost_usd} format={formatCost} /> : "—"}</strong>
        <span className="expense-cost-caption">USD · за выбранный период</span>
      </div>
      <div className="expense-stat">
        <span className="expense-label">Всего токенов</span>
        <strong data-testid="kpi-total-tokens">{stats ? <ExpenseNumber value={stats.total_tokens} /> : "—"}</strong>
        <span>Входящие <b>{stats ? formatTokens(stats.prompt_tokens) : "—"}</b></span>
        <span>Ответы Iris <b>{stats ? formatTokens(stats.completion_tokens) : "—"}</b></span>
      </div>
      <div className="expense-stat">
        <span className="expense-label">Запросы</span>
        <strong>{stats ? <ExpenseNumber value={stats.request_count} /> : "—"}</strong>
        <span>Средний ответ <b>{stats ? `${formatTokens(stats.latency_avg_ms)} мс` : "—"}</b></span>
        <span>{stats ? `${formatTokens(stats.success_count)} успешно · ${formatTokens(stats.error_count)} с ошибкой` : "Загружаем статистику"}</span>
      </div>
      <div className="expense-stat">
        <span className="expense-label">Кэш входящих</span>
        <strong data-testid="kpi-cache-rate">{stats ? <ExpenseNumber value={stats.cache_hit_rate} format={formatPercent} /> : "—"}</strong>
        <span>{stats ? `${formatTokens(stats.cache_hit_tokens)} токенов из кэша` : "—"}</span>
        <span>Повторно используемый контекст</span>
      </div>
      <p className="expense-cost-note">Оценка по учтённым токенам. Итоговая сумма у провайдера может отличаться.</p>
    </section>
    <TokenUsageChart timeseries={stats?.timeseries ?? []} timeframe={timeframe} loading={loading} unavailable={Boolean(error)} />
    <div className="expense-distributions">
      <TokenBreakdownChart key={`purpose-${timeframe}`} title="На что уходят токены" loading={loading} unavailable={Boolean(error)}
        items={Object.entries(stats?.by_purpose ?? {}).map(([key, value]) => ({ key, label: purposeLabels[key] || key, ...value }))} onInspect={onPurpose} />
      <TokenBreakdownChart key={`model-${timeframe}`} title="Использование моделей" loading={loading} unavailable={Boolean(error)}
        items={Object.entries(stats?.by_model ?? {}).map(([key, value]) => ({ key, label: key, ...value }))} />
    </div>
  </div>;
}
