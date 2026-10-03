// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const windowApi = vi.hoisted(() => ({
  label: "main",
  minimize: vi.fn().mockResolvedValue(undefined),
  toggleMaximize: vi.fn().mockResolvedValue(undefined),
  close: vi.fn().mockResolvedValue(undefined),
  isMaximized: vi.fn().mockResolvedValue(false),
  onResized: vi.fn().mockResolvedValue(() => undefined),
}));
const tauriInvoke = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
const windowEvents = vi.hoisted(() => new Set<(event: { payload: unknown }) => void>());

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async (name: string, listener: (event: { payload: unknown }) => void) => {
    if (name === "desktop-window-preferences") windowEvents.add(listener);
    return () => windowEvents.delete(listener);
  }),
}));

vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => windowApi,
}));

import { StartupScreen } from "./components/StartupScreen";
import { IrisLoader } from "./components/IrisLoader";
import { WindowChrome } from "./components/WindowChrome";
import { WindowSettings } from "./components/WindowSettings";
import { shouldWaitForInAppAvatar, type AvatarHostStatus } from "./desktop";

beforeEach(() => {
  windowApi.label = "main";
  tauriInvoke.mockImplementation(async (command: string, args?: { locked?: boolean }) => {
    if (command === "get_window_preferences" || command === "set_reference_window_locked" || command === "reset_reference_window") {
      const payload = {
        locked: args?.locked ?? false,
        reference: { width: 1135, height: 760 },
        minimum: { width: 900, height: 620 },
        effectiveReference: { width: 1135, height: 760 },
      };
      if (command === "set_reference_window_locked") windowEvents.forEach((listener) => listener({ payload }));
      return payload;
    }
    return undefined;
  });
  Object.defineProperty(window, "__TAURI_INTERNALS__", {
    configurable: true,
    value: { invoke: tauriInvoke },
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  windowEvents.clear();
  Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
});

describe("desktop chrome и запуск", () => {
  it("оставляет брендовый loader переиспользуемым и доступным", () => {
    render(<IrisLoader size="compact" label="Загрузка данных" />);
    expect(screen.getByRole("status", { name: "Загрузка данных" })).toHaveClass("iris-loader-compact");
  });

  it("показывает реальный переход starting → ready", () => {
    const { rerender } = render(<StartupScreen status="starting" retrying={false} onRetry={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Запускаю Iris" })).toBeInTheDocument();

    rerender(<StartupScreen status="ready" retrying={false} onRetry={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Рада тебя видеть" })).toBeInTheDocument();
  });

  it("оставляет ошибку на экране и запускает retry", () => {
    const retry = vi.fn();
    render(<StartupScreen status="failed" retrying={false} onRetry={retry} />);
    expect(screen.getByRole("heading", { name: "Не удалось запустить ядро" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Попробовать снова/ }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("раскрывает лепестки по готовности и завершает только после третьего", async () => {
    const complete = vi.fn();
    const { container, rerender } = render(<StartupScreen status="starting" stage={1} onComplete={complete} />);
    expect(container.querySelector(".startup-screen")).toHaveAttribute("data-revealed", "1");
    rerender(<StartupScreen status="ready" stage={2} onComplete={complete} />);
    expect(container.querySelector(".startup-screen")).toHaveAttribute("data-revealed", "2");
    expect(complete).not.toHaveBeenCalled();
    rerender(<StartupScreen status="ready" stage={3} onComplete={complete} />);
    expect(container.querySelector(".startup-screen")).toHaveAttribute("data-revealed", "3");
    await waitFor(() => expect(complete).toHaveBeenCalledOnce());
  });

  it("отменяет финал при сбое и размонтировании", async () => {
    const complete = vi.fn();
    const { rerender, unmount } = render(<StartupScreen status="ready" onComplete={complete} />);
    rerender(<StartupScreen status="crashed" onComplete={complete} />);
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(complete).not.toHaveBeenCalled();
    rerender(<StartupScreen status="ready" onComplete={complete} />);
    unmount();
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(complete).not.toHaveBeenCalled();
  });

  it("вызывает minimize, maximize/restore, двойной клик по header и завершение приложения", async () => {
    render(<WindowChrome title="Обзор" />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Развернуть окно" })).toBeEnabled());

    fireEvent.click(screen.getByRole("button", { name: "Свернуть окно" }));
    fireEvent.click(screen.getByRole("button", { name: "Развернуть окно" }));
    fireEvent.doubleClick(screen.getByRole("banner"));
    fireEvent.click(screen.getByRole("button", { name: "Закрыть Iris" }));

    await waitFor(() => {
      expect(windowApi.minimize).toHaveBeenCalledOnce();
      expect(windowApi.toggleMaximize).toHaveBeenCalledTimes(2);
      expect(tauriInvoke).toHaveBeenCalledWith("quit_app", {}, undefined);
    });
  });
});

describe("эталонное окно", () => {
  it("применяет фиксацию сразу и защищает обе команды разворачивания", async () => {
    render(<><WindowChrome title="" /><WindowSettings /></>);
    const toggle = screen.getByRole("switch");
    await waitFor(() => expect(toggle).toBeEnabled());
    expect(screen.getAllByText("1135 × 760").length).toBeGreaterThan(0);
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).toBeChecked());
    const maximize = screen.getByRole("button", { name: "Развернуть окно" });
    expect(maximize).toBeDisabled();
    fireEvent.click(maximize);
    fireEvent.doubleClick(screen.getByRole("banner"));
    expect(windowApi.toggleMaximize).not.toHaveBeenCalled();
    expect(tauriInvoke).toHaveBeenCalledWith("set_reference_window_locked", { locked: true }, undefined);
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).not.toBeChecked());
    expect(maximize).toBeEnabled();
  });

  it("сбрасывает размер отдельной командой и не снимает фиксацию", async () => {
    render(<WindowSettings />);
    const reset = screen.getByRole("button", { name: "Вернуть эталонный размер" });
    await waitFor(() => expect(reset).toBeEnabled());
    fireEvent.click(reset);
    expect(await screen.findByRole("status")).toHaveTextContent("Окно возвращено к эталонному размеру.");
    expect(tauriInvoke).toHaveBeenCalledWith("reset_reference_window", {}, undefined);
    expect(tauriInvoke).not.toHaveBeenCalledWith("set_reference_window_locked", expect.anything(), undefined);
  });

  it("оставляет прежний переключатель при ошибке сохранения и позволяет повторить", async () => {
    render(<WindowSettings />);
    const toggle = screen.getByRole("switch");
    await waitFor(() => expect(toggle).toBeEnabled());
    tauriInvoke.mockRejectedValueOnce(new Error("disk full"));
    const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
    fireEvent.click(toggle);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось применить настройку окна.");
    expect(toggle).not.toBeChecked();
    expect(toggle).toBeEnabled();
    log.mockRestore();
  });

  it("не изменяет браузер и отдельное окно QA Studio", () => {
    Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
    const browser = render(<WindowSettings />);
    expect(screen.getByRole("switch")).toBeDisabled();
    expect(screen.getByText("Управление размером окна доступно в настольном приложении Iris.")).toBeVisible();
    browser.unmount();
    Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: { invoke: tauriInvoke } });
    windowApi.label = "qa_studio";
    render(<WindowChrome title="QA Studio" />);
    expect(screen.getByRole("button", { name: "Развернуть окно" })).toBeEnabled();
    expect(tauriInvoke).not.toHaveBeenCalledWith("get_window_preferences", {}, undefined);
  });

  it("не перезаписывает событие фиксации запоздавшим ответом первоначального чтения", async () => {
    let completeRead: (value: unknown) => void = () => undefined;
    tauriInvoke.mockImplementationOnce(() => new Promise((resolve) => { completeRead = resolve; }));
    render(<WindowSettings />);
    await waitFor(() => expect(tauriInvoke).toHaveBeenCalledWith("get_window_preferences", {}, undefined));
    const payload = {
      locked: true,
      reference: { width: 1135, height: 760 }, minimum: { width: 900, height: 620 },
      effectiveReference: { width: 1135, height: 760 },
    };
    await act(async () => { windowEvents.forEach((listener) => listener({ payload })); });
    expect(screen.getByRole("switch")).toBeChecked();
    await act(async () => completeRead({ ...payload, locked: false }));
    expect(screen.getByRole("switch")).toBeChecked();
  });
});

describe("avatar startup gate", () => {
  const status = (
    phase: AvatarHostStatus["phase"],
    placement: AvatarHostStatus["placement"] = "in_app",
  ): AvatarHostStatus => ({
    placement,
    running: phase !== "failed",
    embedded: phase === "warming" || phase === "ready",
    visible: true,
    ready: phase === "ready",
    phase,
    error: phase === "failed" ? "timeout" : null,
  });

  it("ждёт только видимый in-app renderer в состоянии прогрева", () => {
    expect(shouldWaitForInAppAvatar(true, null)).toBe(true);
    expect(shouldWaitForInAppAvatar(true, status("starting"))).toBe(true);
    expect(shouldWaitForInAppAvatar(true, status("warming"))).toBe(true);
    expect(shouldWaitForInAppAvatar(true, status("ready"))).toBe(false);
    expect(shouldWaitForInAppAvatar(true, status("failed"))).toBe(false);
    expect(shouldWaitForInAppAvatar(true, status("starting", "desktop_overlay"))).toBe(false);
    expect(shouldWaitForInAppAvatar(false, null)).toBe(false);
  });
});
