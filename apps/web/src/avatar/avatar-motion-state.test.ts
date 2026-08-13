import { describe, expect, it } from "vitest";

import {
  EMOTION_PROFILES,
  BlinkScheduler,
  EmotionBlendController,
  IdleMotionScheduler,
  OrganicMotionDirector,
  SpeechAccentScheduler,
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

  it("treats the visible startup idle as already played", () => {
    const scheduler = new IdleMotionScheduler(() => 0);
    scheduler.setProfile({ intervalMinSeconds: 1, intervalMaxSeconds: 1, alternativeProbability: 1 });
    scheduler.start(0, "look");

    expect(scheduler.schedule(1, candidates.slice(0, 2), { speaking: false, gesturePlaying: false })?.id).toBe("stretch");
  });

  it("uses candidate weights without allowing an immediate repeat", () => {
    const scheduler = new IdleMotionScheduler(() => 0.95);
    scheduler.setProfile({ intervalMinSeconds: 1, intervalMaxSeconds: 1, alternativeProbability: 1 });
    scheduler.start(0);
    const weighted: IdleCandidate[] = [
      { id: "common", category: "micro", durationSeconds: 1, cooldownSeconds: 0, selectionWeight: 8 },
      { id: "rare", category: "normal", durationSeconds: 1, cooldownSeconds: 0, selectionWeight: 1 },
    ];

    expect(scheduler.schedule(1, weighted, { speaking: false, gesturePlaying: false })?.id).toBe("rare");
    expect(scheduler.schedule(2, weighted, { speaking: false, gesturePlaying: false })?.id).toBe("common");
  });

  it("blocks long idles while speaking and all alternatives during a gesture", () => {
    const scheduler = new IdleMotionScheduler(() => 0);
    scheduler.setProfile({ intervalMinSeconds: 1, intervalMaxSeconds: 1, alternativeProbability: 1 });
    scheduler.start(0);

    expect(scheduler.schedule(1, [candidates[2]], { speaking: true, gesturePlaying: false })).toBeNull();
    expect(scheduler.schedule(2, candidates, { speaking: false, gesturePlaying: true })).toBeNull();
  });

  it("does not schedule a wandering idle while Iris is listening or thinking", () => {
    const scheduler = new IdleMotionScheduler(() => 0);
    scheduler.setProfile({ intervalMinSeconds: 1, intervalMaxSeconds: 1, alternativeProbability: 1 });
    scheduler.start(0);
    expect(scheduler.schedule(1, candidates, { speaking: false, gesturePlaying: false, presence: "listening" })).toBeNull();
    expect(scheduler.schedule(2, candidates, { speaking: false, gesturePlaying: false, presence: "thinking" })).toBeNull();
  });

  it("plans each idle as a varied phrase instead of replaying a whole loop", () => {
    const scheduler = new IdleMotionScheduler(() => 0.5);
    const plan = scheduler.planPhrase(candidates[1]);

    expect(plan.durationSeconds).toBeGreaterThan(1.2);
    expect(plan.durationSeconds).toBeLessThan(candidates[1].durationSeconds);
    expect(plan.recoverySeconds).toBeGreaterThanOrEqual(0.8);
    expect(plan.recoverySeconds).toBeLessThanOrEqual(4);
    expect(plan.playbackRate).toBeGreaterThanOrEqual(0.9);
    expect(plan.playbackRate).toBeLessThanOrEqual(1.12);
  });

  it("can schedule the next idle immediately after the planned recovery", () => {
    const scheduler = new IdleMotionScheduler(() => 0);
    scheduler.setProfile({ intervalMinSeconds: 1, intervalMaxSeconds: 1, alternativeProbability: 1 });
    scheduler.start(0);
    const shortCandidates = candidates.slice(0, 2);

    expect(scheduler.schedule(1, shortCandidates, { speaking: false, gesturePlaying: false })?.id).toBe("look");
    scheduler.deferUntil(3);
    expect(scheduler.schedule(3, shortCandidates, { speaking: false, gesturePlaying: false })?.id).toBe("stretch");
  });

  it("reduces recently used families and does not alternate in a fixed category pattern", () => {
    const scheduler = new IdleMotionScheduler(() => 0.99);
    scheduler.setProfile({ intervalMinSeconds: 1, intervalMaxSeconds: 1, alternativeProbability: 1 });
    scheduler.start(0);
    const varied: IdleCandidate[] = [
      { id: "breath-a", family: "breath", category: "micro", durationSeconds: 1, cooldownSeconds: 0, selectionWeight: 8 },
      { id: "breath-b", family: "breath", category: "micro", durationSeconds: 1, cooldownSeconds: 0, selectionWeight: 8 },
      { id: "shift", family: "posture", category: "normal", durationSeconds: 1, cooldownSeconds: 0, selectionWeight: 1 },
    ];

    expect(scheduler.schedule(1, varied, { speaking: false, gesturePlaying: false })?.id).toBe("shift");
    expect(scheduler.schedule(2, varied, { speaking: false, gesturePlaying: false })?.family).toBe("breath");
    expect(scheduler.schedule(3, varied, { speaking: false, gesturePlaying: false })?.id).not.toBe("breath-b");
  });
});

describe("OrganicMotionDirector", () => {
  it("retargets smoothly and keeps listening more forward-facing than thinking", () => {
    const listening = new OrganicMotionDirector(() => 1);
    const thinking = new OrganicMotionDirector(() => 1);
    listening.reset(0, "listening");
    thinking.reset(0, "thinking");

    const attentive = listening.update(10, 10, "listening");
    const thoughtful = thinking.update(10, 10, "thinking");
    expect(Math.abs(attentive.headYaw)).toBeLessThanOrEqual(0.007);
    expect(Math.abs(thoughtful.headYaw)).toBeGreaterThan(Math.abs(attentive.headYaw));
    expect(thoughtful.headPitch).toBeGreaterThan(attentive.headPitch);
  });
});

describe("SpeechAccentScheduler", () => {
  it("spaces accents, prevents immediate repeats, and yields to an explicit gesture", () => {
    const scheduler = new SpeechAccentScheduler(() => 0);
    const accents = [
      { id: "affirm", cooldownSeconds: 30 },
      { id: "explain", cooldownSeconds: 30 },
    ];
    scheduler.start(0);
    expect(scheduler.schedule(6.9, accents, { speaking: true, explicitGesturePlaying: false })).toBeNull();
    expect(scheduler.schedule(7, accents, { speaking: true, explicitGesturePlaying: true })).toBeNull();
    expect(scheduler.schedule(15, accents, { speaking: true, explicitGesturePlaying: false })?.id).toBe("affirm");
    expect(scheduler.schedule(22, accents, { speaking: true, explicitGesturePlaying: false })?.id).toBe("explain");
  });
});

describe("BlinkScheduler", () => {
  it("creates a short, non-periodic eyelid pulse", () => {
    const scheduler = new BlinkScheduler(() => 0);
    scheduler.start(0);

    expect(scheduler.update(2_799)).toBe(0);
    expect(scheduler.update(2_800)).toBe(0);
    expect(scheduler.update(2_850)).toBeGreaterThan(0);
    expect(scheduler.update(3_000)).toBe(0);
    expect(scheduler.update(3_114)).toBe(0);
    expect(scheduler.update(3_115)).toBe(0);
    expect(scheduler.update(3_165)).toBeGreaterThan(0);
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
