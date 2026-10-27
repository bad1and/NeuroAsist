import type { TokenUsageTimeseriesPoint } from "../types";

export type UsageMetric = "tokens" | "requests" | "cache";
export const formatTokens = (value: number) => Math.round(value).toLocaleString("ru-RU").replace(/\u00a0/g, " ");
export const formatCompactTokens = (value: number) => new Intl.NumberFormat("ru-RU", {
  notation: "compact", maximumFractionDigits: 1,
}).format(value);

/** Cache hits are part of the input, never an additional part of the total. */
export function buildUsageData(points: TokenUsageTimeseriesPoint[], cumulative: boolean) {
  const sums = { total: 0, prompt: 0, completion: 0, cache_hit: 0, request_count: 0 };
  return [...points].filter(point => Number.isFinite(point.timestamp))
    .sort((a, b) => a.timestamp - b.timestamp).map(point => {
      const values = { ...point };
      for (const key of Object.keys(sums) as (keyof typeof sums)[]) {
        const amount = Number.isFinite(point[key]) ? Math.max(0, point[key]) : 0;
        sums[key] += amount;
        values[key] = cumulative ? sums[key] : amount;
      }
      return { ...values, date: new Date(point.timestamp * 1000) };
    });
}

export type UsageChartPoint = ReturnType<typeof buildUsageData>[number];
