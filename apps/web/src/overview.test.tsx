// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { TimelineJournalItem } from "./types";

const api = vi.hoisted(() => ({ getTimelineJournal: vi.fn(), getTimelineMessages: vi.fn(), getConversationUsage: vi.fn(), getLlmTokenStats: vi.fn() }));
vi.mock("./api", async original => ({ ...await original<typeof import("./api")>(), ...api }));
import { OverviewPage, formatConversationTime } from "./overview";
import { JournalPage } from "./journal";

const episode: TimelineJournalItem = { id: "latest", session_id: "session", title: "Планы на выходные", day: "2026-10-25", started_at: "2026-10-25T12:00:00Z", last_activity_at: "2026-10-25T12:10:00Z", ended_at: "2026-10-25T12:11:00Z", message_count: 6 };
const props = () => ({ onOpenChat: vi.fn(), onOpenHistory: vi.fn(), onOpenMemory: vi.fn(), onOpenSettings: vi.fn() });
beforeEach(() => {
  vi.resetAllMocks();
  api.getTimelineJournal.mockResolvedValue({ items: [episode] });
  api.getConversationUsage.mockResolvedValue({ active_seconds: 3780, tracking_started_at: "2026-10-29T10:00:00Z" });
  api.getLlmTokenStats.mockResolvedValue({ total_tokens: 123456 });
  api.getTimelineMessages.mockResolvedValue({ items: [], next_offset: null });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

it("считает непустые разговоры и открывает последний эпизод", async () => {
  api.getTimelineJournal.mockResolvedValue({ items: [{ ...episode, id: "empty", last_activity_at: "2026-10-26T12:00:00Z", message_count: 0 }, episode, { ...episode, id: "older", last_activity_at: "2026-10-24T12:00:00Z" }] });
  const actions = props();
  render(<OverviewPage {...actions} />);
  expect(await screen.findByRole("heading", { name: episode.title! })).toBeInTheDocument();
  expect(screen.getByTestId("overview-stat-conversations-value")).toHaveTextContent("2");
  expect(screen.getByTestId("overview-stat-time-value")).toHaveTextContent("1 ч 3 мин");
  expect(screen.getByTestId("overview-stat-tokens-value")).toHaveTextContent(/123\s456/);
  expect(api.getLlmTokenStats).toHaveBeenCalledWith("all");
  fireEvent.click(screen.getByRole("button", { name: "Открыть разговор" }));
  expect(actions.onOpenHistory).toHaveBeenCalledWith(episode);
});

it("сохраняет остальные блоки при ошибке статистики и восстанавливает по повтору", async () => {
  api.getConversationUsage.mockRejectedValueOnce(new TypeError("offline"));
  render(<OverviewPage {...props()} />);
  await screen.findByRole("heading", { name: episode.title! });
  expect(screen.getByTestId("overview-stat-time-value")).toHaveTextContent("—");
  expect(screen.getByTestId("overview-stat-conversations-value")).toHaveTextContent("1");
  expect(screen.getByRole("region", { name: "Галерея" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Повторить загрузку: Время общения" }));
  await waitFor(() => expect(screen.getByTestId("overview-stat-time-value")).toHaveTextContent("1 ч 3 мин"));
});

it("не выдаёт ошибку истории за пустую историю и сохраняет последнюю беседу при повторном сбое", async () => {
  const actions = props();
  const view = render(<OverviewPage {...actions} />);
  await screen.findByRole("heading", { name: episode.title! });
  view.rerender(<OverviewPage {...actions} isActive={false} />);
  api.getTimelineJournal.mockRejectedValueOnce(new Error("offline"));
  view.rerender(<OverviewPage {...actions} isActive />);
  await screen.findByRole("button", { name: "Повторить загрузку: Разговоры" });
  expect(screen.getByRole("heading", { name: episode.title! })).toBeInTheDocument();
  expect(screen.getByTestId("overview-stat-conversations-value")).toHaveTextContent("—");
});

it("показывает последнюю реплику без служебных событий", async () => {
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

it("показывает нули и приглашение для нового пользователя", async () => {
  api.getTimelineJournal.mockResolvedValue({ items: [] });
  api.getConversationUsage.mockResolvedValue({ active_seconds: 0, tracking_started_at: "2026-10-29T10:00:00Z" });
  api.getLlmTokenStats.mockResolvedValue({ total_tokens: 0 });
  const actions = props();
  render(<OverviewPage {...actions} />);
  await screen.findByRole("heading", { name: "Первый разговор — впереди" });
  expect(screen.getByTestId("overview-stat-time-value")).toHaveTextContent("0 мин");
  expect(screen.getByTestId("overview-stat-tokens-value")).toHaveTextContent("0");
  fireEvent.click(screen.getByRole("button", { name: "Начать разговор" }));
  expect(actions.onOpenChat).toHaveBeenCalledOnce();
});

it("отклоняет некорректные данные статистики", async () => {
  api.getConversationUsage.mockResolvedValue({ active_seconds: -1, tracking_started_at: "invalid" });
  api.getLlmTokenStats.mockResolvedValue({ total_tokens: NaN });
  render(<OverviewPage {...props()} />);
  await screen.findByRole("heading", { name: episode.title! });
  expect(screen.getByTestId("overview-stat-time-value")).toHaveTextContent("—");
  expect(screen.getByTestId("overview-stat-tokens-value")).toHaveTextContent("—");
});

it("обновляет активный обзор раз в 30 секунд и останавливается в другой вкладке", async () => {
  vi.useFakeTimers();
  const actions = props();
  const view = render(<OverviewPage {...actions} />);
  await act(async () => {});
  expect(api.getConversationUsage).toHaveBeenCalledTimes(1);
  await act(async () => { vi.advanceTimersByTime(30_000); });
  expect(api.getConversationUsage).toHaveBeenCalledTimes(2);
  view.rerender(<OverviewPage {...actions} isActive={false} />);
  await act(async () => { vi.advanceTimersByTime(60_000); });
  expect(api.getConversationUsage).toHaveBeenCalledTimes(2);
  view.rerender(<OverviewPage {...actions} isActive />);
  await act(async () => {});
  expect(api.getConversationUsage).toHaveBeenCalledTimes(3);
});

it("не принимает запоздалый ответ с предыдущего открытия обзора", async () => {
  let resolveOld!: (value: { items: TimelineJournalItem[] }) => void;
  api.getTimelineJournal.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }));
  const actions = props();
  const view = render(<OverviewPage {...actions} />);
  view.rerender(<OverviewPage {...actions} isActive={false} />);
  view.rerender(<OverviewPage {...actions} isActive />);
  await screen.findByRole("heading", { name: episode.title! });
  await act(async () => { resolveOld({ items: [{ ...episode, title: "Устаревший ответ" }] }); });
  expect(screen.queryByText("Устаревший ответ")).not.toBeInTheDocument();
});

it("открывает переданную из обзора беседу в журнале, в том числе в StrictMode", async () => {
  api.getTimelineMessages.mockResolvedValue({ items: [{ id: "message", role: "assistant", content: "Ответ из выбранной беседы", original_content: "Ответ из выбранной беседы", status: "done", input_mode: "text", created_at: "2026-10-25T12:10:00Z" }], next_offset: null });
  render(<StrictMode><JournalPage episodeRequest={{ episode, requestId: "from-overview" }} /></StrictMode>);
  expect(await screen.findByText("Ответ из выбранной беседы")).toBeInTheDocument();
  expect(api.getTimelineMessages).toHaveBeenCalledWith(200, "session", "latest");
});

it("перелистывает галерею и просмотр клавиатурой, закрывает Escape и возвращает фокус", async () => {
  vi.useFakeTimers();
  render(<OverviewPage {...props()} />);
  await act(async () => {});
  const opener = screen.getByRole("button", { name: "Открыть изображение: Пастельный портрет" });
  opener.focus();
  fireEvent.click(opener);
  const dialog = screen.getByRole("dialog", { name: "Пастельный портрет" });
  expect(within(dialog).getByRole("img", { name: /Мягкий портрет Iris/ })).toBeInTheDocument();
  fireEvent.keyDown(within(dialog).getByRole("button", { name: "Закрыть диалог" }), { key: "ArrowLeft" });
  const lastArtwork = screen.getByRole("dialog", { name: "Всегда рядом" });
  expect(within(lastArtwork).getByRole("img", { name: /Iris на светло-голубом фоне/ })).toBeInTheDocument();
  fireEvent.keyDown(within(lastArtwork).getByRole("button", { name: "Закрыть диалог" }), { key: "ArrowRight" });
  expect(screen.getByRole("dialog", { name: "Пастельный портрет" })).toBeInTheDocument();
  fireEvent.keyDown(within(dialog).getByRole("button", { name: "Закрыть диалог" }), { key: "ArrowRight" });
  expect(screen.getByRole("dialog", { name: "Под открытым небом" })).toBeInTheDocument();
  fireEvent.keyDown(window, { key: "Escape" });
  await act(async () => { vi.advanceTimersByTime(220); });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(opener).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: "Следующие изображения" }));
  expect(document.querySelector(".overview-gallery-track button")).toHaveAccessibleName("Открыть изображение: Под открытым небом");
});

it("сохраняет карточку галереи при отсутствии файла", async () => {
  render(<OverviewPage {...props()} />);
  await screen.findByRole("heading", { name: episode.title! });
  const opener = screen.getByRole("button", { name: "Открыть изображение: Пастельный портрет" });
  fireEvent.error(within(opener).getByRole("img"));
  expect(within(opener).getByText("Изображение недоступно")).toBeInTheDocument();
  expect(opener).toBeEnabled();
});

it("перелистывает советы по кругу и с клавиатуры, сохраняя фокус", async () => {
  render(<StrictMode><OverviewPage {...props()} /></StrictMode>);
  await screen.findByRole("heading", { name: episode.title! });
  const next = screen.getByRole("button", { name: "Следующий совет" });
  next.focus();
  fireEvent.keyDown(next, { key: "End" });
  expect(screen.getByRole("heading", { name: "Интересный факт" })).toBeInTheDocument();
  expect(next).toHaveFocus();
  fireEvent.click(next);
  expect(screen.getByRole("heading", { name: "Пусть Iris звучит по-вашему" })).toBeInTheDocument();
  fireEvent.keyDown(next, { key: "ArrowLeft" });
  expect(screen.getByText("Совет 8 из 8")).toBeInTheDocument();
});

it("открывает память и конкретные настройки из советов", async () => {
  const actions = props();
  render(<OverviewPage {...actions} />);
  await screen.findByRole("heading", { name: episode.title! });
  const next = screen.getByRole("button", { name: "Следующий совет" });
  fireEvent.click(screen.getByRole("button", { name: "Настроить голос" }));
  expect(actions.onOpenSettings).toHaveBeenLastCalledWith("voice", undefined);
  fireEvent.click(next);
  fireEvent.click(screen.getByRole("button", { name: "Посмотреть память" }));
  expect(actions.onOpenMemory).toHaveBeenCalledOnce();
  for (const [label, section, focusId] of [
    ["Выбрать сочетания", "shortcuts", undefined], ["Открыть словарь", "voice", "voice-pronunciations"],
    ["Перейти к инкогнито", "memory", "memory-incognito"], ["Настроить поиск", "internet", undefined], ["Открыть резервные копии", "backups", undefined],
  ] as const) {
    fireEvent.click(next);
    fireEvent.click(screen.getByRole("button", { name: label }));
    expect(actions.onOpenSettings).toHaveBeenLastCalledWith(section, focusId);
  }
});

it("форматирует длительность без выдуманного исторического времени", () => {
  expect(formatConversationTime(0)).toBe("0 мин");
  expect(formatConversationTime(15)).toBe("< 1 мин");
  expect(formatConversationTime(3600)).toBe("1 ч");
  expect(formatConversationTime(3720)).toBe("1 ч 2 мин");
});
