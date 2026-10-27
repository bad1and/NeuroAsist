// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getMemories: vi.fn(), getOpinions: vi.fn(), getOpinionHistory: vi.fn(), saveOpinion: vi.fn(), toggleOpinion: vi.fn() }));
vi.mock("./api", async original => ({ ...await original<typeof import("./api")>(), ...api }));
import { MemoryPage } from "./memory";

const item = { id: "cats", topic: "Кошки", stance: "Кошки мне нравятся.", reason: "Самостоятельный характер.", aliases: ["коты"], revision: 2, enabled: true, created_at: "2026-10-23T10:00:00Z", origin: "iris" };
beforeEach(() => {
  vi.clearAllMocks();
  api.getMemories.mockResolvedValue({ items: [] });
  api.getOpinions.mockResolvedValue({ items: [item], limit: 256 });
  api.getOpinionHistory.mockResolvedValue({ items: [{ ...item }, { ...item, revision: 1, stance: "Кошки мне не нравились.", reason: "Прежняя причина." }] });
  api.saveOpinion.mockResolvedValue({ item });
  api.toggleOpinion.mockResolvedValue({ updated: true });
});
afterEach(cleanup);

it("скрывает взгляды и не читает их без режима разработки", async () => {
  render(<MemoryPage />);
  await screen.findByText("Записей пока нет");
  expect(screen.queryByRole("button", { name: "Взгляды Iris" })).not.toBeInTheDocument();
  expect(api.getOpinions).not.toHaveBeenCalled();
});

it("показывает прежние версии и закрывает раздел при отключении режима", async () => {
  const view = render(<MemoryPage developerMode />);
  fireEvent.click(screen.getByRole("button", { name: "Взгляды Iris" }));
  await screen.findByText(item.stance);
  fireEvent.click(screen.getByRole("button", { name: "История изменений" }));
  await screen.findByText("Кошки мне не нравились.");
  expect(api.getOpinionHistory).toHaveBeenCalledWith("cats");
  view.rerender(<MemoryPage developerMode={false} />);
  await waitFor(() => expect(screen.queryByText(item.stance)).not.toBeInTheDocument());
  expect(screen.queryByText("Кошки мне не нравились.")).not.toBeInTheDocument();
});

it("пересмотр требует причину и передаёт текущую версию; ошибка не закрывает редактор", async () => {
  api.saveOpinion.mockRejectedValue(new Error("Позиция уже изменена. Обновите список."));
  render(<MemoryPage developerMode />);
  fireEvent.click(screen.getByRole("button", { name: "Взгляды Iris" }));
  await screen.findByText(item.stance);
  fireEvent.click(screen.getByRole("button", { name: "Пересмотреть" }));
  expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Позиция Iris"), { target: { value: "Теперь мне ближе собаки." } });
  fireEvent.change(screen.getByLabelText("Причина"), { target: { value: "Передумала после обсуждения." } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  await screen.findByRole("alert");
  expect(api.saveOpinion).toHaveBeenCalledWith(expect.objectContaining({ id: "cats", expected_revision: 2, reason: "Передумала после обсуждения." }));
  expect(screen.getByLabelText("Позиция Iris")).toHaveValue("Теперь мне ближе собаки.");
});

it("отключает позицию с проверкой версии", async () => {
  render(<MemoryPage developerMode />);
  fireEvent.click(screen.getByRole("button", { name: "Взгляды Iris" }));
  await screen.findByText(item.stance);
  fireEvent.click(screen.getByRole("button", { name: "Отключить" }));
  await waitFor(() => expect(api.toggleOpinion).toHaveBeenCalledWith("cats", false, 2));
});
