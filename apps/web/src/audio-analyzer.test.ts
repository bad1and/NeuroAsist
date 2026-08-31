import { describe, expect, it } from "vitest";
import { audioAnalyzer } from "./audio-analyzer";
import { getMoodVisuals, getStrengthLabel, MOOD_MAP } from "./mood-visuals";

describe("mood-visuals", () => {
  it("returns neutral visuals by default", () => {
    const visuals = getMoodVisuals();
    expect(visuals).toBeDefined();
    expect(visuals.colors).toHaveLength(3);
    expect(visuals.labelRu).toBe("Спокойное");
    expect(visuals.speed).toBeGreaterThan(0);
    expect(visuals.warp).toBeGreaterThan(0);
  });

  it("handles known emotions correctly", () => {
    const joy = getMoodVisuals("joy");
    expect(joy.labelRu).toBe("Радость");
    expect(joy.colors[0]).toBe("#fde047");

    const sadness = getMoodVisuals("sadness");
    expect(sadness.labelRu).toBe("Грусть");

    const anger = getMoodVisuals("angry");
    expect(anger.labelRu).toBe("Злость");

    const thinking = getMoodVisuals("thinking");
    expect(thinking.labelRu).toBe("Размышление");
  });

  it("handles russian emotion aliases", () => {
    expect(getMoodVisuals("радость").labelRu).toBe("Радость");
    expect(getMoodVisuals("грусть").labelRu).toBe("Грусть");
    expect(getMoodVisuals("злость").labelRu).toBe("Злость");
    expect(getMoodVisuals("страх").labelRu).toBe("Страх");
    expect(getMoodVisuals("удивление").labelRu).toBe("Удивление");
  });

  it("returns correct strength labels", () => {
    expect(getStrengthLabel("high")).toBe("Ярко выражено");
    expect(getStrengthLabel("low")).toBe("Слабо выражено");
    expect(getStrengthLabel("unknown")).toBe("Умеренно");
  });

  it("contains all expected protocol emotions in MOOD_MAP", () => {
    const keys = ["neutral", "happy", "sad", "angry", "annoyed", "smirk", "thinking", "surprised", "embarrassed", "concerned"];
    for (const key of keys) {
      expect(MOOD_MAP[key]).toBeDefined();
      expect(MOOD_MAP[key].colors).toHaveLength(3);
    }
  });
});

describe("audio-analyzer", () => {
  it("provides initial audio bands with 0 values", () => {
    audioAnalyzer.reset();
    const bands = audioAnalyzer.getAudioBands();
    expect(bands).toBeDefined();
    expect(bands.low).toBeGreaterThanOrEqual(0);
    expect(bands.mid).toBeGreaterThanOrEqual(0);
    expect(bands.high).toBeGreaterThanOrEqual(0);
    expect(bands.level).toBeGreaterThanOrEqual(0);
  });

  it("handles null audio elements gracefully without crashing", () => {
    expect(() => audioAnalyzer.attachAudioElement(null as unknown as HTMLAudioElement)).not.toThrow();
  });
});
