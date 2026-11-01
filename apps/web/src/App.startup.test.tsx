// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReadinessResponse } from "./types";

const runtime = vi.hoisted(() => ({ readiness: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...await original<typeof import("./api")>(),
  isDesktopManaged: () => true,
  getReadiness: runtime.readiness,
  getStatus: vi.fn().mockResolvedValue({ backend: "ok", database: "ok" }),
  getSettings: vi.fn().mockResolvedValue({ api_key_configured: true, avatar_placement: "desktop_overlay" }),
  getEvents: vi.fn().mockResolvedValue({ events: [] }),
  getAvatarStatus: vi.fn().mockResolvedValue(null),
  getAvatarOverlay: vi.fn().mockResolvedValue(null),
}));
vi.mock("./desktop", async (original) => ({
  ...await original<typeof import("./desktop")>(),
  initialCoreStatus: () => "ready",
  getDesktopRuntime: vi.fn().mockResolvedValue({ coreStatus: "ready" }),
  getAvatarHostStatus: vi.fn().mockResolvedValue({ placement: "desktop_overlay", visible: false, phase: "disabled" }),
  listenForCoreStatus: async () => () => {},
  listenForAvatarStatus: async () => () => {},
}));
import App from "./App";
import { notificationStore, notify } from "./notifications";

afterEach(() => { cleanup(); notify.dismissAll(); vi.unstubAllGlobals(); });

describe("desktop startup integration", () => {
  it("keeps the loading screen until model and voice readiness, then reveals the mounted shell", async () => {
    vi.stubGlobal("WebSocket", class { close() {} });
    const readiness: ReadinessResponse = { phase: "starting", text_chat: "loading", stt: "loading",
      tts: "loading", vad: "ready", live_ready: false, errors: [] };
    runtime.readiness.mockResolvedValue(readiness);
    const { container } = render(<App />);
    await waitFor(() => expect(runtime.readiness).toHaveBeenCalled());
    expect(container.querySelector(".startup-screen")).toHaveAttribute("data-stage", "1");
    expect(container.querySelector(".app-shell")).toBeNull();

    runtime.readiness.mockResolvedValue({ ...readiness, phase: "text_ready", text_chat: "ready" });
    await waitFor(() => expect(container.querySelector(".startup-screen")).toHaveAttribute("data-stage", "2"), { timeout: 3000 });
    expect(container.querySelector(".app-shell")).toBeNull();
    expect(screen.getByText("Подготавливаю голосовые сервисы")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Подготовка Iris" })).toHaveAttribute("aria-valuenow", "3");

    runtime.readiness.mockResolvedValue({ ...readiness, phase: "text_ready", text_chat: "ready", stt: "ready" });
    await waitFor(() => expect(screen.getByText("Подготавливаю голос Iris")).toBeInTheDocument(), { timeout: 3000 });
    expect(container.querySelector(".startup-screen")).toHaveAttribute("data-stage", "2");
    expect(screen.getByRole("progressbar", { name: "Подготовка Iris" })).toHaveAttribute("aria-valuenow", "4");

    runtime.readiness.mockResolvedValue({ ...readiness, phase: "ready", text_chat: "ready", stt: "ready", tts: "ready", live_ready: true });
    await waitFor(() => expect(container.querySelector(".startup-screen")).toBeNull(), { timeout: 3000 });
    expect(container.querySelector(".app-shell")).toBeInTheDocument();
    expect(container.querySelector(".app-shell")).not.toHaveAttribute("inert");
    expect(container.querySelector(".app-shell")).not.toHaveAttribute("aria-hidden");
  });

  it("opens the app after an optional voice failure and retains one actionable warning", async () => {
    vi.stubGlobal("WebSocket", class { close() {} });
    runtime.readiness.mockResolvedValue({ phase: "degraded", text_chat: "ready", stt: "ready", tts: "failed",
      vad: "ready", live_ready: false, errors: ["voice failed"] });
    const { container, rerender } = render(<App />);
    await waitFor(() => expect(container.querySelector(".startup-screen")).toBeNull());
    await waitFor(() => expect(notificationStore.getSnapshot().filter(n => n.id === "startup.readiness")).toHaveLength(1));
    const notice = notificationStore.getSnapshot().find(n => n.id === "startup.readiness")!;
    expect(notice.details).toBe("Голос Iris");
    expect(notice.actions?.[0].label).toBe("Открыть диагностику");
    rerender(<App />);
    expect(notificationStore.getSnapshot().filter(n => n.id === "startup.readiness")).toHaveLength(1);
  });

  it("opens with unavailable readiness without claiming speech services were checked", async () => {
    vi.stubGlobal("WebSocket", class { close() {} });
    runtime.readiness.mockRejectedValue(new Error("readiness unavailable"));
    const { container } = render(<App />);
    await waitFor(() => expect(container.querySelector(".startup-screen")).toBeNull());
    expect(container.querySelector(".app-shell")).toBeInTheDocument();
    expect(notificationStore.getSnapshot().some(n => n.id === "startup.readiness")).toBe(false);
  });
});
