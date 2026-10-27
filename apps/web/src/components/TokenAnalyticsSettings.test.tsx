// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent, waitFor, cleanup, act } from "@testing-library/react";
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

    expect(screen.getByRole("heading", { name: "Расходы и запросы" })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("kpi-total-tokens")).toHaveTextContent("12 450");
      expect(screen.getByTestId("kpi-cache-rate")).toHaveTextContent("80.0%");
      expect(screen.getByTestId("kpi-cost")).toHaveTextContent("$0.0035");
    });

    expect(screen.getByText("Активность Iris")).toBeInTheDocument();
    expect(screen.getByText("На что уходят токены")).toBeInTheDocument();
    expect(screen.getAllByText("Чат / Диалог").length).toBeGreaterThan(0);
    expect(screen.getByText("Использование моделей")).toBeInTheDocument();
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

  it("explains unavailable data instead of presenting zero expenses", async () => {
    api.getLlmTokenStats.mockRejectedValueOnce(new Error("Статистика недоступна"));
    render(<TokenAnalyticsSettings />);
    await screen.findByRole("alert");
    expect(screen.getByTestId("kpi-cost")).toHaveTextContent("—");
    expect(screen.getByText("График недоступен")).toBeInTheDocument();
    expect(screen.queryByText("Здесь появится активность")).not.toBeInTheDocument();
  });

  it("shows zero expenses and an empty chart when the period truly has no requests", async () => {
    api.getLlmTokenStats.mockResolvedValueOnce({ ...mockStats, total_tokens: 0, request_count: 0, estimated_cost_usd: 0,
      timeseries: [], by_purpose: {}, by_model: {} });
    render(<TokenAnalyticsSettings />);
    await screen.findByText("Здесь появится активность");
    expect(screen.getByTestId("kpi-cost")).toHaveTextContent("$0.0000");
  });

  it("ignores a late response from the previous period", async () => {
    let resolveOld!: (value: TokenUsageStats) => void;
    api.getLlmTokenStats.mockImplementation((timeframe: string) => timeframe === "24h"
      ? new Promise<TokenUsageStats>(resolve => { resolveOld = resolve; })
      : Promise.resolve({ ...mockStats, timeframe: "7d", total_tokens: 70000 }));
    render(<TokenAnalyticsSettings />);
    fireEvent.click(screen.getByRole("button", { name: "7 дн" }));
    await waitFor(() => expect(screen.getByTestId("kpi-total-tokens")).toHaveTextContent("70 000"));
    await act(async () => resolveOld(mockStats));
    expect(screen.getByTestId("kpi-total-tokens")).toHaveTextContent("70 000");
    expect(screen.getByRole("button", { name: "7 дн" })).toHaveAttribute("aria-pressed", "true");
  });

  it("opens the journal filtered by the selected chart purpose", async () => {
    render(<TokenAnalyticsSettings />);
    const purpose = await screen.findByRole("button", { name: /Чат \/ Диалог:.*Открыть запросы/ });
    fireEvent.click(purpose);
    await waitFor(() => expect(api.getLlmTokenRecords).toHaveBeenLastCalledWith(20, 0, "chat"));
    expect(screen.getByRole("button", { name: "Подробный журнал запросов" })).toHaveAttribute("aria-expanded", "true");
  });

  it("preserves the selected journal category after a statistics reset", async () => {
    render(<TokenAnalyticsSettings />);
    fireEvent.click(screen.getByText("Подробный журнал запросов"));
    fireEvent.click(screen.getByRole("tab", { name: "Память и рефлексия" }));
    await waitFor(() => expect(api.getLlmTokenRecords).toHaveBeenLastCalledWith(20, 0,
      "memory,reflection,memory_extraction,memory_synthesis,memory_conflict"));
    fireEvent.click(screen.getByTitle("Очистить журнал токенов"));
    fireEvent.click(screen.getByRole("button", { name: "Сбросить все данные токенов" }));
    await waitFor(() => expect(api.resetLlmTokenStats).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(api.getLlmTokenRecords).toHaveBeenLastCalledWith(20, 0,
      "memory,reflection,memory_extraction,memory_synthesis,memory_conflict"));
  });

  it("exposes chart metric and aggregation selection", async () => {
    render(<TokenAnalyticsSettings />);
    await waitFor(() => expect(screen.getByTestId("kpi-total-tokens")).toHaveTextContent("12 450"));
    fireEvent.click(screen.getByRole("button", { name: "Кэш" }));
    expect(screen.getByRole("button", { name: "Кэш" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Накопительно" }));
    expect(screen.getByRole("button", { name: "Накопительно" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Сумма с начала выбранного периода/)).toBeInTheDocument();
  });

  it("allows inspecting request details in dialog", async () => {
    render(<TokenAnalyticsSettings />);
    fireEvent.click(screen.getByText("Подробный журнал запросов"));
    await waitFor(() => expect(screen.getByTitle("Подробности запроса")).toBeInTheDocument());

    const inspectBtn = screen.getByTitle("Подробности запроса");
    fireEvent.click(inspectBtn);

    expect(screen.getByText("Подробности запроса")).toBeInTheDocument();
    expect(screen.getByText("Запрос: req-12345")).toBeInTheDocument();
    expect(screen.getByText("JSON записи")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "JSON запроса" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "JSON записи" }));
    expect(screen.getByRole("region", { name: "JSON запроса" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Копировать JSON" })).toBeInTheDocument();
  });

  it("keeps unknown token usage distinct from a measured zero", async () => {
    api.getLlmTokenRecords.mockResolvedValueOnce({ ...mockRecords, items: [{ ...mockRecords.items[0], usage_available: false, total: 0, prompt: 0, completion: 0, cache_hit: 0 }] });
    render(<TokenAnalyticsSettings />);
    fireEvent.click(screen.getByRole("button", { name: "Подробный журнал запросов" }));
    const record = await screen.findByRole("button", { name: /^Открыть запрос:/ });
    expect(record).toHaveTextContent("не учтены");
    expect(record).not.toHaveTextContent("200 OK");
    fireEvent.click(record);
    expect(screen.getByText("Модель не передала расход токенов для этого запроса.")).toBeInTheDocument();
  });

  it("loads the next page and returns to the first page on category change", async () => {
    api.getLlmTokenRecords.mockResolvedValue({ ...mockRecords, total: 44 });
    render(<TokenAnalyticsSettings />);
    fireEvent.click(screen.getByRole("button", { name: "Подробный журнал запросов" }));
    fireEvent.click(await screen.findByRole("button", { name: "Следующая страница запросов" }));
    await waitFor(() => expect(api.getLlmTokenRecords).toHaveBeenLastCalledWith(20, 20, undefined));
    fireEvent.click(screen.getByRole("tab", { name: "Память и рефлексия" }));
    await waitFor(() => expect(api.getLlmTokenRecords).toHaveBeenLastCalledWith(20, 0,
      "memory,reflection,memory_extraction,memory_synthesis,memory_conflict"));
  });

  it("retries a journal error without clearing the selected filters", async () => {
    api.getLlmTokenRecords.mockRejectedValueOnce(new Error("Сервис недоступен"));
    render(<TokenAnalyticsSettings />);
    fireEvent.click(screen.getByRole("button", { name: "Подробный журнал запросов" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить запросы");
    fireEvent.click(screen.getByRole("button", { name: "Попробовать снова" }));
    expect(await screen.findByRole("button", { name: /^Открыть запрос:/ })).toBeInTheDocument();
    expect(screen.queryByText("Сервис недоступен")).not.toBeInTheDocument();
  });

  it("retains the journal tab keyboard and accessibility contract", async () => {
    render(<TokenAnalyticsSettings />);
    fireEvent.click(screen.getByRole("button", { name: "Подробный журнал запросов" }));
    const all = screen.getByRole("tab", { name: "Все назначения" });
    all.focus();
    fireEvent.keyDown(all, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Диалог и голос" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Диалог и голос" })).toHaveFocus();
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
    fireEvent.click(screen.getByText("Подробный журнал запросов"));
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
