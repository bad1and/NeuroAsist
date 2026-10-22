// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const desktop = vi.hoisted(() => ({ enabled: false, invoke: vi.fn() }));
vi.mock("../desktop", () => ({ isDesktopApp: () => desktop.enabled }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: desktop.invoke }));
import { defaultBindings, saveBindings, useShortcutCommands, shortcutsAreRecording } from "../shortcuts";
import { ShortcutSettings } from "./ShortcutSettings";

beforeEach(async () => {
  desktop.enabled = false; desktop.invoke.mockReset(); localStorage.clear(); await saveBindings(defaultBindings());
});
afterEach(() => { cleanup(); desktop.enabled = false; });
const edit = async (title = "Найти в Iris") => {
  fireEvent.click(screen.getByRole("button", { name: `Изменить: ${title}` }));
  await screen.findByLabelText(`Новое сочетание: ${title}`);
};
describe("shortcut settings", () => {
  it("records Russian physical keys, saves, unbinds and resets from the keyboard", async () => {
    render(<ShortcutSettings />);
    await edit();
    fireEvent.keyDown(window, { key: "й", code: "KeyQ", ctrlKey: true, shiftKey: true });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(screen.queryByLabelText("Новое сочетание: Найти в Iris")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Изменить: Найти в Iris" })).toHaveTextContent("Q");
    await edit();
    fireEvent.click(screen.getByRole("button", { name: "Отключить сочетание" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Изменить: Найти в Iris" })).toHaveTextContent("Не назначено"));
    await edit();
    fireEvent.click(screen.getByRole("button", { name: "По умолчанию" }));
    expect(screen.getByRole("button", { name: "Изменить: Найти в Iris" })).toHaveTextContent("Не назначено");
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Изменить: Найти в Iris" })).toHaveTextContent("K"));
  });
  it("requires explicit transfer on a conflict and suppresses live commands while recording", async () => {
    const search = vi.fn();
    function Probe() { useShortcutCommands({ search }); return <ShortcutSettings />; }
    render(<Probe />); await edit("Открыть настройки");
    fireEvent.keyDown(window, { key: "л", code: "KeyK", ctrlKey: true });
    expect(search).not.toHaveBeenCalled(); expect(screen.getByText("Уже назначено:", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Изменить: Найти в Iris" })).toHaveTextContent("K");
    fireEvent.click(screen.getByRole("button", { name: "Перенести сюда" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Изменить: Найти в Iris" })).toHaveTextContent("Не назначено"));
    expect(screen.getByRole("button", { name: "Изменить: Открыть настройки" })).toHaveTextContent("K");
  });
  it("previews a conflicting default and lets the user cancel before transferring", async () => {
    await saveBindings({ ...defaultBindings(), search: null, settings: "Ctrl+KeyK" });
    render(<ShortcutSettings />);
    expect(screen.queryByRole("button", { name: "Отключить сочетание" })).not.toBeInTheDocument();
    await edit();
    expect(screen.queryByRole("button", { name: "Отключить сочетание" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "По умолчанию" }));
    expect(screen.getByRole("button", { name: "Перенести сюда" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(screen.getByRole("button", { name: "Изменить: Найти в Iris" })).toHaveTextContent("Не назначено");
    expect(screen.getByRole("button", { name: "Изменить: Найти в Iris" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "Изменить: Открыть настройки" })).toHaveTextContent("K");
    await edit();
    fireEvent.click(screen.getByRole("button", { name: "По умолчанию" }));
    fireEvent.click(screen.getByRole("button", { name: "Перенести сюда" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Изменить: Найти в Iris" })).toHaveTextContent("K"));
    expect(screen.getByRole("button", { name: "Изменить: Открыть настройки" })).toHaveTextContent("Не назначено");
  });
  it("cancels on Escape or focus loss without changing the binding and validates reserved keys", async () => {
    render(<ShortcutSettings />); await edit();
    fireEvent.keyDown(window, { key: "с", code: "KeyC", ctrlKey: true });
    expect(screen.getByRole("status")).toHaveTextContent("стандартное сочетание");
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
    fireEvent.keyDown(window, { key: "Escape", code: "Escape" });
    expect(shortcutsAreRecording()).toBe(false);
    expect(screen.getByRole("button", { name: "Изменить: Найти в Iris" })).toHaveFocus();
    await edit(); fireEvent.blur(window);
    expect(shortcutsAreRecording()).toBe(false);
  });
  it("filters commands and confirms reset of all preferences", async () => {
    await saveBindings({ ...defaultBindings(), search: null });
    render(<ShortcutSettings />);
    fireEvent.click(screen.getByRole("checkbox", { name: /Изменённые/ }));
    expect(screen.getByRole("button", { name: "Изменить: Найти в Iris" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Изменить: Открыть настройки" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Сбросить всё" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Сбросить сочетания?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сбросить" }));
    await waitFor(() => expect(screen.getByText(/Ничего не найдено/)).toBeInTheDocument());
  });
  it("shows Windows registration failures without applying the candidate", async () => {
    desktop.enabled = true;
    const status = { bindings: { showWindow: null, toggleAvatar: null }, errors: {} };
    desktop.invoke.mockImplementation((name: string) => name === "set_shortcut_preferences" ? Promise.reject("Сочетание занято в Windows") : Promise.resolve(status));
    render(<ShortcutSettings />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Изменить: Показать окно Iris" })).toBeEnabled());
    await edit("Показать окно Iris");
    fireEvent.keyDown(window, { key: "F9", code: "F9", ctrlKey: true, shiftKey: true });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("занято в Windows"));
    expect(screen.getByRole("button", { name: "Изменить: Показать окно Iris" })).toHaveTextContent("Не назначено");
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    await waitFor(() => expect(desktop.invoke).toHaveBeenCalledWith("set_shortcut_recording", { recording: false }));
  });
  it("keeps local changes usable when an existing system shortcut is unavailable", async () => {
    desktop.enabled = true;
    const status = { bindings: { showWindow: "Ctrl+Shift+F9", toggleAvatar: null }, errors: { showWindow: "Сочетание занято в Windows" } };
    desktop.invoke.mockResolvedValue(status);
    render(<ShortcutSettings />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Изменить: Найти в Iris" })).toBeEnabled());
    await edit();
    fireEvent.keyDown(window, { key: "й", code: "KeyQ", ctrlKey: true, shiftKey: true });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Изменить: Найти в Iris" })).toHaveTextContent("Q"));
    expect(desktop.invoke.mock.calls.some(([name]) => name === "set_shortcut_preferences")).toBe(false);
    expect(screen.getByRole("alert")).toHaveTextContent("занято в Windows");
  });
  it("releases the recorder on unmount and allows Tab to reach Save", async () => {
    const view = render(<ShortcutSettings />); await edit();
    fireEvent.keyDown(window, { key: "q", code: "KeyQ", ctrlKey: true, shiftKey: true });
    expect(fireEvent.keyDown(window, { key: "Tab", code: "Tab" })).toBe(true);
    const save = screen.getByRole("button", { name: "Сохранить" }); save.focus();
    expect(fireEvent.keyDown(save, { key: "Enter", code: "Enter" })).toBe(true);
    view.unmount(); expect(shortcutsAreRecording()).toBe(false);
  });
});
