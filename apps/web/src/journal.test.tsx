// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  requestJson: vi.fn(),
  getTimelineJournal: vi.fn(),
  getTimelineMessages: vi.fn(),
  deleteTimelineRange: vi.fn(),
  searchTimeline: vi.fn(),
}));
vi.mock("./api", () => api);

import { JournalPage } from "./journal";
import { StrictMode } from "react";

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
          web_search: {
            query: "актуальная версия Python",
            searched_at: "2026-09-18T03:00:30Z",
            provider: "duckduckgo",
            status: "ok",
            cached: false,
            sources: [{ title: "Python.org", url: "https://www.python.org/" }],
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
  it("opens the exact global-search result through StrictMode mount replay", async () => {
    const target = { id: "target", role: "user", content: "Exact target", created_at: "2026-10-19T10:00:00Z", metadata: {} };
    api.requestJson.mockResolvedValue({ episode: { id: "ep-1", day: "2026-10-19", message_count: 1 }, items: [target], next_offset: null });
    render(<StrictMode><JournalPage focusRequest={{ requestId: "search-1", id: "target", query: "exact" }} /></StrictMode>);
    expect(await screen.findByText("Exact target")).toBeInTheDocument();
    await waitFor(() => expect(document.getElementById("history-message-target")).toHaveFocus());
    expect(screen.getByRole("button", { name: "Показать полный диалог" })).toBeInTheDocument();
  });

  it("shows real memory-context access only in developer mode", async () => {
    api.getTimelineMessages.mockResolvedValue({ items: [{ id: "reply", role: "assistant", content: "Ответ", created_at: "2026-09-18T03:01:00Z", metadata: { context_memories: [{ id: "memory", value: "Факт" }] } }], next_offset: null });
    const view = render(<JournalPage developerMode={false} />);
    fireEvent.click((await screen.findAllByText("18 сентября 2026 г."))[0]);
    await screen.findByText("Ответ");
    expect(screen.queryByRole("button", { name: /записей памяти · DEV/ })).not.toBeInTheDocument();
    view.rerender(<JournalPage developerMode />);
    expect(screen.getByRole("button", { name: /В контексте 1 записей памяти · DEV/ })).toBeInTheDocument();
  });
  it("discards an old page after selecting a different episode", async () => {
    api.getTimelineJournal.mockResolvedValue({ items: [
      { id: "A", title: "Episode A", day: "2026-09-18", message_count: 201 },
      { id: "B", title: "Episode B", day: "2026-09-19", message_count: 1 },
    ] });
    let resolvePage!: (value: unknown) => void;
    api.getTimelineMessages.mockImplementation(async (_limit, _session, episode, offset) => {
      if (offset) return new Promise(resolve => { resolvePage = resolve; });
      return { items: [{ id: episode, role: "user", content: `Message ${episode}`, created_at: "2026-09-18T03:00:00Z" }], next_offset: episode === "A" ? 200 : null };
    });
    render(<JournalPage />);
    fireEvent.click(await screen.findByText("Episode A"));
    await screen.findByText("Message A");
    fireEvent.click(screen.getByRole("button", { name: "Загрузить более ранние сообщения" }));
    fireEvent.click(screen.getAllByText("Episode B")[0]);
    await screen.findByText("Message B");
    await act(async () => resolvePage({ items: [{ id: "old-A", role: "user", content: "Stale A" }], next_offset: 300 }));
    expect(screen.queryByText("Stale A")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Загрузить более ранние сообщения" })).not.toBeInTheDocument();
  });

  it("discards a search response after clearing its query", async () => {
    let resolveSearch!: (value: unknown) => void;
    api.searchTimeline.mockImplementation(() => new Promise(resolve => { resolveSearch = resolve; }));
    render(<JournalPage />);
    const input = screen.getByRole("textbox", { name: "Поиск по истории" });
    fireEvent.change(input, { target: { value: "old query" } });
    fireEvent.submit(input.closest("form")!);
    fireEvent.click(screen.getByRole("button", { name: "Очистить поле поиска" }));
    await act(async () => resolveSearch({ items: [{ id: "old", role: "user", content: "Outdated result" }] }));
    expect(screen.queryByText("Outdated result")).not.toBeInTheDocument();
  });

  it("shows news sources and stale dates even without token metadata", async () => {
    api.getTimelineMessages.mockResolvedValueOnce({ items: [{
      id: "news-1", role: "assistant", content: "Новости науки", created_at: "2026-09-18T03:01:00Z",
      metadata: { news: { query: "Новости: science", provider: "rss", status: "ok", cached: true,
        stale: true, sources: [{ title: "NASA discovery", url: "https://www.nasa.gov/discovery/", published_at: "2026-09-18T00:00:00Z" }] } },
    }], next_offset: null });
    render(<JournalPage />);
    fireEvent.click((await screen.findAllByText("18 сентября 2026 г."))[0]);
    await screen.findByText("Новости науки");
    fireEvent.click(screen.getByRole("button", { name: "Подробнее" }));
    expect(screen.getByText("Новости")).toBeInTheDocument();
    expect(screen.getByText(/данные могут устареть/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /NASA discovery/ })).toHaveAttribute("href", "https://www.nasa.gov/discovery/");
    expect(screen.getByText(/2026-09-18/)).toBeInTheDocument();
  });

  it("expands token details inline from an individual history message", async () => {
    render(<JournalPage />);

    const episodeCards = await screen.findAllByText("18 сентября 2026 г.");
    fireEvent.click(episodeCards[0]);
    expect(await screen.findByText("Привет! Чем могу помочь?")).toBeInTheDocument();

    const detailButtons = screen.getAllByRole("button", { name: "Подробнее" });
    fireEvent.click(detailButtons[1]);

    expect(screen.getByText("Параметры вызова LLM")).toBeInTheDocument();
    expect(screen.getByText("В ответе")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Свернуть" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Поиск в интернете")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Python.org/ })).toHaveAttribute("href", "https://www.python.org/");
  });

  it("keeps message text selectable and opens statistics through its explicit button", async () => {
    render(<JournalPage />);

    // Select episode
    const episodeCards = await screen.findAllByText("18 сентября 2026 г.");
    fireEvent.click(episodeCards[0]);

    // Wait for messages to load
    expect(await screen.findByText("Привет! Чем могу помочь?")).toBeInTheDocument();

    const messageText = screen.getByText("Привет! Чем могу помочь?");
    fireEvent.click(messageText);
    expect(screen.queryByText("Статистика токенов")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Токены ответа" }));

    // Token statistics dialog must appear
    expect(await screen.findByText("Статистика токенов")).toBeInTheDocument();
    expect(screen.getByText("deepseek-flash")).toBeInTheDocument();
    expect(screen.getByText("На входе")).toBeInTheDocument();
    expect(screen.getByText("В ответе")).toBeInTheDocument();

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
    const badge = screen.getByRole("button", { name: "Токены ответа" });
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
    expect(screen.getByText("2 сообщения")).toBeInTheDocument();
    expect(headerTokenBtn).toHaveTextContent("408 ток.");
    fireEvent.click(headerTokenBtn);

    expect(await screen.findByText("Статистика токенов")).toBeInTheDocument();
  });
});
