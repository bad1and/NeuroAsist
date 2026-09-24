// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getTimelineJournal: vi.fn(),
  getTimelineMessages: vi.fn(),
  deleteTimelineRange: vi.fn(),
  searchTimeline: vi.fn(),
}));
vi.mock("./api", () => api);

import { JournalPage } from "./journal";

beforeEach(() => {
  api.getTimelineJournal.mockResolvedValue({
    items: [
      {
        id: "ep-1",
        day: "2026-09-18",
        message_count: 2,
        started_at: "2026-09-18T03:00:00Z",
        last_activity_at: "2026-09-18T03:04:00Z",
        token_estimate: 408,
      },
    ],
  });

  api.getTimelineMessages.mockResolvedValue({
    items: [
      {
        id: "msg-1",
        role: "user",
        content: "Привет!",
        created_at: "2026-09-18T03:00:00Z",
        metadata: {
          tokens: {
            prompt_tokens: 120,
            total_tokens: 120,
          },
        },
      },
      {
        id: "msg-2",
        role: "assistant",
        content: "Привет! Чем могу помочь?",
        created_at: "2026-09-18T03:01:00Z",
        metadata: {
          tokens: {
            prompt_tokens: 120,
            completion_tokens: 288,
            total_tokens: 408,
            model: "deepseek-flash",
          },
        },
      },
    ],
    next_offset: null,
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("JournalPage token dialog interaction", () => {
  it("expands token details inline from an individual history message", async () => {
    render(<JournalPage />);

    const episodeCards = await screen.findAllByText("18 сентября 2026 г.");
    fireEvent.click(episodeCards[0]);
    expect(await screen.findByText("Привет! Чем могу помочь?")).toBeInTheDocument();

    const detailButtons = screen.getAllByRole("button", { name: "Подробнее" });
    fireEvent.click(detailButtons[1]);

    expect(screen.getByText("Параметры вызова LLM")).toBeInTheDocument();
    expect(screen.getByText("Output (генерация)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Свернуть" })).toHaveAttribute("aria-expanded", "true");
  });

  it("opens token statistics dialog when clicking on a message with tokens", async () => {
    render(<JournalPage />);

    // Select episode
    const episodeCards = await screen.findAllByText("18 сентября 2026 г.");
    fireEvent.click(episodeCards[0]);

    // Wait for messages to load
    expect(await screen.findByText("Привет! Чем могу помочь?")).toBeInTheDocument();

    // Click on the assistant message text or container
    const messageText = screen.getByText("Привет! Чем могу помочь?");
    fireEvent.click(messageText);

    // Token statistics dialog must appear
    expect(await screen.findByText("Статистика токенов")).toBeInTheDocument();
    expect(screen.getByText("deepseek-flash")).toBeInTheDocument();
    expect(screen.getByText("Входящие (Prompt)")).toBeInTheDocument();
    expect(screen.getByText("Исходящие (Output)")).toBeInTheDocument();

    // Close via Понятно
    fireEvent.click(screen.getByRole("button", { name: "Понятно" }));
    await waitFor(() => {
      expect(screen.queryByText("Статистика токенов")).not.toBeInTheDocument();
    });
  });

  it("opens token statistics dialog when clicking the token badge", async () => {
    render(<JournalPage />);

    const episodeCards = await screen.findAllByText("18 сентября 2026 г.");
    fireEvent.click(episodeCards[0]);

    expect(await screen.findByText("Привет! Чем могу помочь?")).toBeInTheDocument();

    // Click on the token badge button
    const badge = screen.getByRole("button", { name: /Токены: 288 out/i });
    fireEvent.click(badge);

    expect(await screen.findByText("Статистика токенов")).toBeInTheDocument();
    expect(screen.getByText("deepseek-flash")).toBeInTheDocument();

    // Close via close X button
    const closeBtn = screen.getByRole("button", { name: "Закрыть диалог" });
    fireEvent.click(closeBtn);
    await waitFor(() => {
      expect(screen.queryByText("Статистика токенов")).not.toBeInTheDocument();
    });
  });

  it("opens token statistics dialog when clicking the episode header token count", async () => {
    render(<JournalPage />);

    const episodeCards = await screen.findAllByText("18 сентября 2026 г.");
    fireEvent.click(episodeCards[0]);

    expect(await screen.findByText("Привет! Чем могу помочь?")).toBeInTheDocument();

    // Click on the header token button
    const headerTokenBtn = await screen.findByTitle("Нажмите для просмотра статистики токенов диалога");
    fireEvent.click(headerTokenBtn);

    expect(await screen.findByText("Статистика токенов")).toBeInTheDocument();
  });
});
