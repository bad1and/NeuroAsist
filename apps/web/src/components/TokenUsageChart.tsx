import { useId, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Area, AreaChart } from "./charts/area-chart";
import { Grid } from "./charts/grid";
import { XAxis } from "./charts/x-axis";
import { YAxis } from "./charts/y-axis";
import { ChartTooltip } from "./charts/tooltip";
import { useChart, useChartPortalContainer } from "./charts/chart-context";
import { SlidingSegments } from "./SlidingSegments";
import { MaterialButton } from "./MaterialButton";
import { IconInterfaceActivity as Activity } from "../CustomIcons";
import { buildUsageData, formatTokens, formatCompactTokens, type UsageMetric, type UsageChartPoint } from "./expenses";
import type { TokenUsageTimeseriesPoint } from "../types";

export interface TokenUsageChartProps {
  timeseries: TokenUsageTimeseriesPoint[];
  timeframe?: "24h" | "7d" | "30d" | "all";
  loading?: boolean;
  unavailable?: boolean;
}

const METRICS = { tokens: { label: "Токены", key: "total" }, requests: { label: "Запросы", key: "request_count" }, cache: { label: "Кэш", key: "cache_hit" } } as const;

/** Keyboard exploration shares the exact Bklit hover context with the pointer. */
function KeyboardExplorer({ descriptionId }: { descriptionId: string }) {
  const { data, xScale, yScale, lines, tooltipData, setTooltipData, containerRef, margin } = useChart();
  const container = useChartPortalContainer(containerRef);
  if (!container) return null;
  return createPortal(<div className="expense-chart-keyboard" tabIndex={0} role="group"
    aria-label="Исследовать график" aria-describedby={descriptionId}
    style={{ inset: `${margin.top}px ${margin.right}px ${margin.bottom}px ${margin.left}px` }}
    onBlur={() => setTooltipData(null)}
    onKeyDown={event => {
      if (event.key === "Escape") { setTooltipData(null); return; }
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key) || !data.length) return;
      event.preventDefault();
      const current = tooltipData?.index ?? -1;
      const index = event.key === "Home" ? 0 : event.key === "End" ? data.length - 1
        : Math.max(0, Math.min(data.length - 1, current + (event.key === "ArrowLeft" ? -1 : 1)));
      const point = data[index];
      setTooltipData({ index, point, x: xScale(point.date as Date),
        yPositions: Object.fromEntries(lines.map(line => [line.dataKey, yScale(Number(point[line.dataKey]))])) });
    }}><span className="expense-sr-only" aria-live="polite">{tooltipData
      ? `${tooltipData.point.label}: ${lines.map(line => `${({ request_count: "запросы", total: "всего токенов", completion: "ответы Iris", cache_hit: "из кэша" } as Record<string, string>)[line.dataKey] || line.dataKey} ${formatTokens(Number(tooltipData.point[line.dataKey]))}`).join(", ")}`
      : "Стрелки влево и вправо выбирают интервал. Home и End переходят к краям графика."}</span></div>, container);
}

export function TokenUsageChart({ timeseries, timeframe, loading = false, unavailable = false }: TokenUsageChartProps) {
  const [metric, setMetric] = useState<UsageMetric>("tokens");
  const [cumulative, setCumulative] = useState(false);
  const descriptionId = useId();
  const data = useMemo(() => buildUsageData(timeseries, cumulative), [timeseries, cumulative]);
  const hasData = data.some(point => point.total > 0 || point.request_count > 0);
  const metricConfig = METRICS[metric];
  const total = timeseries.reduce((sum, point) => sum + (point[metricConfig.key] || 0), 0);
  const peak = timeseries.reduce<TokenUsageTimeseriesPoint | null>((best, point) => !best || point[metricConfig.key] > best[metricConfig.key] ? point : best, null);

  return <section className="expense-activity" aria-labelledby={`${descriptionId}-title`} aria-busy={loading}>
    <div className="expense-chart-heading">
      <div><h3 id={`${descriptionId}-title`}>Активность Iris</h3><p>Как меняется использование модели</p></div>
      <SlidingSegments value={metric} className="expense-metrics" aria-label="Метрика графика">
        {(Object.keys(METRICS) as UsageMetric[]).map(key => <MaterialButton key={key} appearance="plain"
          className={metric === key ? "active" : ""} aria-pressed={metric === key}
          materialKey={`expenses.metric.${key}`} onClick={() => setMetric(key)}>{METRICS[key].label}</MaterialButton>)}
      </SlidingSegments>
    </div>
    <div className="expense-chart-summary">
      <div><strong>{loading || unavailable ? "—" : formatCompactTokens(total)}</strong><span>{metric === "requests" ? "запросов за период" : metric === "cache" ? "входных токенов из кэша" : "токенов за период"}</span></div>
      <SlidingSegments value={String(cumulative)} className="expense-chart-mode" aria-label="Отображение графика">
        <MaterialButton appearance="plain" materialKey="expenses.intervals" className={!cumulative ? "active" : ""} aria-pressed={!cumulative} onClick={() => setCumulative(false)}>По интервалам</MaterialButton>
        <MaterialButton appearance="plain" materialKey="expenses.cumulative" className={cumulative ? "active" : ""} aria-pressed={cumulative} onClick={() => setCumulative(true)}>Накопительно</MaterialButton>
      </SlidingSegments>
    </div>
    <p id={descriptionId} className="expense-sr-only">{cumulative ? "Сумма с начала выбранного периода." : "Значения за каждый интервал."} Для просмотра с клавиатуры используйте стрелки, Home и End.</p>
    {loading || !hasData || unavailable ? <div className="expense-chart-placeholder" role="status">
      {loading ? <><div className="expense-loading-plot" aria-hidden="true"><svg viewBox="0 0 600 180" preserveAspectRatio="none"><path d="M0 145 C50 145 60 100 110 110 S170 170 220 90 S300 125 350 65 S430 110 480 45 S560 65 600 25" /></svg></div><span>Загружаем активность…</span></>
        : <><Activity size={28} /><strong>{unavailable ? "График недоступен" : "Здесь появится активность"}</strong><span>{unavailable ? "Обновите данные, чтобы попробовать снова." : "За этот период запросов ещё нет. Попробуйте другой диапазон."}</span></>}
    </div> : <div className="expense-chart-plot">
      <AreaChart key={`${timeframe}-${metric}`} data={data} style={{ height: 260, aspectRatio: "auto", touchAction: "pan-y" }}
        margin={{ top: 20, right: 12, bottom: 36, left: 46 }} animationDuration={720}
        enterTransition={{ type: "tween", duration: .72 }} revealSignature={`${metric}-${cumulative}`}>
        <Grid numTicksRows={4} strokeDasharray="2,6" hideHorizontalEdgeLines />
        <Area dataKey={metricConfig.key} fill="var(--chart-1)" stroke="var(--chart-1)" fillOpacity={.27}
          gradientToOpacity={0} strokeWidth={2.5} showHighlight={false} showMarkers={data.length === 1} />
        {metric === "tokens" && <Area dataKey="completion" fillOpacity={0} stroke="var(--chart-2)" strokeWidth={1.7} showHighlight={false} showMarkers={data.length === 1} />}
        <XAxis labels={data.map(point => point.label)} />
        <YAxis numTicks={4} formatValue={formatCompactTokens} />
        <ChartTooltip dateLabels={data.map(point => point.label)} showDatePill={false} dotVariant="ring" dotSize={4}
          indicatorDasharray="3,5" damping={0} className="expense-tooltip" content={({ point }) => {
            const value = point as UsageChartPoint;
            return <div className="expense-tooltip-content"><header>{value.label}<span>{cumulative ? "С начала периода" : "За интервал"}</span></header>
              <dl><div><dt>Всего токенов</dt><dd>{formatTokens(value.total)}</dd></div>
                <div><dt>Входящие</dt><dd>{formatTokens(value.prompt)}</dd></div>
                <div><dt>Ответы Iris</dt><dd>{formatTokens(value.completion)}</dd></div>
                <div><dt>Из кэша <small>часть входящих</small></dt><dd>{formatTokens(value.cache_hit)}</dd></div>
                <div><dt>Запросы</dt><dd>{formatTokens(value.request_count)}</dd></div></dl></div>;
          }} />
        <KeyboardExplorer descriptionId={descriptionId} />
      </AreaChart>
    </div>}
    <div className="expense-chart-footer">
      <div className="expense-series-key"><span><i />{metric === "tokens" ? "Всего токенов" : metric === "requests" ? "Запросы" : "Из кэша"}</span>{metric === "tokens" && <span><i />Ответы Iris</span>}</div>
      <span>{!loading && !unavailable && peak && peak[metricConfig.key] > 0 ? `Пик: ${peak.label} · ${formatCompactTokens(peak[metricConfig.key])}` : ""}</span>
    </div>
  </section>;
}
