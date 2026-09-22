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
import { IrisLoader } from "./components/IrisLoader";
import { WindowChrome } from "./components/WindowChrome";
import { shouldWaitForInAppAvatar, type AvatarHostStatus } from "./desktop";

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
