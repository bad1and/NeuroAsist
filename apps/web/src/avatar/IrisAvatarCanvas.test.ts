import { describe, expect, it } from "vitest";

import {
  criticallyDampedBlend,
  isSpeechGesture,
  motionTransitionDuration,
  parseAvatarPresence,
  speechPoseSmoothingBlend,
  speechPoseSmoothingSeconds,
  speechClipId,
  speechVisemeForTone,
} from "./IrisAvatarCanvas";
import { VRMHumanBoneName } from "@pixiv/three-vrm";

describe("speech animation routing", () => {
  it("keeps continuous speaking directives out of the one-shot gesture path", () => {
    for (const gesture of ["talk", "explanation", "question", "talkingquestion", "auto", "none"]) {
      expect(isSpeechGesture(gesture)).toBe(true);
    }
    expect(isSpeechGesture("greeting")).toBe(false);
  });

  it("selects the questioning loop only for question directives", () => {
    expect(speechClipId("question")).toBe("talkingquestion");
    expect(speechClipId("talkingquestion")).toBe("talkingquestion");
    expect(speechClipId("talk")).toBe("talk");
    expect(speechClipId("greeting")).toBe("talk");
  });
});

describe("avatar presence and interruptible blending", () => {
  it("accepts only the four renderer presence states", () => {
    expect(parseAvatarPresence("listening")).toBe("listening");
    expect(parseAvatarPresence("Thinking")).toBe("thinking");
    expect(parseAvatarPresence("speaking")).toBe("speaking");
    expect(parseAvatarPresence("legacy-state")).toBe("idle");
  });

  it("approaches a new pose smoothly without overshoot", () => {
    const early = criticallyDampedBlend(0.1, 0.4);
    const late = criticallyDampedBlend(0.4, 0.4);
    expect(early).toBeGreaterThan(0);
    expect(late).toBeGreaterThan(early);
    expect(late).toBeLessThanOrEqual(1);
  });

  it("gives materially different idle poses enough time to settle", () => {
    const subtleIdleChange = motionTransitionDuration({
      fromId: "idle-neutral",
      toId: "idle-soft-sway",
      requestedSeconds: 0.42,
      largestJointAngle: 0.08,
      hipsDistance: 0.002,
      interrupted: false,
      reducedMotion: false,
    });
    const largeInterruptedChange = motionTransitionDuration({
      fromId: "idle-soft-sway",
      toId: "talk",
      requestedSeconds: 0.42,
      largestJointAngle: 1.8,
      hipsDistance: 0.1,
      interrupted: true,
      reducedMotion: false,
    });

    expect(subtleIdleChange).toBeGreaterThanOrEqual(0.7);
    expect(largeInterruptedChange).toBeGreaterThan(subtleIdleChange);
    expect(largeInterruptedChange).toBeLessThanOrEqual(1.15);
  });

  it("keeps a calm but non-zero transition with reduced motion enabled", () => {
    expect(motionTransitionDuration({
      fromId: "talk",
      toId: "idle-neutral",
      requestedSeconds: 0.66,
      largestJointAngle: 2,
      hipsDistance: 0.2,
      interrupted: true,
      reducedMotion: true,
    })).toBe(0.5);
  });

  it("adapts speech filtering to animation velocity and bone role", () => {
    const slowTorso = speechPoseSmoothingSeconds(VRMHumanBoneName.Chest, 0.2);
    const fastTorso = speechPoseSmoothingSeconds(VRMHumanBoneName.Chest, 20);
    const fastArm = speechPoseSmoothingSeconds(VRMHumanBoneName.LeftUpperArm, 20);
    const fastHips = speechPoseSmoothingSeconds(VRMHumanBoneName.Hips, 20, 1);

    expect(slowTorso).toBeGreaterThanOrEqual(0.1);
    expect(fastTorso).toBeGreaterThan(slowTorso);
    expect(fastTorso).toBeLessThanOrEqual(0.24);
    expect(fastArm).toBe(0.26);
    expect(fastHips).toBe(0.28);
  });

  it("approaches a speech pose monotonically without overshoot", () => {
    const first = speechPoseSmoothingBlend(1 / 60, 0.24);
    const second = first + (1 - first) * speechPoseSmoothingBlend(1 / 60, 0.24);

    expect(first).toBeGreaterThan(0);
    expect(second).toBeGreaterThan(first);
    expect(second).toBeLessThan(1);
  });

  it("selects a stable coarse viseme from the audio tone instead of a timer", () => {
    expect(speechVisemeForTone(0)).toBe("aa");
    expect(speechVisemeForTone(0.35)).toBe("ih");
    expect(speechVisemeForTone(0.55)).toBe("ee");
    expect(speechVisemeForTone(0.75)).toBe("oh");
    expect(speechVisemeForTone(1)).toBe("ou");
  });
});
