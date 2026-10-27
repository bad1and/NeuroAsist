// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { MemoryItem, StatusResponse, TimelineJournalItem } from "./types";

const api = vi.hoisted(() => ({ getTimelineJournal: vi.fn(), getMemories: vi.fn(), getReminders: vi.fn(), getTimelineMessages: vi.fn() }));
vi.mock("./api", async original => ({ ...await original<typeof import("./api")>(), ...api }));
vi.mock("./product-api", () => ({ getReminders: api.getReminders }));
import { OverviewPage } from "./overview";
import { JournalPage } from "./journal";

const episode: TimelineJournalItem = { id: "latest", session_id: "session", title: "Планы на выходные", day: "2026-10-25", started_at: "2026-10-25T12:00:00Z", last_activity_at: "2026-10-25T12:10:00Z", ended_at: "2026-10-25T12:11:00Z", message_count: 6 };
const memory: MemoryItem = { id: "memory", scope: "user", kind: "fact", subject: "user", predicate: "likes", value_text: "Люблю прогулки у воды.", importance: 1, confidence: 1, sensitivity: "normal", status: "active", user_locked: false, source_message_ids: [], created_at: "2026-10-25T10:00:00Z", updated_at: "2026-10-25T10:00:00Z", access_count: 0 };
const status = { backend: "ok", api_key_configured: true } as StatusResponse;
const props = () => ({ status, avatarStatus: null, onOpenChat: vi.fn(), onOpenHistory: vi.fn(), onOpenMemory: vi.fn(), onOpenSettings: vi.fn(), onOpenPlans: vi.fn() });
beforeEach(() => {
  vi.resetAllMocks();
  api.getTimelineJournal.mockResolvedValue({ items: [episode] });
  api.getMemories.mockResolvedValue({ items: [] });
  api.getReminders.mockResolvedValue({ items: [] });
  api.getTimelineMessages.mockResolvedValue({ items: [], next_offset: null });
});
afterEach(cleanup);

it("открывает последний непустой разговор, минуя список истории", async () => {
  api.getTimelineJournal.mockResolvedValue({ items: [{ ...episode, id: "empty", last_activity_at: "2026-10-26T12:00:00Z", message_count: 0 }, episode] });
  const actions = props();
  render(<OverviewPage {...actions} />);
  expect(await screen.findByRole("heading", { name: episode.title! })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Открыть разговор" }));
  expect(actions.onOpenHistory).toHaveBeenCalledWith(episode);
});

it("сохраняет историю при ошибке памяти и восстанавливает память по повтору", async () => {
  api.getMemories.mockRejectedValueOnce(new TypeError("offline"));
  render(<OverviewPage {...props()} />);
  expect(await screen.findByRole("heading", { name: episode.title! })).toBeInTheDocument();
  expect(screen.getByText("Память недоступна")).toBeInTheDocument();
  expect(screen.queryByText("Начинаем знакомство")).not.toBeInTheDocument();
  api.getMemories.mockResolvedValue({ items: [memory] });
  fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
  expect(await screen.findByText(memory.value_text)).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("открывает выбранную предыдущую беседу из списка недавних", async () => {
  const earlier = { ...episode, id: "earlier", title: "Разговор о музыке", last_activity_at: "2026-10-24T12:10:00Z" };
  api.getTimelineJournal.mockResolvedValue({ items: [earlier, episode] });
  const actions = props();
  render(<OverviewPage {...actions} />);
  fireEvent.click(await screen.findByRole("button", { name: /Разговор о музыке/ }));
  expect(actions.onOpenHistory).toHaveBeenCalledWith(earlier);
});

it("показывает последнюю реплику беседы без служебных событий", async () => {
  api.getTimelineMessages.mockResolvedValue({ items: [
    { id: "user", role: "user", content: "Хочу выбраться за город" },
    { id: "reply", role: "assistant", content: "Давай выберем маршрут" },
    { id: "system", role: "system_event", content: "Внутреннее событие" },
  ] });
  render(<OverviewPage {...props()} />);
  expect(await screen.findByText("Давай выберем маршрут")).toBeInTheDocument();
  expect(screen.queryByText("Внутреннее событие")).not.toBeInTheDocument();
  expect(api.getTimelineMessages).toHaveBeenCalledWith(4, "session", "latest");
});

it("не показывает чувствительные и отклонённые записи в превью и отмечает неполный счётчик", async () => {
  api.getMemories.mockResolvedValue({ items: [memory, { ...memory, id: "secret", sensitivity: "sensitive", value_text: "Секрет", updated_at: "2026-10-26T12:00:00Z" }, { ...memory, id: "rejected", status: "rejected", value_text: "Неверный факт", updated_at: "2026-10-26T13:00:00Z" }], next_offset: 100 });
  render(<OverviewPage {...props()} />);
  expect(await screen.findByText(memory.value_text)).toBeInTheDocument();
  expect(screen.getByText("2+ сохранено")).toBeInTheDocument();
  expect(screen.queryByText("Секрет")).not.toBeInTheDocument();
  expect(screen.queryByText("Неверный факт")).not.toBeInTheDocument();
});

it("выбирает ближайшее открытое напоминание и обновляет его при возврате", async () => {
  api.getReminders.mockResolvedValue({ items: [
    { id: "later", title: "Позже", status: "open", due_at: "2027-01-03T12:00:00Z" },
    { id: "done", title: "Уже сделано", status: "completed", due_at: "2027-01-01T12:00:00Z" },
    { id: "next", title: "Важная встреча", status: "open", due_at: "2027-01-02T12:00:00Z" },
  ] });
  const actions = props();
  const view = render(<OverviewPage {...actions} />);
  expect(await screen.findByText("Важная встреча")).toBeInTheDocument();
  expect(screen.queryByText("Позже")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Планы и обещания" }));
  expect(actions.onOpenPlans).toHaveBeenCalledOnce();
  view.rerender(<OverviewPage {...actions} isActive={false} />);
  api.getReminders.mockResolvedValue({ items: [] });
  view.rerender(<OverviewPage {...actions} isActive />);
  await waitFor(() => expect(screen.queryByText("Важная встреча")).not.toBeInTheDocument());
});

it("показывает три последних разных воспоминания без повторов", async () => {
  api.getMemories.mockResolvedValue({ items: [
    { ...memory, id: "oldest", value_text: "Старая запись", updated_at: "2026-10-21T10:00:00Z" },
    { ...memory, id: "third", value_text: "Третья запись", updated_at: "2026-10-22T10:00:00Z" },
    { ...memory, id: "second", value_text: "Вторая запись", updated_at: "2026-10-23T10:00:00Z" },
    { ...memory, id: "duplicate", value_text: "  ЛЮБЛЮ   ПРОГУЛКИ У ВОДЫ. ", updated_at: "2026-10-24T10:00:00Z" },
    memory,
  ] });
  render(<OverviewPage {...props()} />);
  const first = await screen.findByText(memory.value_text);
  expect(first.closest("ul")?.children).toHaveLength(3);
  expect(screen.getByText("Вторая запись")).toBeInTheDocument();
  expect(screen.getByText("Третья запись")).toBeInTheDocument();
  expect(screen.queryByText("Старая запись")).not.toBeInTheDocument();
  expect(screen.queryByText(/ЛЮБЛЮ/)).not.toBeInTheDocument();
});

it("не принимает запоздалый ответ с предыдущего открытия обзора", async () => {
  let resolveOld!: (value: { items: TimelineJournalItem[] }) => void;
  api.getTimelineJournal.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }));
  const actions = props();
  const view = render(<OverviewPage {...actions} />);
  view.rerender(<OverviewPage {...actions} isActive={false} />);
  view.rerender(<OverviewPage {...actions} isActive />);
  expect(await screen.findByRole("heading", { name: episode.title! })).toBeInTheDocument();
  resolveOld({ items: [{ ...episode, title: "Устаревший ответ" }] });
  await waitFor(() => expect(screen.queryByText("Устаревший ответ")).not.toBeInTheDocument());
});

it("открывает переданную из обзора беседу в журнале, в том числе в StrictMode", async () => {
  api.getTimelineMessages.mockResolvedValue({ items: [{ id: "message", role: "assistant", content: "Ответ из выбранной беседы", original_content: "Ответ из выбранной беседы", status: "done", input_mode: "text", created_at: "2026-10-25T12:10:00Z" }], next_offset: null });
  render(<StrictMode><JournalPage episodeRequest={{ episode, requestId: "from-overview" }} /></StrictMode>);
  expect(await screen.findByText("Ответ из выбранной беседы")).toBeInTheDocument();
  expect(api.getTimelineMessages).toHaveBeenCalledWith(200, "session", "latest");
});
