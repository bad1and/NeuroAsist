// @vitest-environment jsdom
import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
vi.mock("./desktop", () => ({ isDesktopApp: () => false }));
import { SHORTCUT_STORAGE_KEY, bindingError, bindingFromEvent, defaultBindings, readBindings, saveBindings, setShortcutRecording, useShortcutCommands } from "./shortcuts";

beforeEach(async () => { localStorage.clear(); await saveBindings(defaultBindings()); });
afterEach(() => { cleanup(); setShortcutRecording(false); vi.restoreAllMocks(); });
describe("keyboard command routing", () => {
  it("uses the same physical key for English and Russian, including text inputs", () => {
    const search = vi.fn();
    function Probe() { useShortcutCommands({ search }); return <textarea aria-label="message" />; }
    const view = render(<Probe />);
    const input = view.getByRole("textbox");
    fireEvent.keyDown(input, { key: "k", code: "KeyK", ctrlKey: true });
    fireEvent.keyDown(input, { key: "л", code: "KeyK", ctrlKey: true });
    expect(search).toHaveBeenCalledTimes(2);
  });
  it("ignores extra modifiers, held keys, composition, AltGr and prevented events", () => {
    const search = vi.fn();
    function Probe() { useShortcutCommands({ search }); return null; }
    render(<Probe />);
    for (const extra of [{ shiftKey: true }, { altKey: true }, { metaKey: true }, { repeat: true }, { isComposing: true }]) {
      fireEvent.keyDown(window, { key: "л", code: "KeyK", ctrlKey: true, ...extra });
    }
    const event = new KeyboardEvent("keydown", { key: "л", code: "KeyK", ctrlKey: true, cancelable: true });
    event.preventDefault(); window.dispatchEvent(event);
    const altgr = new KeyboardEvent("keydown", { code: "KeyK", ctrlKey: true });
    vi.spyOn(altgr, "getModifierState").mockReturnValue(true);
    expect(bindingFromEvent(altgr)).toBeNull();
    expect(search).not.toHaveBeenCalled();
  });
  it("suspends commands in the recorder, modal and startup screen", () => {
    const search = vi.fn();
    function Probe() { useShortcutCommands({ search }); return null; }
    render(<Probe />);
    const press = () => fireEvent.keyDown(window, { code: "KeyK", ctrlKey: true });
    setShortcutRecording(true); press(); setShortcutRecording(false);
    const modal = document.createElement("div"); modal.setAttribute("role", "dialog"); modal.setAttribute("aria-modal", "true"); document.body.append(modal); press(); modal.remove();
    const shell = document.createElement("div"); shell.className = "app-shell"; shell.setAttribute("inert", ""); document.body.append(shell); press(); shell.remove();
    expect(search).not.toHaveBeenCalled(); press(); expect(search).toHaveBeenCalledOnce();
  });
  it("updates live after a rebind and unbind and leaves unavailable commands unconsumed", async () => {
    const search = vi.fn();
    function Probe() { useShortcutCommands({ search, composer: () => false }); return null; }
    render(<Probe />);
    await act(() => saveBindings({ ...defaultBindings(), search: "Ctrl+Shift+KeyQ" }));
    fireEvent.keyDown(window, { code: "KeyK", ctrlKey: true });
    fireEvent.keyDown(window, { code: "KeyQ", key: "й", ctrlKey: true, shiftKey: true });
    expect(search).toHaveBeenCalledOnce();
    expect(fireEvent.keyDown(window, { code: "KeyL", ctrlKey: true, shiftKey: true })).toBe(true);
    await act(() => saveBindings({ ...defaultBindings(), search: null }));
    fireEvent.keyDown(window, { code: "KeyK", ctrlKey: true });
    expect(search).toHaveBeenCalledOnce();
  });
});
describe("shortcut preferences", () => {
  it("protects standard editing, system shortcuts, AltGr and bare keys", () => {
    for (const value of ["KeyM", "Shift+KeyM", "Ctrl+KeyC", "Ctrl+Shift+KeyZ", "Ctrl+Alt+KeyQ", "Alt+F4", "Meta+KeyK", "Ctrl+Ctrl+KeyK"]) expect(bindingError(value)).toBeTruthy();
    for (const item of Object.values(defaultBindings())) if (item) expect(bindingError(item)).toBeNull();
  });
  it("persists null unbinds and recovers corrupt preferences without duplicate actions", () => {
    localStorage.setItem(SHORTCUT_STORAGE_KEY, JSON.stringify({ search: null, settings: "Ctrl+Shift+KeyM", microphone: "Ctrl+Shift+KeyM", composer: "Ctrl+KeyC" }));
    const restored = readBindings();
    expect(restored.search).toBeNull(); expect(restored.settings).toBe("Ctrl+Shift+KeyM"); expect(restored.microphone).toBeNull(); expect(restored.composer).toBe(defaultBindings().composer);
    localStorage.setItem(SHORTCUT_STORAGE_KEY, "{broken"); expect(readBindings()).toEqual(defaultBindings());
  });
  it("rejects collisions and storage failures without changing active bindings", async () => {
    await expect(saveBindings({ ...defaultBindings(), search: defaultBindings().microphone })).rejects.toThrow("уже назначено");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("disk full"); });
    await expect(saveBindings({ ...defaultBindings(), search: null })).rejects.toThrow("disk full");
    expect(readBindings().search).toBe(defaultBindings().search);
  });
});
