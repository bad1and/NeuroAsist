// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getMemories: vi.fn(), getMemeLibrary: vi.fn(), saveMemeCard: vi.fn(), deleteMemeCard: vi.fn(),
}));
vi.mock("./api", async importOriginal => ({ ...await importOriginal<typeof import("./api")>(), ...api }));
import { MemoryPage } from "./memory";

const card = { id: "m1", name: "Мем для теста", summary: "Ироничная реакция на рабочий завал.", tags: "работа", source: "https://example.org/meme", kind: "curated" as const, checked_at: "2026-10-14", published_at: "2026-09-30", enabled: true };
beforeEach(() => {
  vi.clearAllMocks();
  api.getMemories.mockResolvedValue({ items: [] });
  api.getMemeLibrary.mockResolvedValue({ items: [card], limit: 48 });
  api.saveMemeCard.mockResolvedValue({ item: card });
  api.deleteMemeCard.mockResolvedValue({ deleted: true });
});
afterEach(cleanup);

describe("Мемотека в режиме разработчика", () => {
  it("по умолчанию скрыта и не запрашивает данные", async () => {
    render(<MemoryPage />);
    await screen.findByText("Записей пока нет");
    expect(screen.queryByRole("button", { name: "Мемотека" })).not.toBeInTheDocument();
    expect(api.getMemeLibrary).not.toHaveBeenCalled();
  });
  it("открывает отдельные карточки с источниками и закрывается при отключении режима", async () => {
    const view = render(<MemoryPage developerMode />);
    fireEvent.click(screen.getByRole("button", { name: "Мемотека" }));
    await screen.findByText(card.name);
    expect(screen.getByRole("link", { name: "Источник" })).toHaveAttribute("href", card.source);
    view.rerender(<MemoryPage developerMode={false} />);
    await waitFor(() => expect(screen.queryByText(card.name)).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Мемотека" })).not.toBeInTheDocument();
  });
  it("отключает подсказку через отдельный API", async () => {
    render(<MemoryPage developerMode />);
    fireEvent.click(screen.getByRole("button", { name: "Мемотека" }));
    await screen.findByText(card.name);
    fireEvent.click(screen.getByRole("button", { name: "Отключить" }));
    await waitFor(() => expect(api.saveMemeCard).toHaveBeenCalledWith("m1", { enabled: false }));
  });
  it("сохраняет исправленное значение и оставляет редактор открытым при ошибке", async () => {
    api.saveMemeCard.mockRejectedValue(new Error("Источник недоступен"));
    render(<MemoryPage developerMode />);
    fireEvent.click(screen.getByRole("button", { name: "Мемотека" }));
    await screen.findByText(card.name);
    fireEvent.click(screen.getByRole("button", { name: "Исправить" }));
    fireEvent.change(screen.getByLabelText("Значение и применение"), { target: { value: "Исправленное значение" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await screen.findByRole("alert");
    expect(screen.getByLabelText("Значение и применение")).toHaveValue("Исправленное значение");
    expect(api.saveMemeCard).toHaveBeenCalledWith("m1", expect.objectContaining({ summary: "Исправленное значение" }));
  });
});
