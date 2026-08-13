import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { FBXLoader } from "three/examples/jsm/loaders/FBXLoader.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import {
  VRM,
  VRMExpressionPresetName,
  VRMHumanBoneName,
  VRMLoaderPlugin,
  VRMUtils,
} from "@pixiv/three-vrm";

import { avatarWebSocketUrl, resolveApiUrl } from "../api";
import type { Emotion } from "../generated/character-protocol";
import { AvatarAudioQueue } from "./AvatarAudioQueue";
import { AvatarProtocolClient, type AvatarEnvelope } from "./AvatarProtocolClient";
import {
  EMOTION_PROFILES,
  BlinkScheduler,
  EmotionBlendController,
  IdleMotionScheduler,
  OrganicMotionDirector,
  SpeechAccentScheduler,
  parseEmotion,
  type AvatarPresence,
  type IdleCandidate,
} from "./avatar-motion-state";
import {
  createIrisTargetBindRotations,
  createProceduralIdlePose,
  retargetMixamoPose,
  type ProceduralIdleKind,
  type RetargetedPose,
  type SourceBoneReference,
} from "./avatar-retarget";

const IDLE_DEFINITIONS: readonly IdleCandidate[] = [
  // Breathing remains the base, but posture and attention changes get enough
  // turns that idle reads as present rather than paused.
  { id: "idle-neutral", category: "micro", durationSeconds: 18, cooldownSeconds: 12, selectionWeight: 1.2, family: "breath" },
  { id: "idle-refocus", category: "micro", durationSeconds: 6.5, cooldownSeconds: 27, selectionWeight: 0.95, family: "attention" },
  { id: "idle-weight-shift", category: "normal", durationSeconds: 9, cooldownSeconds: 36, selectionWeight: 0.72, family: "posture" },
  { id: "idle-look-around", category: "normal", durationSeconds: 7, cooldownSeconds: 54, selectionWeight: 0.42, family: "attention" },
  { id: "idle-soft-sway", category: "micro", durationSeconds: 14, cooldownSeconds: 30, selectionWeight: 0.9, family: "posture" },
  { id: "idle-shoulder-release", category: "normal", durationSeconds: 8, cooldownSeconds: 48, selectionWeight: 0.48, family: "release" },
];

const SPEECH_ACCENT_DEFINITIONS = [
  { id: "speech-accent-affirm", cooldownSeconds: 22, selectionWeight: 0.7 },
  { id: "speech-accent-explain", cooldownSeconds: 28, selectionWeight: 0.45 },
] as const;

const EMOTION_EXPRESSION_KEYS = [
  VRMExpressionPresetName.Neutral,
  VRMExpressionPresetName.Happy,
  VRMExpressionPresetName.Sad,
  VRMExpressionPresetName.Angry,
  VRMExpressionPresetName.Relaxed,
  "Surprised",
];

/** Pick a coarse viseme from the current spectral centroid. This remains an
 * amplitude/spectrum fallback, not phoneme recognition, but follows the audio
 * being played instead of cycling vowels on a wall-clock timer. */
export function speechVisemeForTone(tone: number): VRMExpressionPresetName {
  const normalized = THREE.MathUtils.clamp(tone, 0, 1);
  if (normalized < 0.2) return VRMExpressionPresetName.Aa;
  if (normalized < 0.4) return VRMExpressionPresetName.Ih;
  if (normalized < 0.6) return VRMExpressionPresetName.Ee;
  if (normalized < 0.8) return VRMExpressionPresetName.Oh;
  return VRMExpressionPresetName.Ou;
}

const MOTION_PROFILES: Record<string, { intervalMinSeconds: number; intervalMaxSeconds: number; probability: number }> = {
  idle: { intervalMinSeconds: 5.5, intervalMaxSeconds: 11, probability: 0.94 },
  energetic: { intervalMinSeconds: 11, intervalMaxSeconds: 23, probability: 0.84 },
  calm: { intervalMinSeconds: 18, intervalMaxSeconds: 34, probability: 0.64 },
  tense: { intervalMinSeconds: 12, intervalMaxSeconds: 25, probability: 0.74 },
  playful: { intervalMinSeconds: 12, intervalMaxSeconds: 24, probability: 0.8 },
  thoughtful: { intervalMinSeconds: 16, intervalMaxSeconds: 31, probability: 0.66 },
  alert: { intervalMinSeconds: 10, intervalMaxSeconds: 20, probability: 0.8 },
  shy: { intervalMinSeconds: 16, intervalMaxSeconds: 31, probability: 0.62 },
  attentive: { intervalMinSeconds: 14, intervalMaxSeconds: 27, probability: 0.72 },
};

type ExpressionName = string;

type MotionClip = {
  id: string;
  root: THREE.Group | null;
  mixer: THREE.AnimationMixer | null;
  action: THREE.AnimationAction | null;
  duration: number;
  loop: boolean;
  time: number;
  bones: Map<string, THREE.Object3D>;
  reference: Map<string, SourceBoneReference>;
  sample: (time: number) => NormalizedPose;
};

type NormalizedPose = RetargetedPose;

type ClipSource = {
  file: string;
  fallbackFile?: string;
  loop: boolean;
  aliasOf?: string;
  /** Keep downloaded reference material, but use Iris's authored safe pose. */
  preferProcedural?: boolean;
};

const CLIP_SOURCES: Record<string, ClipSource> = {
  // Optional role-based exports. When a named, verified Mixamo file is added
  // it replaces the procedural role below; absent files retain that safe
  // fallback and never block avatar startup.
  "idle-soft-sway": { file: "iris-idle-calm-a.fbx", loop: true },
  "idle-shoulder-release": { file: "iris-idle-calm-b.fbx", loop: true },
  "presence-listening": { file: "iris-listening.fbx", loop: true },
  // This Mixamo thought is kept as an embedded reference asset, but its deep
  // source bend does not fit Iris's portrait rig. The procedural version has
  // the same semantic state and a calibrated, forward-safe entry pose.
  "presence-thinking": { file: "iris-thinking.fbx", loop: true, preferProcedural: true },
  thinking: { file: "X Bot@Thinking.fbx", loop: false },
  angry: { file: "X Bot@Angry.fbx", loop: false },
  frustration: { file: "X Bot@Angry.fbx", loop: false, aliasOf: "angry" },
  surprise: { file: "X Bot@Surprised.fbx", loop: false },
  greeting: { file: "X Bot@Waving.fbx", loop: false },
  farewell: { file: "X Bot@WavingGoodbye.fbx", loop: false },
  shrug: { file: "X Bot@Shrugging.fbx", loop: false },
  agreement: { file: "X Bot@Agreeing.fbx", loop: false },
  disagreement: { file: "X Bot@Shaking Head No.fbx", loop: false },
  talk: { file: "iris-talk-calm.fbx", fallbackFile: "X Bot@Talking.fbx", loop: true },
  talkingquestion: { file: "iris-talk-question.fbx", fallbackFile: "X Bot@TalkingQuestion.fbx", loop: true },
  question: { file: "X Bot@TalkingQuestion.fbx", loop: true, aliasOf: "talkingquestion" },
  explanation: { file: "X Bot@Talking.fbx", loop: true, aliasOf: "talk" },
  "speech-accent-affirm": { file: "iris-accent-affirm.fbx", fallbackFile: "X Bot@Agreeing.fbx", loop: false },
  "speech-accent-explain": { file: "iris-accent-explain.fbx", fallbackFile: "X Bot@Shrugging.fbx", loop: false },
};

const PROCEDURAL_IDLE_CLIPS: Record<string, { kind: ProceduralIdleKind; duration: number }> = {
  "idle-neutral": { kind: "neutral", duration: 18 },
  "idle-refocus": { kind: "refocus", duration: 6.5 },
  "idle-weight-shift": { kind: "weight-shift", duration: 9 },
  "idle-look-around": { kind: "look-around", duration: 7 },
  "idle-soft-sway": { kind: "soft-sway", duration: 14 },
  "idle-shoulder-release": { kind: "shoulder-release", duration: 8 },
  "presence-listening": { kind: "listening", duration: 12 },
  "presence-thinking": { kind: "thinking", duration: 10 },
};

// Keep the common conversational path fast. One-shot gestures remain lazy so
// opening the dialog does not download every FBX in the gesture library.
const INITIAL_CLIP_IDS = [
  "idle-soft-sway",
  "idle-shoulder-release",
  "presence-listening",
  "talk",
  "talkingquestion",
  "speech-accent-affirm",
  "speech-accent-explain",
] as const;

const UPPER_BODY_BONES = new Set<VRMHumanBoneName>([
  VRMHumanBoneName.Spine, VRMHumanBoneName.Chest, VRMHumanBoneName.UpperChest,
  VRMHumanBoneName.Neck, VRMHumanBoneName.Head,
  VRMHumanBoneName.LeftShoulder, VRMHumanBoneName.LeftUpperArm,
  VRMHumanBoneName.LeftLowerArm, VRMHumanBoneName.LeftHand,
  VRMHumanBoneName.RightShoulder, VRMHumanBoneName.RightUpperArm,
  VRMHumanBoneName.RightLowerArm, VRMHumanBoneName.RightHand,
]);

function payloadString(payload: Record<string, unknown>, key: string, fallback = ""): string {
  return typeof payload[key] === "string" ? payload[key] : fallback;
}

function payloadNumber(payload: Record<string, unknown>, key: string, fallback = 1): number {
  return typeof payload[key] === "number" ? payload[key] : fallback;
}

function payloadBoolean(payload: Record<string, unknown>, key: string, fallback = false): boolean {
  return typeof payload[key] === "boolean" ? payload[key] : fallback;
}

/**
 * A critically damped response reaches the current target without overshoot
 * and can be retargeted every frame. That is what makes interrupted gestures
 * look continuous instead of like two cross-fades glued together.
 */
export function criticallyDampedBlend(elapsedSeconds: number, durationSeconds: number): number {
  if (durationSeconds <= 0) return 1;
  const x = Math.max(0, elapsedSeconds) / durationSeconds * 4.5;
  return THREE.MathUtils.clamp(1 - (1 + x) * Math.exp(-x), 0, 1);
}

export type MotionTransitionContext = {
  fromId: string | null;
  toId: string;
  requestedSeconds: number;
  largestJointAngle: number;
  hipsDistance: number;
  interrupted: boolean;
  reducedMotion: boolean;
};

/**
 * Select a transition time from the semantic change as well as the actual
 * pose distance.  A fixed fade made a small breath wait unnecessarily while a
 * large idle-to-speech change still looked like it snapped into place.
 */
export function motionTransitionDuration({
  fromId,
  toId,
  requestedSeconds,
  largestJointAngle,
  hipsDistance,
  interrupted,
  reducedMotion,
}: MotionTransitionContext): number {
  const isIdle = (id: string | null) => id?.startsWith("idle-") ?? false;
  const isSpeech = (id: string | null) => id === "talk" || id === "talkingquestion";
  const isPresence = (id: string | null) => id?.startsWith("presence-") ?? false;
  const fromIdle = isIdle(fromId);
  const toIdle = isIdle(toId);

  let semanticMinimum = 0.42;
  if (fromIdle && toIdle) semanticMinimum = 0.7;
  else if ((fromIdle && isSpeech(toId)) || (isSpeech(fromId) && toIdle)) semanticMinimum = 0.66;
  else if (isPresence(fromId) || isPresence(toId)) semanticMinimum = 0.58;
  else if (isSpeech(fromId) || isSpeech(toId)) semanticMinimum = 0.6;

  // Retargeting a fade before it has settled needs a little more time.  It
  // keeps repeated stream/state commands from producing a sharp reversal.
  const interruptionPadding = interrupted ? 0.12 : 0;
  const poseMinimum = Math.max(
    Math.max(0, largestJointAngle) * 0.36,
    Math.max(0, hipsDistance) * 4.2,
  );
  const duration = Math.max(Math.max(0.05, requestedSeconds), semanticMinimum, poseMinimum) + interruptionPadding;
  return THREE.MathUtils.clamp(duration, reducedMotion ? 0.22 : 0.32, reducedMotion ? 0.5 : 1.15);
}

export type SpeechSmoothingBoneGroup = "hips" | "arms" | "torso" | "head" | "other";

export function speechSmoothingBoneGroup(human: VRMHumanBoneName): SpeechSmoothingBoneGroup {
  if (human === VRMHumanBoneName.Hips) return "hips";
  switch (human) {
    case VRMHumanBoneName.LeftShoulder: case VRMHumanBoneName.LeftUpperArm:
    case VRMHumanBoneName.LeftLowerArm: case VRMHumanBoneName.LeftHand:
    case VRMHumanBoneName.RightShoulder: case VRMHumanBoneName.RightUpperArm:
    case VRMHumanBoneName.RightLowerArm: case VRMHumanBoneName.RightHand:
      return "arms";
    case VRMHumanBoneName.Spine: case VRMHumanBoneName.Chest:
    case VRMHumanBoneName.UpperChest: case VRMHumanBoneName.Neck:
      return "torso";
    default:
      break;
  }
  if (human === VRMHumanBoneName.Head) return "head";
  return "other";
}

/**
 * Convert the observed per-frame pose velocity into a bounded time constant.
 * Calm talk frames stay responsive; discontinuities in exported clips receive
 * extra filtering before they can read as a shoulder or torso snap.
 */
export function speechPoseSmoothingSeconds(
  human: VRMHumanBoneName,
  angularSpeedRadiansPerSecond: number,
  hipsSpeedUnitsPerSecond = 0,
): number {
  const group = speechSmoothingBoneGroup(human);
  const [minimum, maximum, speedAtMaximum] = group === "hips"
    ? [0.14, 0.28, 4.2]
    : group === "arms"
      ? [0.13, 0.26, 7.2]
      : group === "torso"
        ? [0.1, 0.24, 6.4]
        : group === "head"
          ? [0.1, 0.22, 6]
          : [0.1, 0.2, 6];
  // Position changes matter only for the hips. The multiplier puts a visible
  // root translation on a comparable scale to a torso rotation.
  const speed = Math.max(0, angularSpeedRadiansPerSecond, hipsSpeedUnitsPerSecond * 9);
  const normalized = THREE.MathUtils.clamp((speed - 0.35) / Math.max(0.001, speedAtMaximum - 0.35), 0, 1);
  return THREE.MathUtils.lerp(minimum, maximum, normalized * normalized);
}

/** Exponential response is interruption-safe and never overshoots a pose. */
export function speechPoseSmoothingBlend(deltaSeconds: number, smoothingSeconds: number): number {
  if (smoothingSeconds <= 0) return 1;
  // Three time constants settle to roughly 95% of the new pose.
  return THREE.MathUtils.clamp(1 - Math.exp(-Math.max(0, deltaSeconds) / (smoothingSeconds / 3)), 0, 1);
}

function emotionPreset(emotion: string): ExpressionName {
  switch (emotion.toLowerCase()) {
    case "happy": case "smirk": return VRMExpressionPresetName.Happy;
    case "sad": return VRMExpressionPresetName.Sad;
    case "angry": case "annoyed": return VRMExpressionPresetName.Angry;
    // This VRM is v0.0 and exports Surprised as a custom expression rather
    // than the VRM 1.0 `surprised` preset.
    case "surprised": return "Surprised";
    case "thinking": return VRMExpressionPresetName.Relaxed;
    case "embarrassed": case "concerned": return VRMExpressionPresetName.Sad;
    case "relaxed": return VRMExpressionPresetName.Relaxed;
    default: return VRMExpressionPresetName.Neutral;
  }
}

/**
 * `talk` is the continuous locomotion state for an utterance, not a one-shot
 * gesture. Treating it as both caused the animation to restart from frame zero
 * shortly after playback began, which was most visible in the shoulders.
 */
export function speechClipId(gesture: string): "talk" | "talkingquestion" {
  const normalized = gesture.toLowerCase();
  return normalized === "question" || normalized === "talkingquestion"
    ? "talkingquestion"
    : "talk";
}

export function isSpeechGesture(gesture: string): boolean {
  return ["", "none", "auto", "talk", "explanation", "question", "talkingquestion"].includes(gesture.toLowerCase());
}

export function parseAvatarPresence(value: string | undefined): AvatarPresence {
  switch ((value ?? "idle").trim().toLowerCase()) {
    case "listening": return "listening";
    case "thinking": return "thinking";
    case "speaking": return "speaking";
    default: return "idle";
  }
}

class AvatarMotionPlayer {
  private readonly idleScheduler = new IdleMotionScheduler();
  private readonly organicMotion = new OrganicMotionDirector();
  private readonly speechAccentScheduler = new SpeechAccentScheduler();
  private readonly clips = new Map<string, MotionClip>();
  private readonly clipLoads = new Map<string, Promise<MotionClip | null>>();
  private readonly normalizedByHuman = new Map<VRMHumanBoneName, THREE.Object3D>();
  private readonly normalizedRestPositions = new Map<VRMHumanBoneName, THREE.Vector3>();
  private readonly targetBindRotations = createIrisTargetBindRotations();
  private readonly transitionFrom = new Map<VRMHumanBoneName, { position: THREE.Vector3; quaternion: THREE.Quaternion }>();
  private readonly idleVariations = new Map<string, number>();
  private clipsReady: Promise<void> | null = null;
  private motionProfile = "idle";
  private elapsedSeconds = 0;
  private gazeTime = 0;
  private presence: AvatarPresence = "idle";
  private speakingClipId: "talk" | "talkingquestion" = "talk";
  private gestureGeneration = 0;
  private currentIdleId = "idle-neutral";
  private currentIdleTime = 0;
  private idlePhraseEndsAt = 0;
  private idlePhraseAmplitude = 1;
  private idlePhrasePlaybackRate = 1;
  private activeClip: MotionClip | null = null;
  private overlay: {
    clip: MotionClip;
    id: string;
    startedAt: number;
    endsAt: number;
    intensity: number;
    explicit: boolean;
  } | null = null;
  private readonly overlayTransitionFrom = new Map<VRMHumanBoneName, THREE.Quaternion>();
  private readonly overlayDeltas = new Map<VRMHumanBoneName, THREE.Quaternion>();
  private readonly speechFilteredRotations = new Map<VRMHumanBoneName, THREE.Quaternion>();
  private readonly speechRawRotations = new Map<VRMHumanBoneName, THREE.Quaternion>();
  private speechFilteredHipsPosition: THREE.Vector3 | null = null;
  private speechRawHipsPosition: THREE.Vector3 | null = null;
  private overlayTransitionElapsed = 1;
  private overlayTransitionDuration = 0.28;
  private overlayReleasing = false;
  private transitionElapsed = 1;
  private transitionDuration = 0.4;
  private reducedMotion = false;
  private disposed = false;

  constructor(private readonly vrm: VRM) {
    if (!vrm.humanoid) return;
    // The normalized VRM rig is the contract between a generic humanoid
    // animation and this model. Writing raw Iris bones directly was the cause
    // of the old head-only/T-pose behaviour.
    vrm.humanoid.autoUpdateHumanBones = true;
    vrm.humanoid.resetNormalizedPose();
    for (const humanBoneName of Object.values(VRMHumanBoneName) as VRMHumanBoneName[]) {
      const node = vrm.humanoid.getNormalizedBoneNode(humanBoneName);
      if (node) {
        this.normalizedByHuman.set(humanBoneName, node);
        this.normalizedRestPositions.set(humanBoneName, node.position.clone());
      }
    }
    this.createProceduralIdleClips();
  }

  async startIdle(): Promise<void> {
    if (this.disposed || !this.vrm.humanoid) return;
    await this.ensureClipsLoaded();
    if (this.disposed) return;
    // The neutral profile must be active before the first idle schedule. It
    // used to be selected only after an emotion release, leaving startup with
    // the scheduler's much slower legacy interval.
    this.setMotionProfile("idle");
    this.currentIdleId = "idle-neutral";
    this.idleScheduler.start(this.elapsedSeconds, this.currentIdleId);
    this.organicMotion.reset(this.elapsedSeconds, this.presence);
    this.seedIdleVariation("idle-neutral");
    if (this.presence === "speaking") this.switchTo(this.speakingClipId, 0.56);
    else if (this.presence === "listening") this.switchTo(this.clips.has("presence-listening") ? "presence-listening" : "idle-neutral", 0.42, 0, true);
    else if (this.presence === "thinking") this.switchTo(this.clips.has("presence-thinking") ? "presence-thinking" : "idle-refocus", 0.48, 0, true);
    else this.switchTo(this.currentIdleId, 0.45);
  }

  setSpeaking(value: boolean, preferredClipId?: "talk" | "talkingquestion"): void {
    const nextSpeechClipId = preferredClipId ?? this.speakingClipId;
    if (value) this.speakingClipId = nextSpeechClipId;
    this.setPresence(value ? "speaking" : "idle");
  }

  setSpeechClip(preferredClipId: "talk" | "talkingquestion"): void {
    this.speakingClipId = preferredClipId;
    if (this.presence === "speaking") this.switchTo(preferredClipId, 0.48);
  }

  setPresence(nextPresence: AvatarPresence): void {
    if (this.disposed) return;
    const previous = this.presence;
    if (nextPresence === previous) return;
    this.presence = nextPresence;
    this.idlePhraseEndsAt = 0;
    if (nextPresence === "speaking") {
      // Start from the displayed idle pose, not the first talk frame. This
      // makes the new per-frame filter part of the existing state transition
      // instead of creating a second jump on the first audible word.
      this.primeSpeechPoseFilter();
      this.speechAccentScheduler.start(this.elapsedSeconds);
      // Start a reply from the neutral first frame. Phase matching made the
      // avatar enter mid-gesture, which was visible as a sharply crumpled
      // torso during the first word of an answer.
      this.switchTo(this.speakingClipId, 0.56);
      return;
    }
    if (previous === "speaking") {
      this.speechAccentScheduler.stop();
      this.resetSpeechPoseFilter();
    }
    if (nextPresence === "listening") {
      this.switchTo(this.clips.has("presence-listening") ? "presence-listening" : "idle-neutral", 0.42, 0, true);
      return;
    }
    if (nextPresence === "thinking") {
      this.switchTo(this.clips.has("presence-thinking") ? "presence-thinking" : "idle-refocus", 0.48, 0, true);
      return;
    }
    this.returnToCurrentIdle(0.42);
  }

  setMotionProfile(profileName: string): void {
    this.motionProfile = profileName in MOTION_PROFILES ? profileName : "idle";
    const profile = MOTION_PROFILES[this.motionProfile];
    this.idleScheduler.setProfile({
      intervalMinSeconds: profile.intervalMinSeconds,
      intervalMaxSeconds: profile.intervalMaxSeconds,
      alternativeProbability: profile.probability,
    });
  }

  setReducedMotion(value: boolean): void {
    this.reducedMotion = value;
  }

  async trigger(gesture: string, intensity: number): Promise<{ durationMs: number; generation: number }> {
    const generation = ++this.gestureGeneration;
    if (this.disposed) return { durationMs: 0, generation };
    const normalized = gesture.toLowerCase();
    const clipId = CLIP_SOURCES[normalized] ? normalized : "talk";
    await this.ensureClipLoaded(clipId);
    // A gesture may have been superseded while its FBX files were loading.
    // Never let that stale async continuation overwrite the newer pose.
    if (this.disposed || generation !== this.gestureGeneration) return { durationMs: 0, generation };
    const clip = this.clips.get(clipId);
    if (!clip) return { durationMs: 0, generation };
    this.startOverlay(clipId, clip, intensity, true);
    const durationMs = Math.round(clip.duration * 1_000);
    return { durationMs, generation };
  }

  isGestureGenerationCurrent(generation: number): boolean {
    return !this.disposed && generation === this.gestureGeneration;
  }

  stop(): void {
    this.gestureGeneration += 1;
    this.beginOverlayRelease();
    this.setPresence("idle");
  }

  update(delta: number): void {
    const safeDelta = Math.max(0, delta);
    this.elapsedSeconds += safeDelta;

    if (this.activeClip) {
      const duration = Math.max(0.001, this.activeClip.duration);
      const playbackRate = this.presence === "idle" && this.activeClip.id === this.currentIdleId
        ? this.idlePhrasePlaybackRate
        : 1;
      this.activeClip.time = this.activeClip.loop
        ? (this.activeClip.time + safeDelta * playbackRate) % duration
        : Math.min(duration, this.activeClip.time + safeDelta * playbackRate);
      this.transitionElapsed += safeDelta;
      this.applySample(this.activeClip.sample(this.activeClip.time), this.idlePhraseAmplitude);
      if (this.presence === "idle" && this.activeClip.id === this.currentIdleId) {
        this.currentIdleTime = this.activeClip.time;
      }
    }

    this.applyOverlay(safeDelta);
    this.applySpeechPoseFilter(safeDelta);
    const hasExplicitOverlay = this.overlay?.explicit ?? false;
    if (this.presence === "speaking" && !this.overlay) {
      const accent = this.speechAccentScheduler.schedule(this.elapsedSeconds, SPEECH_ACCENT_DEFINITIONS, {
        speaking: true,
        explicitGesturePlaying: hasExplicitOverlay,
      });
      const clip = accent && this.clips.get(accent.id);
      if (accent && clip) this.startOverlay(accent.id, clip, 0.42, false);
    }

    if (this.presence === "idle" && !this.overlay && this.idlePhraseEndsAt > 0 && this.elapsedSeconds >= this.idlePhraseEndsAt) {
      this.idlePhraseEndsAt = 0;
      this.idlePhraseAmplitude = 1;
      this.idlePhrasePlaybackRate = 1;
      this.currentIdleId = "idle-neutral";
      this.seedIdleVariation(this.currentIdleId);
      this.returnToCurrentIdle(0.52);
    }

    if (this.presence === "idle" && !this.overlay && this.idlePhraseEndsAt === 0) {
      const candidate = this.idleScheduler.schedule(this.elapsedSeconds, IDLE_DEFINITIONS, {
        speaking: false,
        gesturePlaying: false,
        presence: this.presence,
      });
      if (candidate) {
        const phrase = this.idleScheduler.planPhrase(candidate);
        this.currentIdleId = candidate.id;
        this.currentIdleTime = 0;
        this.idlePhraseEndsAt = this.elapsedSeconds + phrase.durationSeconds;
        this.idlePhraseAmplitude = phrase.amplitude;
        this.idlePhrasePlaybackRate = phrase.playbackRate;
        this.seedIdleVariation(candidate.id, phrase.variation);
        // Idle clips may enter from their closest compatible phase. This
        // avoids treating a cross-fade as a bandage for a pose mismatch.
        this.switchTo(candidate.id, 0.58, 0, true);
        this.idleScheduler.deferUntil(this.idlePhraseEndsAt + phrase.recoverySeconds);
      }
    }
  }

  // Gaze is applied to the same normalized rig after the clip has been
  // sampled, then VRM copies it to Iris's authored raw bones in vrm.update().
  applyPreVrmPose(delta: number): void {
    const safeDelta = Math.max(0, delta);
    this.gazeTime += safeDelta;
    const head = this.normalizedByHuman.get(VRMHumanBoneName.Head);
    if (!head) return;
    const intensity = this.overlay?.explicit ? 0.35 : (this.reducedMotion ? 0.3 : 1);
    const drift = this.organicMotion.update(this.elapsedSeconds, safeDelta, this.presence, Boolean(this.overlay?.explicit));
    const hips = this.normalizedByHuman.get(VRMHumanBoneName.Hips);
    const chest = this.normalizedByHuman.get(VRMHumanBoneName.Chest);
    if (hips) hips.position.x += drift.hipsX * intensity;
    if (chest) chest.rotateX(drift.chestPitch * intensity);
    if (chest) chest.rotateY(drift.chestYaw * intensity);
    head.rotateX(drift.headPitch * intensity);
    head.rotateY(drift.headYaw * intensity);
    head.rotateZ(drift.headRoll * intensity);
  }

  private ensureClipsLoaded(): Promise<void> {
    this.clipsReady ??= Promise.all(INITIAL_CLIP_IDS.map((id) => this.ensureClipLoaded(id))).then(() => undefined);
    return this.clipsReady;
  }

  private ensureClipLoaded(id: string): Promise<void> {
    const source = CLIP_SOURCES[id];
    if (!source) return Promise.resolve();
    const canonicalId = source.aliasOf ?? id;
    const canonicalSource = CLIP_SOURCES[canonicalId] ?? source;
    const existing = this.clips.get(canonicalId);
    if (canonicalSource.preferProcedural || existing?.root) {
      if (source.aliasOf && existing) this.clips.set(id, existing);
      return Promise.resolve();
    }
    const inFlight = this.clipLoads.get(canonicalId);
    if (inFlight) return inFlight.then(() => undefined);

    const load = this.loadClip(canonicalId, canonicalSource);
    const completion = load.then((clip) => {
      if (clip) {
        this.clips.set(canonicalId, clip);
        if (source.aliasOf) this.clips.set(id, clip);
      }
    }).finally(() => {
      this.clipLoads.delete(canonicalId);
    });
    this.clipLoads.set(canonicalId, load);
    return completion;
  }

  private async loadClip(id: string, source: ClipSource): Promise<MotionClip | null> {
    try {
      const loader = new FBXLoader();
      let root: THREE.Group;
      try {
        root = await loader.loadAsync(`/avatar/animations/${source.file}`);
      } catch (primaryError) {
        if (!source.fallbackFile) throw primaryError;
        root = await loader.loadAsync(`/avatar/animations/${source.fallbackFile}`);
      }
      if (!root.animations[0]) return null;
      const bones = new Map<string, THREE.Object3D>();
      const reference = new Map<string, { position: THREE.Vector3; quaternion: THREE.Quaternion }>();
      root.traverse((node) => {
        if (node.type !== "Bone") return;
        bones.set(node.name, node);
      });
      const mixer = new THREE.AnimationMixer(root);
      const action = mixer.clipAction(root.animations[0]);
      action.setLoop(source.loop ? THREE.LoopRepeat : THREE.LoopOnce, source.loop ? Infinity : 1);
      action.clampWhenFinished = !source.loop;
      action.play();
      // Mixamo's bind pose is not the entry pose of the exported clip. The
      // first animated frame is the only safe reference for a seamless entry
      // into the model's authored neutral pose.
      mixer.setTime(0);
      root.updateMatrixWorld(true);
      for (const [name, node] of bones) {
        reference.set(name, {
          position: node.position.clone(),
          quaternion: node.quaternion.clone(),
        });
      }
      return {
        id,
        root,
        mixer,
        action,
        duration: root.animations[0].duration,
        loop: source.loop,
        time: 0,
        bones,
        reference,
        sample: (time) => {
          mixer.setTime(time);
          root.updateMatrixWorld(true);
          return retargetMixamoPose(bones, reference, this.targetBindRotations, this.normalizedRestPositions);
        },
      } satisfies MotionClip;
    } catch {
      return null;
    }
  }

  private switchTo(id: string, duration: number, initialTime = 0, matchLoopPhase = false): void {
    const next = this.clips.get(id);
    if (!next) return;
    const startTime = matchLoopPhase
      ? this.findClosestLoopEntryTime(next)
      : Math.max(0, initialTime) % Math.max(0.001, next.duration);
    if (this.activeClip === next && Math.abs(startTime - next.time) < 0.01) return;
    const previousId = this.activeClip?.id ?? null;
    const interrupted = this.transitionElapsed < this.transitionDuration;
    this.transitionFrom.clear();
    for (const [human, node] of this.normalizedByHuman) {
      this.transitionFrom.set(human, {
        position: node.position.clone(),
        quaternion: node.quaternion.clone(),
      });
    }
    // `sample` for imported FBX clips reads the bones that its mixer writes.
    // Set the entry time before sampling: evaluating its former frame here was
    // the source of a one-frame jump at every clip switch.
    next.action?.reset().play();
    const entryPose = next.sample(startTime);
    let largestJointChange = 0;
    for (const [human, node] of this.normalizedByHuman) {
      const target = entryPose.rotations.get(human);
        if (target) largestJointChange = Math.max(largestJointChange, node.quaternion.angleTo(target));
    }
    const hips = this.normalizedByHuman.get(VRMHumanBoneName.Hips);
    const hipsDistance = hips ? hips.position.distanceTo(entryPose.hipsPosition) : 0;
    next.time = startTime;
    this.activeClip = next;
    this.transitionElapsed = 0;
    this.transitionDuration = motionTransitionDuration({
      fromId: previousId,
      toId: next.id,
      requestedSeconds: duration,
      largestJointAngle: largestJointChange,
      hipsDistance,
      interrupted,
      reducedMotion: this.reducedMotion,
    });
  }

  private findClosestLoopEntryTime(next: MotionClip): number {
    if (!next.loop || next.duration <= 0) return 0;
    const sampleCount = 36;
    let bestTime = 0;
    let bestScore = Number.POSITIVE_INFINITY;
    for (let index = 0; index < sampleCount; index += 1) {
      const time = next.duration * index / sampleCount;
      const pose = next.sample(time);
      let score = 0;
      for (const [human, node] of this.normalizedByHuman) {
        const target = pose.rotations.get(human);
        if (!target) continue;
        const multiplier = human === VRMHumanBoneName.Hips || human === VRMHumanBoneName.Spine || human === VRMHumanBoneName.Chest ? 1.35 : 1;
        score += node.quaternion.angleTo(target) ** 2 * multiplier;
      }
      const hips = this.normalizedByHuman.get(VRMHumanBoneName.Hips);
      if (hips) score += hips.position.distanceToSquared(pose.hipsPosition) * 18;
      if (score < bestScore) {
        bestScore = score;
        bestTime = time;
      }
    }
    return bestTime;
  }

  private captureCurrentIdle(): void {
    if (this.activeClip && this.activeClip.id === this.currentIdleId && this.presence === "idle" && !this.overlay) {
      this.currentIdleTime = this.activeClip.time;
    }
  }

  private returnToCurrentIdle(duration: number): void {
    const id = this.clips.has(this.currentIdleId) ? this.currentIdleId : "idle-neutral";
    // The saved time is useful while an idle remains active, but after speech
    // or a gesture its old phase is often the opposite of the current body
    // pose. Re-enter a loop through its nearest compatible frame instead.
    this.switchTo(id, duration, this.currentIdleTime, true);
  }

  private createProceduralIdleClips(): void {
    for (const [id, definition] of Object.entries(PROCEDURAL_IDLE_CLIPS)) {
      this.clips.set(id, {
        id,
        root: null,
        mixer: null,
        action: null,
        duration: definition.duration,
        loop: true,
        time: 0,
        bones: new Map(),
        reference: new Map(),
        sample: (time) => createProceduralIdlePose(
          definition.kind,
          time,
          this.targetBindRotations,
          this.normalizedRestPositions,
          this.idleVariations.get(id) ?? 0,
        ),
      });
    }
  }

  private seedIdleVariation(id: string, variation = Math.random() * Math.PI * 2): void {
    this.idleVariations.set(id, variation);
  }

  private startOverlay(id: string, clip: MotionClip, intensity: number, explicit: boolean): void {
    this.overlayTransitionFrom.clear();
    for (const [human, delta] of this.overlayDeltas) {
      this.overlayTransitionFrom.set(human, delta.clone());
    }
    const safeIntensity = THREE.MathUtils.clamp(intensity, 0, 1);
    this.overlay = {
      clip,
      id,
      startedAt: this.elapsedSeconds,
      endsAt: this.elapsedSeconds + clip.duration,
      intensity: safeIntensity,
      explicit,
    };
    this.overlayTransitionElapsed = 0;
    this.overlayTransitionDuration = explicit ? 0.34 : 0.26;
    this.overlayReleasing = false;
  }

  private beginOverlayRelease(): void {
    if (!this.overlay && !this.overlayReleasing) return;
    this.overlayTransitionFrom.clear();
    for (const [human, value] of this.overlayDeltas) this.overlayTransitionFrom.set(human, value.clone());
    this.overlay = null;
    this.overlayTransitionElapsed = 0;
    this.overlayTransitionDuration = 0.24;
    this.overlayReleasing = true;
  }

  private applyOverlay(delta: number): void {
    if (this.overlay && this.elapsedSeconds >= this.overlay.endsAt) {
      this.beginOverlayRelease();
    }
    if (!this.overlay && !this.overlayReleasing) return;

    this.overlayTransitionElapsed += delta;
    const blend = criticallyDampedBlend(this.overlayTransitionElapsed, this.overlayTransitionDuration);
    const desired = new Map<VRMHumanBoneName, THREE.Quaternion>();
    if (this.overlay) {
      const elapsed = Math.max(0, this.elapsedSeconds - this.overlay.startedAt);
      const pose = this.overlay.clip.sample(Math.min(elapsed, this.overlay.clip.duration));
      const fadeSeconds = Math.min(0.18, this.overlay.clip.duration * 0.18);
      const remaining = Math.max(0, this.overlay.endsAt - this.elapsedSeconds);
      const envelope = Math.min(1, elapsed / Math.max(0.001, fadeSeconds), remaining / Math.max(0.001, fadeSeconds));
      for (const human of UPPER_BODY_BONES) {
        const overlayRotation = pose.rotations.get(human);
        if (!overlayRotation) continue;
        const bind = this.targetBindRotations.get(human) ?? new THREE.Quaternion();
        const deltaRotation = bind.clone().invert().multiply(overlayRotation).normalize();
        desired.set(human, new THREE.Quaternion().slerp(deltaRotation, this.overlay.intensity * envelope).normalize());
      }
    }

    for (const human of UPPER_BODY_BONES) {
      const node = this.normalizedByHuman.get(human);
      if (!node) continue;
      const from = this.overlayTransitionFrom.get(human) ?? new THREE.Quaternion();
      const target = desired.get(human) ?? new THREE.Quaternion();
      const applied = from.clone().slerp(target, blend).normalize();
      node.quaternion.multiply(applied).normalize();
      this.overlayDeltas.set(human, applied);
    }

    if (this.overlayReleasing && this.overlayTransitionElapsed >= this.overlayTransitionDuration) {
      this.overlayReleasing = false;
      this.overlayTransitionFrom.clear();
      this.overlayDeltas.clear();
    }
  }

  private applySample(pose: NormalizedPose, amplitude = 1): void {
    const blend = criticallyDampedBlend(this.transitionElapsed, this.transitionDuration);
    const quaternion = new THREE.Quaternion();
    for (const [human, node] of this.normalizedByHuman) {
      const target = pose.rotations.get(human);
      if (!target) continue;
      const bind = this.targetBindRotations.get(human) ?? new THREE.Quaternion();
      const scaledTarget = bind.clone().slerp(target, THREE.MathUtils.clamp(amplitude, 0, 1.25)).normalize();
      const from = this.transitionFrom.get(human);
      if (from) {
        quaternion.copy(from.quaternion).slerp(scaledTarget, blend).normalize();
        node.quaternion.copy(quaternion);
        if (human === VRMHumanBoneName.Hips) {
          const rest = this.normalizedRestPositions.get(human) ?? pose.hipsPosition;
          const scaledHips = rest.clone().lerp(pose.hipsPosition, THREE.MathUtils.clamp(amplitude, 0, 1.25));
          node.position.lerpVectors(from.position, scaledHips, blend);
        }
      } else {
        node.quaternion.copy(scaledTarget);
        if (human === VRMHumanBoneName.Hips) {
          const rest = this.normalizedRestPositions.get(human) ?? pose.hipsPosition;
          node.position.copy(rest).lerp(pose.hipsPosition, THREE.MathUtils.clamp(amplitude, 0, 1.25));
        }
      }
    }
  }

  /**
   * Filter only the continuous speech body pose. Explicit protocol gestures
   * retain their envelope timing so acknowledgements and greetings do not feel
   * delayed. The filter runs after talk + automatic accents and before gaze.
   */
  private applySpeechPoseFilter(delta: number): void {
    if (this.presence !== "speaking" || this.overlay?.explicit) {
      if (this.overlay?.explicit) this.primeSpeechPoseFilter();
      return;
    }
    const safeDelta = Math.max(0.001, delta);
    for (const [human, node] of this.normalizedByHuman) {
      const raw = node.quaternion.clone();
      const rawHipsPosition = human === VRMHumanBoneName.Hips ? node.position.clone() : null;
      const previousRaw = this.speechRawRotations.get(human) ?? this.speechFilteredRotations.get(human) ?? raw;
      const filtered = this.speechFilteredRotations.get(human) ?? node.quaternion.clone();
      const angularSpeed = previousRaw.angleTo(raw) / safeDelta;
      const hipsSpeed = rawHipsPosition && this.speechRawHipsPosition
        ? this.speechRawHipsPosition.distanceTo(rawHipsPosition) / safeDelta
        : 0;
      const blend = speechPoseSmoothingBlend(safeDelta, speechPoseSmoothingSeconds(human, angularSpeed, hipsSpeed));
      filtered.slerp(raw, blend).normalize();
      node.quaternion.copy(filtered);
      this.speechFilteredRotations.set(human, filtered);
      this.speechRawRotations.set(human, raw);

      if (rawHipsPosition) {
        const filteredPosition = this.speechFilteredHipsPosition ?? rawHipsPosition.clone();
        filteredPosition.lerp(rawHipsPosition, blend);
        node.position.copy(filteredPosition);
        this.speechFilteredHipsPosition = filteredPosition;
        // Preserve the source pose before replacing it with the filtered one.
        this.speechRawHipsPosition = rawHipsPosition;
      }
    }
  }

  private primeSpeechPoseFilter(): void {
    this.speechFilteredRotations.clear();
    this.speechRawRotations.clear();
    for (const [human, node] of this.normalizedByHuman) {
      this.speechFilteredRotations.set(human, node.quaternion.clone());
    }
    const hips = this.normalizedByHuman.get(VRMHumanBoneName.Hips);
    this.speechFilteredHipsPosition = hips?.position.clone() ?? null;
    this.speechRawHipsPosition = null;
  }

  private resetSpeechPoseFilter(): void {
    this.speechFilteredRotations.clear();
    this.speechRawRotations.clear();
    this.speechFilteredHipsPosition = null;
    this.speechRawHipsPosition = null;
  }

  dispose(): void {
    this.disposed = true;
    for (const clip of this.clips.values()) {
      clip.action?.stop();
      if (clip.root) clip.mixer?.uncacheRoot(clip.root);
    }
    this.clips.clear();
  }
}

export function IrisAvatarCanvas() {
  const hostRef = useRef<HTMLElement | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "failed">("loading");

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;
    // jsdom and very old WebViews expose a canvas element but not a usable
    // WebGL context. Do not attempt a renderer construction in that case.
    if (typeof WebGLRenderingContext === "undefined") {
      setStatus("failed");
      return undefined;
    }
    let disposed = false;
    let frame = 0;
    let renderer: THREE.WebGLRenderer | null = null;
    let resizeObserver: ResizeObserver | null = null;
    let vrm: VRM | null = null;
    let motion: AvatarMotionPlayer | null = null;
    const emotionController = new EmotionBlendController();
    const blinkScheduler = new BlinkScheduler();
    let currentUtterance: string | null = null;
    let gestureTimer: number | null = null;
    const audio = new AvatarAudioQueue();
    const timer = new THREE.Timer();
    timer.connect(document);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, 1, 0.01, 100);
    let lastDpr = Math.min(window.devicePixelRatio || 1, 2);
    let slowFrames = 0;
    let fastFrames = 0;
    let animationRunning = false;
    let liveConversation = false;
    let presence: AvatarPresence = "idle";
    const reducedMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");

    const setPresence = (next: AvatarPresence) => {
      if (presence === next) return;
      presence = next;
      motion?.setPresence(next);
      protocol.send("avatar.state.changed", { state: next });
    };
    const clearMouth = () => {
      const expressions = vrm?.expressionManager;
      if (!expressions) return;
      for (const key of [VRMExpressionPresetName.Aa, VRMExpressionPresetName.Ih, VRMExpressionPresetName.Ou, VRMExpressionPresetName.Ee, VRMExpressionPresetName.Oh]) {
        expressions.setValue(key, 0);
      }
    };
    const applyEmotionExpressions = (weights: ReadonlyMap<Emotion, number>) => {
      const expressions = vrm?.expressionManager;
      if (!expressions) return;
      const values = new Map<ExpressionName, number>();
      for (const [emotion, weight] of weights) {
        if (weight <= 0.0005) continue;
        const key = emotionPreset(emotion);
        values.set(key, Math.max(values.get(key) ?? 0, weight));
      }
      for (const key of EMOTION_EXPRESSION_KEYS) expressions.setValue(key, 0);
      for (const [key, value] of values) expressions.setValue(key, Math.min(1, value));
    };
    const applyEmotion = (value: string, intensity = 1) => {
      const emotion = parseEmotion(value);
      emotionController.setTarget(emotion, intensity, performance.now());
      motion?.setMotionProfile(EMOTION_PROFILES[emotion].motionProfile);
    };
    const releaseEmotion = () => {
      const snapshot = emotionController.releaseToNeutral(performance.now());
      if (snapshot.targetEmotion === "neutral") motion?.setMotionProfile(EMOTION_PROFILES.neutral.motionProfile);
    };
    const playGesture = async (client: AvatarProtocolClient, gesture: string, intensity: number, replyTo: string) => {
      // The speech loop is selected by setSpeaking. Starting it here as a
      // finite gesture would make it expire and restart while audio continues.
      if (!motion || isSpeechGesture(gesture)) return;
      const result = await motion.trigger(gesture, intensity);
      if (!motion.isGestureGenerationCurrent(result.generation)) return;
      client.send("avatar.gesture.started", { gesture, intensity }, replyTo);
      if (gestureTimer !== null) window.clearTimeout(gestureTimer);
      gestureTimer = window.setTimeout(() => {
        if (motion?.isGestureGenerationCurrent(result.generation)) {
          client.send("avatar.gesture.finished", { gesture, intensity }, replyTo);
        }
      }, result.durationMs);
    };
    const protocol = new AvatarProtocolClient({
      url: avatarWebSocketUrl(),
      onConnectionChange: (connected) => { if (connected) protocol.send("avatar.state.changed", { state: presence }); },
      onMessage: (message) => { void handleMessage(message); },
    });
    const playbackHandlers = (utteranceId: string, replyTo: string) => ({
        onStarted: () => {
          currentUtterance = utteranceId;
          motion?.setSpeaking(true);
          setPresence("speaking");
        protocol.send("avatar.playback.started", { utterance_id: utteranceId, client_latency_ms: 0 }, replyTo);
      },
      onFinished: () => {
          clearMouth();
          motion?.setSpeaking(false);
          releaseEmotion();
          if (currentUtterance === utteranceId) currentUtterance = null;
          setPresence(liveConversation ? "listening" : "idle");
        protocol.send("avatar.playback.finished", { utterance_id: utteranceId, client_latency_ms: 0 }, replyTo);
      },
      onFailed: (reason: string) => {
        clearMouth();
          motion?.setSpeaking(false);
          releaseEmotion();
          if (currentUtterance === utteranceId) currentUtterance = null;
          setPresence(liveConversation ? "listening" : "idle");
        protocol.send("avatar.playback.failed", { utterance_id: utteranceId, reason, client_latency_ms: 0 }, replyTo);
      },
    });
    const handleMessage = async (message: AvatarEnvelope): Promise<void> => {
      const payload = message.payload;
      try {
        switch (message.type) {
          case "avatar.ping":
            protocol.send("avatar.pong", { reply_to: message.message_id });
            return;
          case "avatar.speak": {
            const utterance = payloadString(payload, "utterance_id");
            const gesture = payloadString(payload, "gesture", "talk");
            if (payloadBoolean(payload, "interrupt", true)) motion?.stop();
            applyEmotion(payloadString(payload, "emotion"), payloadNumber(payload, "gesture_intensity"));
            liveConversation = false;
            motion?.setSpeechClip(speechClipId(gesture));
            setPresence("thinking");
            void playGesture(protocol, gesture, payloadNumber(payload, "gesture_intensity"), message.message_id);
            await audio.playUrl(resolveApiUrl(payloadString(payload, "audio_url")), playbackHandlers(utterance, message.message_id));
            break;
          }
          case "avatar.stream.start": {
            const utterance = payloadString(payload, "utterance_id");
            if (payloadBoolean(payload, "interrupt", true)) {
              audio.stop();
              motion?.stop();
            }
            liveConversation = true;
            setPresence("thinking");
            audio.beginStream(playbackHandlers(utterance, message.message_id));
            break;
          }
          case "avatar.stream.metadata": {
            const gesture = payloadString(payload, "gesture", "talk");
            applyEmotion(payloadString(payload, "emotion"), payloadNumber(payload, "gesture_intensity"));
            motion?.setSpeechClip(speechClipId(gesture));
            void playGesture(protocol, gesture, payloadNumber(payload, "gesture_intensity"), message.message_id);
            break;
          }
          case "avatar.stream.segment":
            await audio.enqueueBase64Wav(payloadNumber(payload, "sequence", 0), payloadString(payload, "audio_base64"));
            protocol.send("avatar.stream.received", {
              utterance_id: payloadString(payload, "utterance_id"),
              sequence: payloadNumber(payload, "sequence", 0),
              client_latency_ms: 0,
            });
            break;
          case "avatar.stream.end":
            audio.endStream();
            break;
          case "avatar.stop":
            audio.stop();
            motion?.stop();
            clearMouth();
            releaseEmotion();
            setPresence(liveConversation ? "listening" : "idle");
            break;
          case "avatar.state": {
            const requested = parseAvatarPresence(payloadString(payload, "state"));
            liveConversation = requested === "listening" || requested === "thinking";
            setPresence(requested);
            break;
          }
          case "avatar.emotion":
            applyEmotion(payloadString(payload, "emotion"), payloadNumber(payload, "intensity"));
            break;
          case "avatar.gesture":
            void playGesture(protocol, payloadString(payload, "gesture", "talk"), payloadNumber(payload, "intensity"), message.message_id);
            break;
          case "avatar.audio.mute":
            audio.setMuted(payloadBoolean(payload, "muted"));
            break;
          // Overlay configuration is intentionally ignored by the in-app renderer.
          case "avatar.overlay.configure":
            break;
          default:
            return;
        }
        protocol.send("avatar.ack", { reply_to: message.message_id, accepted: true });
      } catch (error) {
        protocol.send("avatar.ack", {
          reply_to: message.message_id,
          accepted: false,
          error: error instanceof Error ? error.message : "Avatar command failed",
        });
      }
    };

    const fitPortrait = () => {
      if (!vrm) return;
      const bounds = new THREE.Box3().setFromObject(vrm.scene);
      const size = bounds.getSize(new THREE.Vector3());
      // Match the Unity portrait camera: keep the face and upper torso in
      // frame instead of fitting the complete doll. The target is measured
      // from the top of the rig so changes to hair, shoes, or spring-bone
      // bounds do not pull the face away from the center of the shot.
      const portraitHeight = Math.max(0.1, size.y * 0.48);
      const framingPadding = 1.12;
      const halfHeight = portraitHeight * 0.5 * framingPadding;
      const portraitWidth = portraitHeight * Math.max(0.72, camera.aspect) * 0.9;
      const halfWidth = portraitWidth * 0.5 * framingPadding;
      const verticalDistance = halfHeight / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
      const horizontalFov = 2 * Math.atan(
        Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * camera.aspect,
      );
      const horizontalDistance = halfWidth / Math.tan(horizontalFov / 2);
      const center = bounds.getCenter(new THREE.Vector3());
      const targetY = bounds.max.y - portraitHeight * 0.52;
      const distance = Math.max(verticalDistance, horizontalDistance, 0.1);
      camera.position.set(center.x, targetY, distance + center.z);
      camera.lookAt(center.x, targetY, center.z);
      camera.updateProjectionMatrix();
    };
    const resize = () => {
      if (!renderer) return;
      const width = Math.max(1, host.clientWidth);
      const height = Math.max(1, host.clientHeight);
      camera.aspect = width / height;
      renderer.setSize(width, height, false);
      renderer.setPixelRatio(lastDpr);
      fitPortrait();
    };
    const animate = () => {
      if (disposed || !renderer) {
        animationRunning = false;
        return;
      }
      if (document.hidden) {
        animationRunning = false;
        timer.reset();
        return;
      }
      frame = window.requestAnimationFrame(animate);
      timer.update();
      const delta = Math.min(timer.getDelta(), 0.1);
      if (delta > 1 / 45) { slowFrames += 1; fastFrames = 0; }
      else { fastFrames += 1; slowFrames = 0; }
      if (slowFrames > 135 && lastDpr > 1) { lastDpr = 1; resize(); slowFrames = 0; }
      if (fastFrames > 600 && lastDpr < Math.min(window.devicePixelRatio || 1, 2)) { lastDpr = Math.min(window.devicePixelRatio || 1, 2); resize(); fastFrames = 0; }
      const mouthSignal = audio.mouthSignal(delta);
      if (vrm?.expressionManager) {
        clearMouth();
        const emotionSnapshot = emotionController.update(delta, performance.now());
        applyEmotionExpressions(emotionSnapshot.weights);
        const blink = blinkScheduler.update(performance.now());
        vrm.expressionManager.setValue(VRMExpressionPresetName.Blink, Math.max(0, blink));
        if (mouthSignal.level > 0.018) {
          const viseme = speechVisemeForTone(mouthSignal.tone);
          vrm.expressionManager.setValue(viseme, Math.min(1, mouthSignal.level * 1.5));
        }
      }
      motion?.update(delta);
      motion?.applyPreVrmPose(delta);
      vrm?.update(delta);
      renderer.render(scene, camera);
    };
    const startAnimation = () => {
      if (disposed || animationRunning || document.hidden) return;
      animationRunning = true;
      frame = window.requestAnimationFrame(animate);
    };
    const handleVisibilityChange = () => {
      if (document.hidden) {
        if (frame) window.cancelAnimationFrame(frame);
        frame = 0;
        animationRunning = false;
        timer.reset();
        return;
      }
      timer.reset();
      startAnimation();
    };
    const handleReducedMotionChange = (event: MediaQueryListEvent) => {
      motion?.setReducedMotion(event.matches);
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    reducedMotionQuery.addEventListener("change", handleReducedMotionChange);

    try {
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: "high-performance" });
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.setClearColor(0x000000, 0);
      renderer.setPixelRatio(lastDpr);
      renderer.domElement.className = "iris-avatar-canvas";
      host.append(renderer.domElement);
      scene.add(new THREE.HemisphereLight(0xffffff, 0x2d2439, 2.2));
      const key = new THREE.DirectionalLight(0xffffff, 2.4);
      key.position.set(1.5, 2.5, 3);
      scene.add(key);
      resizeObserver = new ResizeObserver(resize);
      resizeObserver.observe(host);
      resize();
      const loader = new GLTFLoader();
      loader.register((parser) => new VRMLoaderPlugin(parser));
      void loader.loadAsync("/avatar/IRIS.vrm").then((gltf) => {
        if (disposed) return;
        vrm = gltf.userData.vrm as VRM;
        VRMUtils.rotateVRM0(vrm);
        vrm.scene.traverse((node) => { node.frustumCulled = false; });
        scene.add(vrm.scene);
        motion = new AvatarMotionPlayer(vrm);
        motion.setReducedMotion(reducedMotionQuery.matches);
        // The websocket can receive a presence command while the VRM file is
        // still decoding. Apply the most recent requested state before the
        // first rendered frame so it cannot flash an unrelated idle pose.
        motion.setPresence(presence);
        vrm.update(0);
        applyEmotionExpressions(emotionController.snapshot().weights);
        void motion.startIdle().then(() => { if (!disposed) fitPortrait(); });
        fitPortrait();
        setStatus("ready");
      }).catch(() => { if (!disposed) setStatus("failed"); });
      protocol.start();
      startAnimation();
    } catch {
      setStatus("failed");
    }

    return () => {
      disposed = true;
      if (frame) window.cancelAnimationFrame(frame);
      animationRunning = false;
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      reducedMotionQuery.removeEventListener("change", handleReducedMotionChange);
      timer.dispose();
      if (gestureTimer !== null) window.clearTimeout(gestureTimer);
      resizeObserver?.disconnect();
      protocol.stop();
      audio.dispose();
      motion?.dispose();
      if (vrm) VRMUtils.deepDispose(vrm.scene);
      renderer?.dispose();
      renderer?.domElement.remove();
    };
  }, []);

  return <aside ref={hostRef} className="in-app-avatar-stage" aria-label="Аватар Iris">
    {status !== "ready" && <span className="iris-avatar-status">{status === "failed" ? "Не удалось загрузить аватар" : "Загрузка Iris…"}</span>}
  </aside>;
}
