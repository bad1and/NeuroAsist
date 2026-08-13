import { describe, expect, it } from "vitest";

import {
  EMOTION_PROFILES,
  EmotionBlendController,
  IdleMotionScheduler,
  parseEmotion,
  type IdleCandidate,
} from "./avatar-motion-state";

const candidates: IdleCandidate[] = [
  { id: "look", category: "micro", durationSeconds: 2, cooldownSeconds: 5 },
  { id: "stretch", category: "normal", durationSeconds: 3, cooldownSeconds: 5 },
  { id: "long", category: "long", durationSeconds: 8, cooldownSeconds: 10 },
];

describe("IdleMotionScheduler", () => {
  it("does not immediately repeat an idle and honors cooldown", () => {
    const scheduler = new IdleMotionScheduler(() => 0);
    scheduler.setProfile({ intervalMinSeconds: 1, intervalMaxSeconds: 1, alternativeProbability: 1 });
    scheduler.start(0);
    const shortCandidates = candidates.slice(0, 2);

    expect(scheduler.schedule(1, shortCandidates, { speaking: false, gesturePlaying: false })?.id).toBe("look");
    expect(scheduler.schedule(2, shortCandidates, { speaking: false, gesturePlaying: false })?.id).toBe("stretch");
    expect(scheduler.schedule(3, shortCandidates, { speaking: false, gesturePlaying: false })).toBeNull();
    expect(scheduler.schedule(7, shortCandidates, { speaking: false, gesturePlaying: false })?.id).toBe("look");
  });

  it("blocks long idles while speaking and all alternatives during a gesture", () => {
    const scheduler = new IdleMotionScheduler(() => 0);
    scheduler.setProfile({ intervalMinSeconds: 1, intervalMaxSeconds: 1, alternativeProbability: 1 });
    scheduler.start(0);

    expect(scheduler.schedule(1, [candidates[2]], { speaking: true, gesturePlaying: false })).toBeNull();
    expect(scheduler.schedule(2, candidates, { speaking: false, gesturePlaying: true })).toBeNull();
  });
});

describe("EmotionBlendController", () => {
  it("blends between emotions without dropping the previous weight", () => {
    const controller = new EmotionBlendController();
    controller.setTarget("angry", 1, 0);
    const entering = controller.update(0.05, 50);
    expect(entering.weights.get("angry")).toBeGreaterThan(0);
    expect(entering.weights.get("neutral")).toBeGreaterThan(0);

    for (let index = 0; index < 20; index += 1) controller.update(0.05, 100 + index * 50);
    const settled = controller.snapshot();
    expect(settled.currentEmotion).toBe("angry");
    expect(settled.weights.get("angry")).toBeCloseTo(EMOTION_PROFILES.angry.weight, 2);

    controller.setTarget("happy", 1, 1_200);
    const crossing = controller.update(0.05, 1_250);
    expect(crossing.weights.get("angry")).toBeGreaterThan(0);
    expect(crossing.weights.get("happy")).toBeGreaterThan(0);
  });

  it("keeps a transient emotion through its minimum hold before releasing", () => {
    const controller = new EmotionBlendController();
    controller.setTarget("surprised", 1, 0);
    expect(controller.releaseToNeutral(100).targetEmotion).toBe("surprised");
    expect(controller.update(0.01, EMOTION_PROFILES.surprised.minimumHoldMs + 1).targetEmotion).toBe("neutral");
  });

  it("falls back to neutral for unknown emotions", () => {
    expect(parseEmotion("not-a-real-emotion")).toBe("neutral");
  });
});
