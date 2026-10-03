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

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

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

    runtime.readiness.mockResolvedValue({ ...readiness, phase: "ready", text_chat: "ready", stt: "ready", tts: "ready", live_ready: true });
    await waitFor(() => expect(container.querySelector(".startup-screen")).toBeNull(), { timeout: 3000 });
    expect(container.querySelector(".app-shell")).toBeInTheDocument();
    expect(container.querySelector(".app-shell")).not.toHaveAttribute("inert");
    expect(container.querySelector(".app-shell")).not.toHaveAttribute("aria-hidden");
  });
});
