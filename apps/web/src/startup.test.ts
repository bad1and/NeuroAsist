import { describe, expect, it } from "vitest";
import { getStartupStage } from "./startup";
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
