import { useState, useMemo, useCallback, useRef } from "react";
import { ParentSize } from "@visx/responsive";
import { scaleBand, scaleLinear } from "@visx/scale";
import { Activity } from "lucide-react";
import type { TokenUsageTimeseriesPoint } from "../types";

export interface TokenUsageChartProps {
  timeseries: TokenUsageTimeseriesPoint[];
  timeframe?: "24h" | "7d" | "30d" | "all";
}

function formatCompact(num: number): string {
  if (num >= 1_000_000) {
    return `${(num / 1_000_000).toFixed(1)}M`;
  }
  if (num >= 1_000) {
    return `${(num / 1_000).toFixed(num >= 10_000 ? 0 : 1)}k`;
  }
  return String(num);
}

function formatFullNum(num?: number): string {
  if (num === undefined || num === null || isNaN(num)) return "0";
  return num.toLocaleString().replace(/\u00a0/g, " ");
}

interface ChartInnerSvgProps {
  width: number;
  height: number;
  timeseries: TokenUsageTimeseriesPoint[];
  timeframe?: "24h" | "7d" | "30d" | "all";
}

const MARGIN = { top: 16, right: 16, bottom: 28, left: 44 };

function ChartInnerSvg({ width, height, timeseries, timeframe }: ChartInnerSvgProps) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const containerRef = useRef<SVGSVGElement | null>(null);

  const innerWidth = Math.max(10, width - MARGIN.left - MARGIN.right);
  const innerHeight = Math.max(10, height - MARGIN.top - MARGIN.bottom);

  const maxTotal = useMemo(() => {
    const rawMax = Math.max(...timeseries.map((p) => p.total), 0);
    if (rawMax === 0) return 100;
    // Round up to nice number
    const magnitude = Math.pow(10, Math.floor(Math.log10(rawMax)));
    return Math.ceil((rawMax * 1.15) / magnitude) * magnitude;
  }, [timeseries]);

  const xScale = useMemo(() => {
    return scaleBand<number>({
      domain: timeseries.map((_, i) => i),
      range: [0, innerWidth],
      padding: timeseries.length > 20 ? 0.28 : 0.38,
    });
  }, [timeseries, innerWidth]);

  const yScale = useMemo(() => {
    return scaleLinear<number>({
      domain: [0, maxTotal],
      range: [innerHeight, 0],
      nice: true,
    });
  }, [maxTotal, innerHeight]);

  // Generate 4-5 nice horizontal grid lines
  const yTicks = useMemo(() => {
    const count = innerHeight < 120 ? 3 : 4;
    const ticks: { value: number; y: number }[] = [];
    for (let i = 0; i <= count; i++) {
      const val = (maxTotal / count) * i;
      ticks.push({
        value: val,
        y: yScale(val) ?? 0,
      });
    }
    return ticks;
  }, [maxTotal, yScale, innerHeight]);

  // Intelligently choose which X axis labels to render to prevent overlapping
  const visibleXIndices = useMemo(() => {
    const total = timeseries.length;
    if (total <= 7) {
      return new Set(timeseries.map((_, i) => i));
    }

    const maxLabels = innerWidth < 380 ? 4 : innerWidth < 600 ? 6 : 8;
    const step = Math.max(1, Math.ceil(total / maxLabels));
    const indices = new Set<number>();

    for (let i = 0; i < total; i += step) {
      indices.add(i);
    }
    // Always include the last item if reasonable
    if (total > 0 && !indices.has(total - 1)) {
      indices.add(total - 1);
    }
    return indices;
  }, [timeseries, innerWidth]);

  const bandwidth = xScale.bandwidth();

  // Mouse move handler
  const handleMouseMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (!containerRef.current || timeseries.length === 0) return;
      const rect = containerRef.current.getBoundingClientRect();
      const mouseX = e.clientX - rect.left - MARGIN.left;

      if (mouseX < 0 || mouseX > innerWidth) {
        setHoveredIdx(null);
        return;
      }

      // Find closest band
      let closestIdx = 0;
      let minDiff = Infinity;
      timeseries.forEach((_, i) => {
        const bandX = (xScale(i) ?? 0) + bandwidth / 2;
        const diff = Math.abs(mouseX - bandX);
        if (diff < minDiff) {
          minDiff = diff;
          closestIdx = i;
        }
      });
      setHoveredIdx(closestIdx);
    },
    [timeseries, innerWidth, xScale, bandwidth],
  );

  const activePoint = hoveredIdx !== null ? timeseries[hoveredIdx] : null;

  // Tooltip position (clamped inside inner bounds)
  const tooltipX = useMemo(() => {
    if (hoveredIdx === null) return 0;
    const bandX = (xScale(hoveredIdx) ?? 0) + bandwidth / 2 + MARGIN.left;
    return bandX;
  }, [hoveredIdx, xScale, bandwidth]);

  return (
    <div className="bklit-chart-root" style={{ position: "relative", width, height }}>
      <svg
        ref={containerRef}
        width={width}
        height={height}
        className="bklit-chart-svg"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoveredIdx(null)}
      >
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          {/* Horizontal Grid lines and Y axis ticks */}
          {yTicks.map((tick, i) => (
            <g key={`ytick-${i}`} className="bklit-grid-line-group">
              <line
                x1={0}
                x2={innerWidth}
                y1={tick.y}
                y2={tick.y}
                className="bklit-grid-line"
              />
              <text
                x={-8}
                y={tick.y + 3.5}
                className="bklit-axis-label-y"
                textAnchor="end"
              >
                {formatCompact(tick.value)}
              </text>
            </g>
          ))}

          {/* Hover highlight column band (Bklit underlay track) */}
          {hoveredIdx !== null && (
            <rect
              x={(xScale(hoveredIdx) ?? 0) - 2}
              y={0}
              width={bandwidth + 4}
              height={innerHeight}
              rx={6}
              className="bklit-hover-track"
            />
          )}

          {/* Data Bars */}
          {timeseries.map((point, idx) => {
            const x = xScale(idx) ?? 0;
            const barW = Math.max(4, Math.min(32, bandwidth));
            const xOffset = x + (bandwidth - barW) / 2;

            if (point.total === 0) {
              // Subtle zero-height indicator line at baseline
              return (
                <rect
                  key={`zero-${idx}`}
                  x={xOffset}
                  y={innerHeight - 2}
                  width={barW}
                  height={2}
                  rx={1}
                  className="bklit-bar-zero"
                />
              );
            }

            const promptRatio = point.total > 0 ? point.prompt / point.total : 0.8;
            const completionRatio = point.total > 0 ? point.completion / point.total : 0.2;

            const totalHeight = Math.max(4, innerHeight - (yScale(point.total) ?? innerHeight));
            const promptH = totalHeight * promptRatio;
            const completionH = totalHeight * completionRatio;

            const promptY = innerHeight - promptH;
            const completionY = promptY - completionH;

            const isHovered = hoveredIdx === idx;

            return (
              <g
                key={`bar-${idx}`}
                className={`bklit-bar-group ${isHovered ? "is-hovered" : ""}`}
              >
                {/* Prompt Segment (Bottom) */}
                <rect
                  x={xOffset}
                  y={promptY}
                  width={barW}
                  height={Math.max(1, promptH)}
                  rx={completionH < 1 ? 4 : 0}
                  className="bklit-bar-prompt"
                />
                {/* Completion / Output Segment (Top) */}
                {completionH > 0 && (
                  <rect
                    x={xOffset}
                    y={completionY}
                    width={barW}
                    height={Math.max(2, completionH)}
                    rx={3}
                    className="bklit-bar-completion"
                  />
                )}
              </g>
            );
          })}

          {/* X Axis Labels */}
          {timeseries.map((point, idx) => {
            if (!visibleXIndices.has(idx)) return null;
            const x = (xScale(idx) ?? 0) + bandwidth / 2;
            const isHovered = hoveredIdx === idx;

            return (
              <text
                key={`xlabel-${idx}`}
                x={x}
                y={innerHeight + 18}
                textAnchor="middle"
                className={`bklit-axis-label-x ${isHovered ? "is-active" : ""}`}
              >
                {point.label}
              </text>
            );
          })}
        </g>
      </svg>

      {/* Interactive Tooltip (Bklit UI Popover) */}
      {activePoint && hoveredIdx !== null && (
        <div
          className="bklit-chart-tooltip"
          style={{
            left: `${tooltipX}px`,
            transform:
              tooltipX < 140
                ? "translate(10px, -50%)"
                : tooltipX > width - 140
                  ? "translate(calc(-100% - 10px), -50%)"
                  : "translate(-50%, -105%)",
            top:
              tooltipX < 140 || tooltipX > width - 140
                ? `${MARGIN.top + innerHeight / 2}px`
                : `${Math.min(innerHeight * 0.7, (yScale(activePoint.total) ?? innerHeight / 2) + MARGIN.top)}px`,
          }}
        >
          <div className="bklit-tooltip-header">
            <span>{activePoint.label}</span>
            {activePoint.request_count > 0 && (
              <span className="bklit-tooltip-count">
                {activePoint.request_count} {activePoint.request_count === 1 ? "вызов" : "вызовов"}
              </span>
            )}
          </div>

          <div className="bklit-tooltip-row total-row">
            <span className="bklit-tooltip-label">Всего:</span>
            <strong className="bklit-tooltip-val text-total">
              {formatFullNum(activePoint.total)}
            </strong>
          </div>

          <div className="bklit-tooltip-row">
            <span className="bklit-tooltip-label">
              <span className="bklit-dot prompt-dot" />
              Prompt:
            </span>
            <span className="bklit-tooltip-val text-prompt">
              {formatFullNum(activePoint.prompt)}
            </span>
          </div>

          <div className="bklit-tooltip-row">
            <span className="bklit-tooltip-label">
              <span className="bklit-dot completion-dot" />
              Output:
            </span>
            <span className="bklit-tooltip-val text-completion">
              {formatFullNum(activePoint.completion)}
            </span>
          </div>

          {activePoint.cache_hit > 0 && (
            <div className="bklit-tooltip-row">
              <span className="bklit-tooltip-label">
                <span className="bklit-dot cache-dot" />
                Cache Hit:
              </span>
              <span className="bklit-tooltip-val text-hit">
                {formatFullNum(activePoint.cache_hit)}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function TokenUsageChart({ timeseries, timeframe }: TokenUsageChartProps) {
  const hasData = timeseries.length > 0 && timeseries.some((p) => p.total > 0 || p.request_count > 0);

  if (!hasData) {
    return (
      <div className="token-chart-empty">
        <Activity size={24} className="empty-icon" />
        <span>Нет данных о вызовах за выбранный период</span>
      </div>
    );
  }

  return (
    <div className="bklit-chart-container" style={{ width: "100%", height: 210 }}>
      <ParentSize debounceTime={15}>
        {({ width, height }) =>
          width > 40 && height > 40 ? (
            <ChartInnerSvg
              width={width}
              height={height}
              timeseries={timeseries}
              timeframe={timeframe}
            />
          ) : null
        }
      </ParentSize>
    </div>
  );
}
