// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const api = vi.hoisted(() => ({
  getLlmTokenStats: vi.fn(),
  getLlmTokenRecords: vi.fn(),
  resetLlmTokenStats: vi.fn(),
}));

vi.mock("../api", () => api);

import { TokenAnalyticsSettings } from "./TokenAnalyticsSettings";
import type { TokenUsageStats, TokenRecordsResponse } from "../types";

const mockStats: TokenUsageStats = {
  timeframe: "24h",
  total_tokens: 12450,
  prompt_tokens: 10200,
  completion_tokens: 2250,
  reasoning_tokens: 450,
  cache_hit_tokens: 8160,
  cache_miss_tokens: 2040,
  cache_hit_rate: 80.0,
  request_count: 15,
  success_count: 15,
  error_count: 0,
  latency_avg_ms: 380,
  latency_p95_ms: 620,
  estimated_cost_usd: 0.0035,
  by_purpose: {
    chat: { request_count: 10, prompt: 7000, completion: 1500, total: 8500, cache_hit: 5600 },
    live: { request_count: 5, prompt: 3200, completion: 750, total: 3950, cache_hit: 2560 },
  },
  by_model: {
    "deepseek-flash": { request_count: 15, prompt: 10200, completion: 2250, total: 12450 },
  },
  timeseries: [
    { timestamp: 1000, label: "12:00", total: 4500, prompt: 3500, completion: 1000, cache_hit: 2800, request_count: 5 },
    { timestamp: 2000, label: "13:00", total: 7950, prompt: 6700, completion: 1250, cache_hit: 5360, request_count: 10 },
  ],
};

const mockRecords: TokenRecordsResponse = {
  items: [
    {
      timestamp: 2000,
      request_id: "req-12345",
      purpose: "chat",
      model: "deepseek-flash",
      streaming: true,
      thinking: false,
      max_tokens: 4096,
      message_count: 4,
      input_chars: 1200,
      usage_available: true,
      prompt: 1200,
      completion: 180,
      total: 1380,
      reasoning: 0,
      cache_hit: 960,
      cache_miss: 240,
      latency_ms: 320,
      finish_reason: "stop",
      status: "success",
      logical_attempt: 1,
    },
  ],
  total: 1,
  limit: 20,
  offset: 0,
};

describe("TokenAnalyticsSettings component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getLlmTokenStats.mockResolvedValue(mockStats);
    api.getLlmTokenRecords.mockResolvedValue(mockRecords);
    api.resetLlmTokenStats.mockResolvedValue({ status: "cleared", cleared_records: 1 });
  });

  afterEach(() => {
    cleanup();
  });

  it("renders header, KPI cards, and breakdowns", async () => {
    render(<TokenAnalyticsSettings />);

    expect(screen.getByText("Токены и расходы LLM")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("kpi-total-tokens")).toHaveTextContent("12 450");
      expect(screen.getByTestId("kpi-cache-rate")).toHaveTextContent("80.0%");
      expect(screen.getByTestId("kpi-cost")).toHaveTextContent("$0.0035");
    });

    expect(screen.getByText("Динамика расхода токенов")).toBeInTheDocument();
    expect(screen.getByText("Распределение по назначению")).toBeInTheDocument();
    expect(screen.getAllByText("Чат / Диалог").length).toBeGreaterThan(0);
    expect(screen.getByText("Распределение по моделям")).toBeInTheDocument();
    expect(screen.getAllByText("deepseek-flash").length).toBeGreaterThan(0);
  });

  it("changes timeframe and reloads stats", async () => {
    render(<TokenAnalyticsSettings />);
    await waitFor(() => expect(api.getLlmTokenStats).toHaveBeenCalledWith("24h"));

    const btn7d = screen.getByRole("button", { name: "7 дн" });
    fireEvent.click(btn7d);

    await waitFor(() => {
      expect(api.getLlmTokenStats).toHaveBeenCalledWith("7d");
    });
  });

  it("allows inspecting request details in dialog", async () => {
    render(<TokenAnalyticsSettings />);
    await waitFor(() => expect(screen.getByTitle("Просмотреть сырой JSON")).toBeInTheDocument());

    const inspectBtn = screen.getByTitle("Просмотреть сырой JSON");
    fireEvent.click(inspectBtn);

    expect(screen.getByText("Сырые метрики вызова LLM")).toBeInTheDocument();
    expect(screen.getByText("Запрос: req-12345")).toBeInTheDocument();
    expect(screen.getByText("Сырой объект записи")).toBeInTheDocument();
  });

  it("shows confirmation modal and resets statistics", async () => {
    render(<TokenAnalyticsSettings />);
    await waitFor(() => expect(screen.getByTestId("kpi-total-tokens")).toHaveTextContent("12 450"));

    const resetBtn = screen.getByTitle("Очистить журнал токенов");
    fireEvent.click(resetBtn);

    expect(screen.getByText("Сбросить статистику токенов?")).toBeInTheDocument();
    const confirmBtn = screen.getByRole("button", { name: "Сбросить все данные токенов" });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(api.resetLlmTokenStats).toHaveBeenCalled();
    });
  });

  it("filters records by clicking category tabs", async () => {
    render(<TokenAnalyticsSettings />);
    await waitFor(() => expect(api.getLlmTokenRecords).toHaveBeenCalled());

    const memoryTab = screen.getByRole("tab", { name: "Память и рефлексия" });
    fireEvent.click(memoryTab);

    await waitFor(() => {
      expect(api.getLlmTokenRecords).toHaveBeenCalledWith(
        20,
        0,
        "memory,reflection,memory_extraction,memory_synthesis,memory_conflict",
      );
    });
  });
});
