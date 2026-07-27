// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const windowApi = vi.hoisted(() => ({
  minimize: vi.fn().mockResolvedValue(undefined),
  toggleMaximize: vi.fn().mockResolvedValue(undefined),
  close: vi.fn().mockResolvedValue(undefined),
  isMaximized: vi.fn().mockResolvedValue(false),
  onResized: vi.fn().mockResolvedValue(() => undefined),
}));
const tauriInvoke = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));

vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => windowApi,
}));

import { StartupScreen } from "./components/StartupScreen";
import { WindowChrome } from "./components/WindowChrome";

beforeEach(() => {
  Object.defineProperty(window, "__TAURI_INTERNALS__", {
    configurable: true,
    value: { invoke: tauriInvoke },
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
});

describe("desktop chrome и запуск", () => {
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

  it("вызывает minimize, maximize/restore, двойной клик по header и завершение приложения", async () => {
    render(<WindowChrome title="Обзор" />);

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
