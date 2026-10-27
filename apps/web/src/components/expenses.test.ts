import { describe, expect, it } from "vitest";
import { buildUsageData } from "./expenses";
import type { TokenUsageTimeseriesPoint } from "../types";

const points: TokenUsageTimeseriesPoint[] = [
  { timestamp: 20, label: "Второй", total: 150, prompt: 100, completion: 50, cache_hit: 80, request_count: 2 },
  { timestamp: 10, label: "Первый", total: 100, prompt: 90, completion: 10, cache_hit: 60, request_count: 1 },
];
describe("expense chart data", () => {
  it("orders intervals without changing server data", () => {
    const before = JSON.stringify(points);
    const result = buildUsageData(points, false);
    expect(result.map(point => point.total)).toEqual([100, 150]);
    expect(result[0].date.getTime()).toBe(10_000);
    expect(JSON.stringify(points)).toBe(before);
  });
  it("accumulates tokens and requests, keeping cached input a subset", () => {
    const result = buildUsageData(points, true);
    expect(result[1]).toMatchObject({ total: 250, prompt: 190, completion: 60, cache_hit: 140, request_count: 3 });
    expect(result[1].total).toBe(result[1].prompt + result[1].completion);
  });
  it("keeps genuine zero intervals and a single point without manufacturing activity", () => {
    expect(buildUsageData([], true)).toEqual([]);
    expect(buildUsageData([points[0]], false)).toHaveLength(1);
    const result = buildUsageData([{ ...points[0], total: 0, prompt: 0, completion: 0, cache_hit: 0, request_count: 0 }], false);
    expect(result[0].total).toBe(0);
  });
});
