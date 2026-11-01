import { describe, expect, it } from "vitest";
import { getStartupProgress, getStartupStage } from "./startup";
import type { AvatarHostStatus } from "./desktop";
import type { ReadinessResponse } from "./types";

const ready: ReadinessResponse = {
  phase: "ready", text_chat: "ready", stt: "ready", tts: "ready", vad: "ready", live_ready: true, errors: [],
};

describe("real startup stages", () => {
  it("holds the core petal until the model is ready", () => {
    expect(getStartupStage("starting", ready, false)).toBe(1);
    expect(getStartupStage("ready", null, false)).toBe(1);
    expect(getStartupStage("ready", { ...ready, text_chat: "loading" }, false)).toBe(1);
  });
  it("waits for both voice preparation and the first avatar frame", () => {
    expect(getStartupStage("ready", { ...ready, tts: "loading" }, false)).toBe(2);
    expect(getStartupStage("ready", ready, true)).toBe(2);
    expect(getStartupStage("ready", ready, false)).toBe(3);
  });
  it("allows diagnostics when optional services fail or are disabled", () => {
    expect(getStartupStage("ready", { ...ready, phase: "degraded", tts: "failed", stt: "disabled", vad: "fallback" }, false)).toBe(3);
    expect(getStartupStage("ready", { ...ready, phase: "degraded", tts: "failed", stt: "loading" }, false)).toBe(2);
    expect(getStartupStage("failed", ready, false)).toBe(1);
  });
  it("supports older cores without readiness while retaining the avatar gate", () => {
    expect(getStartupStage("ready", null, false, true)).toBe(3);
    expect(getStartupStage("ready", null, true, true)).toBe(2);
  });
});

describe("startup component progress", () => {
  it("does not invent progress before readiness or reuse a previous core's snapshot", () => {
    expect(getStartupProgress("starting", ready, false).value).toBeNull();
    expect(getStartupProgress("starting", ready, false).components.find(row => row.id === "tts")?.state).toBe("unknown");
    expect(getStartupProgress("ready", null, false).value).toBeNull();
  });
  it("reports parallel voice preparation and advances only for settled checks", () => {
    const loading = { ...ready, stt: "loading" as const, tts: "loading" as const, live_ready: false };
    const progress = getStartupProgress("ready", loading, false);
    expect(progress.value).toBe(3 / 5);
    expect(progress.complete).toBe(false);
    expect(progress.detail).toBe("Подготавливаю голосовые сервисы");
    const next = getStartupProgress("ready", { ...loading, stt: "ready" }, false);
    expect(next.value).toBe(4 / 5);
    expect(next.detail).toBe("Подготавливаю голос Iris");
  });
  it("waits for the first avatar frame even when voice services are ready", () => {
    const avatar: AvatarHostStatus = { placement: "in_app", running: true, embedded: false, visible: true,
      ready: false, phase: "warming", error: null };
    const progress = getStartupProgress("ready", ready, true, avatar);
    expect(progress.value).toBe(5 / 6);
    expect(progress.complete).toBe(false);
    expect(progress.detail).toBe("Подготавливаю первый кадр аватара");
    expect(getStartupProgress("ready", ready, false, { ...avatar, phase: "ready", ready: true }).value).toBe(1);
    expect(getStartupProgress("ready", ready, false, { ...avatar, phase: "failed" }).detail).toContain("часть функций недоступна");
  });
  it("settles optional failures and deferred loading without calling them ready", () => {
    const progress = getStartupProgress("ready", { ...ready, tts: "failed", stt: "disabled", vad: "fallback" }, false);
    expect(progress.complete).toBe(true);
    expect(progress.value).toBe(1);
    expect(progress.components.map(row => row.state)).toEqual(["ready", "ready", "deferred", "failed", "fallback"]);
    expect(progress.detail).toContain("часть функций недоступна");
  });
  it("preserves the legacy fallback without claiming unknown services are ready", () => {
    const progress = getStartupProgress("ready", null, false, null, true);
    expect(progress.complete).toBe(true);
    expect(progress.value).toBeNull();
    expect(progress.components.find(row => row.id === "stt")?.state).toBe("unknown");
    expect(progress.detail).toContain("сведения о сервисах недоступны");
  });
  it.each(["failed", "crashed"] as const)("never completes a %s core", status => {
    const progress = getStartupProgress(status, ready, false);
    expect(progress.failed).toBe(true);
    expect(progress.complete).toBe(false);
    expect(progress.value).toBeNull();
  });
});
