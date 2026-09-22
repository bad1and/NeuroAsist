import { describe, expect, it } from "vitest";
import {
  calculateDeepSeekCostUsd,
  canonicalDeepSeekModel,
  isDeepSeekPeakTime,
} from "./deepseek";

const utc = (day: number, hour: number) => Date.UTC(2026, 8, day, hour) / 1000;

describe("DeepSeek API metadata", () => {
  it("normalizes retired and mistaken model identifiers", () => {
    expect(canonicalDeepSeekModel("deepseek-v4.1-flash")).toBe("deepseek-flash");
    expect(canonicalDeepSeekModel("deepseek-v4-flash")).toBe("deepseek-flash");
    expect(canonicalDeepSeekModel("deepseek-v4.1-pro")).toBe("deepseek-v4-pro");
  });

  it("detects weekday peak windows in UTC", () => {
    expect(isDeepSeekPeakTime(utc(21, 2))).toBe(true);
    expect(isDeepSeekPeakTime(utc(21, 5))).toBe(false);
    expect(isDeepSeekPeakTime(utc(21, 8))).toBe(true);
    expect(isDeepSeekPeakTime(utc(20, 2))).toBe(false);
  });

  it.each([
    ["deepseek-flash", 21, 1.506],
    ["deepseek-flash", 20, 0.753],
    ["deepseek-v4-pro", 21, 5.324],
    ["deepseek-v4-pro", 20, 2.662],
  ])("prices %s requests for the correct tier", (model, day, expected) => {
    expect(calculateDeepSeekCostUsd({
      model,
      timestamp: utc(day, 2),
      prompt_cache_hit_tokens: 1_000_000,
      prompt_cache_miss_tokens: 1_000_000,
      completion_tokens: 1_000_000,
    })).toBeCloseTo(expected);
  });
});
