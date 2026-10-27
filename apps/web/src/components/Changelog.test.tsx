// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChangelogDialog, ChangelogSettingsCard } from "./Changelog";
import { NotificationHost } from "./NotificationHost";
import { notify } from "../notifications";
import type { ReleaseNote } from "../changelog/types";

const releases: ReleaseNote[] = [
  { version: "2.0.0", status: "released", date: "2026-10-26", title: "Стало проще", summary: "Новое в Iris", intro: "Текущая запись", sections: [{ kind: "new", title: "Появилось новое", items: [{ title: "Изображение", description: "Пояснение", image: { src: "/changelog/2.0.0/search.webp", alt: "Окно поиска", width: 1280, height: 800, caption: "Поиск в Iris" } }] }] },
  { version: "1.9.0", status: "released", date: "2026-10-20", title: "Прежнее обновление", summary: "Ранее", intro: "Прошлая запись", sections: [] },
];

afterEach(() => { cleanup(); notify.dismissAll(); vi.useRealTimers(); });

describe("окно истории обновлений", () => {
  it("выбирает установленную версию, переключает историю, показывает изображение и возвращается к текущей при открытии", () => {
    const props = { onClose: vi.fn(), releases, installedVersion: "2.0.0" };
    const { rerender } = render(<ChangelogDialog {...props} open />);
    expect(screen.getByRole("dialog", { name: "Что нового" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Стало проще" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Окно поиска" })).toHaveAttribute("width", "1280");
    const versions = screen.getByRole("navigation", { name: "Версии Iris" });
    fireEvent.click(within(versions).getByRole("button", { name: /1.9.0/ }));
    expect(screen.getByRole("heading", { name: "Прежнее обновление" })).toBeInTheDocument();
    expect(within(versions).getByRole("button", { name: /1.9.0/ })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByText("Установлена")).not.toBeInTheDocument();
    rerender(<ChangelogDialog {...props} open={false} />);
    rerender(<ChangelogDialog {...props} open />);
    expect(screen.getByRole("heading", { name: "Стало проще" })).toBeInTheDocument();
  });

  it("закрывается Escape, удерживает фокус и возвращает его к вызвавшей кнопке", async () => {
    vi.useFakeTimers();
    const onClose = vi.fn();
    const opener = document.createElement("button"); opener.textContent = "Открыть историю"; document.body.append(opener); opener.focus();
    const { rerender } = render(<ChangelogDialog open onClose={onClose} releases={releases} installedVersion="2.0.0" />);
    const dialog = screen.getByRole("dialog");
    const buttons = within(dialog).getAllByRole("button");
    buttons[buttons.length - 1].focus();
    fireEvent.keyDown(window, { key: "Tab" });
    // The scrollable article is also a keyboard stop.
    const article = within(dialog).getByRole("article"); article.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(buttons[0]).toHaveFocus();
    fireEvent.keyDown(window, { key: "Escape" });
    await act(async () => { vi.advanceTimersByTime(200); });
    expect(onClose).toHaveBeenCalledOnce();
    rerender(<ChangelogDialog open={false} onClose={onClose} releases={releases} installedVersion="2.0.0" />);
    expect(opener).toHaveFocus(); opener.remove();
  });

  it("даёт доступ к истории из настроек", () => {
    const open = vi.fn(); window.addEventListener("iris-open-changelog", open);
    render(<ChangelogSettingsCard />);
    fireEvent.click(screen.getByRole("button", { name: "История обновлений" }));
    expect(open).toHaveBeenCalledOnce();
    window.removeEventListener("iris-open-changelog", open);
  });

  it("Escape сначала закрывает список версий и оставляет окно открытым", async () => {
    vi.useFakeTimers();
    const onClose = vi.fn();
    render(<ChangelogDialog open onClose={onClose} releases={releases} installedVersion="2.0.0" />);
    const select = screen.getByRole("button", { name: "2.0.0 · Установлена" });
    fireEvent.click(select);
    expect(select).toHaveAttribute("aria-expanded", "true");
    fireEvent.keyDown(select, { key: "Escape" });
    await act(async () => { vi.advanceTimersByTime(250); });
    expect(select).toHaveAttribute("aria-expanded", "false");
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("открывает подробности уведомления с клавиатурной кнопки и сохраняет постоянное сообщение", async () => {
    vi.useFakeTimers();
    const onNavigate = vi.fn();
    render(<NotificationHost onNavigate={onNavigate} />);
    act(() => { notify.info("Обновление Iris", "Новые заметки", { duration: "persistent", navigateView: "changelog", navigateLabel: "Что нового" }); });
    await act(async () => { vi.advanceTimersByTime(60000); });
    expect(screen.getByText("Обновление Iris")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Что нового" }));
    expect(onNavigate).toHaveBeenCalledWith("changelog");
  });
});
