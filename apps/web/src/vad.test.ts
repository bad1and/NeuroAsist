import { describe, expect, it } from "vitest";
import { VoiceActivityGate } from "./vad";

describe("VoiceActivityGate", () => {
  it("debounces speech onset and end", () => {
    const gate = new VoiceActivityGate(.1, 100, 300);
    gate.start(0);
    expect(gate.feed(.2, 0)).toBeNull();
    expect(gate.feed(.2, 99)).toBeNull();
    expect(gate.feed(.2, 100)).toBe("speech_started");
    expect(gate.feed(0, 120)).toBeNull();
    expect(gate.feed(0, 419)).toBeNull();
    expect(gate.feed(0, 420)).toBe("speech_ended");
  });

  it("rejects a short noise candidate and resumes after a brief pause", () => {
    const gate = new VoiceActivityGate(.1, 100, 300);
    gate.start();
    gate.feed(.2, 0);
    expect(gate.feed(0, 10)).toBeNull();
    expect(gate.snapshot()).toBe("listening");
    gate.feed(.2, 20);
    expect(gate.feed(.2, 120)).toBe("speech_started");
    gate.feed(0, 150);
    gate.feed(.2, 200);
    expect(gate.snapshot()).toBe("speech");
  });
});
