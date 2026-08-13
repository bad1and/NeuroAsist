import type { Emotion } from "../generated/character-protocol";

export type IdleCategory = "micro" | "normal" | "long";
export type AvatarPresence = "idle" | "listening" | "thinking" | "speaking";

export type IdleCandidate = {
  id: string;
  category: IdleCategory;
  durationSeconds: number;
  cooldownSeconds: number;
  /** Relative chance amongst eligible idles. Defaults to one for legacy callers. */
  selectionWeight?: number;
  /** Similar phrases are deliberately separated even when their ids differ. */
  family?: string;
};

export type IdleSchedulerProfile = {
  intervalMinSeconds: number;
  intervalMaxSeconds: number;
  alternativeProbability: number;
};

export type IdleSchedulerContext = {
  speaking: boolean;
  gesturePlaying: boolean;
  presence?: AvatarPresence;
};

export type IdlePhrasePlan = {
  durationSeconds: number;
  recoverySeconds: number;
  amplitude: number;
  playbackRate: number;
  variation: number;
};

export type OrganicMotionSample = {
  hipsX: number;
  chestPitch: number;
  chestYaw: number;
  headPitch: number;
  headYaw: number;
  headRoll: number;
};

export type SpeechAccentCandidate = {
  id: string;
  cooldownSeconds: number;
  selectionWeight?: number;
};

export type EmotionProfile = {
  weight: number;
  attackMs: number;
  minimumHoldMs: number;
  releaseMs: number;
  motionProfile: string;
};

export const EMOTION_PROFILES: Record<Emotion, EmotionProfile> = {
  neutral: { weight: 0.35, attackMs: 360, minimumHoldMs: 700, releaseMs: 520, motionProfile: "idle" },
  happy: { weight: 0.8, attackMs: 340, minimumHoldMs: 850, releaseMs: 480, motionProfile: "energetic" },
  sad: { weight: 0.7, attackMs: 480, minimumHoldMs: 1_000, releaseMs: 620, motionProfile: "calm" },
  angry: { weight: 0.75, attackMs: 290, minimumHoldMs: 900, releaseMs: 580, motionProfile: "tense" },
  annoyed: { weight: 0.65, attackMs: 340, minimumHoldMs: 850, releaseMs: 540, motionProfile: "tense" },
  smirk: { weight: 0.6, attackMs: 380, minimumHoldMs: 800, releaseMs: 480, motionProfile: "playful" },
  thinking: { weight: 0.6, attackMs: 420, minimumHoldMs: 900, releaseMs: 520, motionProfile: "thoughtful" },
  surprised: { weight: 0.8, attackMs: 220, minimumHoldMs: 700, releaseMs: 540, motionProfile: "alert" },
  embarrassed: { weight: 0.65, attackMs: 440, minimumHoldMs: 850, releaseMs: 540, motionProfile: "shy" },
  concerned: { weight: 0.7, attackMs: 400, minimumHoldMs: 900, releaseMs: 580, motionProfile: "attentive" },
};

const EMOTIONS = Object.keys(EMOTION_PROFILES) as Emotion[];

export function parseEmotion(value: string | undefined): Emotion {
  const normalized = (value ?? "neutral").toLowerCase() as Emotion;
  return normalized in EMOTION_PROFILES ? normalized : "neutral";
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function approach(current: number, target: number, deltaSeconds: number, durationMs: number): number {
  if (Math.abs(target - current) < 0.0005) return target;
  if (durationMs <= 0) return target;
  // Three time constants reach roughly 95% of the requested transition time.
  const factor = 1 - Math.exp(-deltaSeconds / (durationMs / 3_000));
  return current + (target - current) * clamp(factor, 0, 1);
}

export type EmotionBlendSnapshot = {
  weights: ReadonlyMap<Emotion, number>;
  currentEmotion: Emotion;
  targetEmotion: Emotion;
  targetIntensity: number;
  generation: number;
  heldUntilMs: number;
};

/**
 * Renderer-independent face state. It keeps expression blending separate from
 * mouth visemes and blink, so a TTS update cannot abruptly erase an emotion.
 */
export class EmotionBlendController {
  private readonly weights = new Map<Emotion, number>();
  private currentEmotion: Emotion = "neutral";
  private targetEmotion: Emotion = "neutral";
  private targetIntensity = 1;
  private targetWeight = EMOTION_PROFILES.neutral.weight;
  private generation = 0;
  private heldUntilMs = 0;
  private lastNowMs = 0;
  private releaseRequested = false;

  constructor() {
    for (const emotion of EMOTIONS) this.weights.set(emotion, 0);
    this.weights.set("neutral", EMOTION_PROFILES.neutral.weight);
  }

  setTarget(value: string | undefined, intensity = 1, nowMs = 0): EmotionBlendSnapshot {
    this.update(0, nowMs);
    const emotion = parseEmotion(value);
    const profile = EMOTION_PROFILES[emotion];
    const nextIntensity = clamp(intensity, 0, 1);
    const changed = emotion !== this.targetEmotion || Math.abs(nextIntensity - this.targetIntensity) > 0.001;
    this.releaseRequested = false;
    this.targetEmotion = emotion;
    this.targetIntensity = nextIntensity;
    this.targetWeight = profile.weight * nextIntensity;
    if (changed) this.generation += 1;
    this.heldUntilMs = nowMs + profile.minimumHoldMs;
    return this.snapshot();
  }

  releaseToNeutral(nowMs = this.lastNowMs): EmotionBlendSnapshot {
    if (nowMs < this.heldUntilMs && this.targetEmotion !== "neutral") {
      this.releaseRequested = true;
      return this.snapshot();
    }
    return this.setTarget("neutral", 1, nowMs);
  }

  update(deltaSeconds: number, nowMs = this.lastNowMs + Math.max(0, deltaSeconds) * 1_000): EmotionBlendSnapshot {
    this.lastNowMs = Math.max(this.lastNowMs, nowMs);
    if (this.releaseRequested && this.targetEmotion !== "neutral" && this.lastNowMs >= this.heldUntilMs) {
      this.releaseRequested = false;
      this.setTarget("neutral", 1, this.lastNowMs);
    }
    const safeDelta = Math.max(0, deltaSeconds);
    for (const emotion of EMOTIONS) {
      const current = this.weights.get(emotion) ?? 0;
      const desired = emotion === this.targetEmotion ? this.targetWeight : 0;
      const duration = emotion === this.targetEmotion
        ? EMOTION_PROFILES[emotion].attackMs
        : EMOTION_PROFILES[emotion].releaseMs;
      this.weights.set(emotion, approach(current, desired, safeDelta, duration));
    }

    const targetValue = this.weights.get(this.targetEmotion) ?? 0;
    if (Math.abs(targetValue - this.targetWeight) < 0.002) {
      this.weights.set(this.targetEmotion, this.targetWeight);
      this.currentEmotion = this.targetEmotion;
    }
    return this.snapshot();
  }

  snapshot(): EmotionBlendSnapshot {
    return {
      weights: new Map(this.weights),
      currentEmotion: this.currentEmotion,
      targetEmotion: this.targetEmotion,
      targetIntensity: this.targetIntensity,
      generation: this.generation,
      heldUntilMs: this.heldUntilMs,
    };
  }
}

export class IdleMotionScheduler {
  private profile: IdleSchedulerProfile = {
    intervalMinSeconds: 6,
    intervalMaxSeconds: 15,
    alternativeProbability: 1,
  };
  private readonly lastPlayedAt = new Map<string, number>();
  private readonly recentIds: string[] = [];
  private readonly recentFamilies: string[] = [];
  private nextDueAt = 0;
  private previousId: string | null = null;
  private previousCategory: IdleCategory | null = null;
  private generation = 0;

  constructor(private readonly random: () => number = Math.random) {}

  setProfile(profile: Partial<IdleSchedulerProfile>): void {
    const minimum = Math.max(0.1, profile.intervalMinSeconds ?? this.profile.intervalMinSeconds);
    const maximum = Math.max(minimum, profile.intervalMaxSeconds ?? this.profile.intervalMaxSeconds);
    this.profile = {
      intervalMinSeconds: minimum,
      intervalMaxSeconds: maximum,
      alternativeProbability: clamp(profile.alternativeProbability ?? this.profile.alternativeProbability, 0, 1),
    };
    this.generation += 1;
  }

  start(nowSeconds: number, initialId?: string): void {
    if (initialId) {
      // The base loop is already visible when scheduling begins. Remember it
      // so the first deliberate idle is guaranteed to be a different pose.
      this.previousId = initialId;
      this.lastPlayedAt.set(initialId, nowSeconds);
      this.recentIds.unshift(initialId);
      this.recentIds.splice(4);
    }
    this.nextDueAt = nowSeconds + this.randomInterval();
  }

  stop(): void {
    this.generation += 1;
    this.nextDueAt = Number.POSITIVE_INFINITY;
  }

  getGeneration(): number {
    return this.generation;
  }

  schedule(
    nowSeconds: number,
    candidates: readonly IdleCandidate[],
    context: IdleSchedulerContext,
  ): IdleCandidate | null {
    if (nowSeconds < this.nextDueAt) return null;
    this.nextDueAt = nowSeconds + this.randomInterval();
    if (context.gesturePlaying || context.presence === "listening" || context.presence === "thinking" || this.random() > this.profile.alternativeProbability) return null;

    const eligible = candidates.filter((candidate) => {
      if (context.speaking && candidate.category === "long") return false;
      if (candidate.id === this.previousId && candidates.length > 1) return false;
      const lastPlayed = this.lastPlayedAt.get(candidate.id);
      return lastPlayed === undefined || nowSeconds - lastPlayed >= candidate.cooldownSeconds;
    });
    if (eligible.length === 0) return null;

    const useDiversityPressure = candidates.length >= 3;
    const candidateWeight = (candidate: IdleCandidate): number => {
      let weight = Math.max(0, candidate.selectionWeight ?? 1);
      if (!useDiversityPressure) return weight;
      const family = candidate.family ?? candidate.id;
      if (this.recentIds.includes(candidate.id)) weight *= 0.14;
      if (this.recentFamilies.includes(family)) weight *= 0.42;
      if (candidate.category === this.previousCategory) weight *= 0.62;
      return weight;
    };
    const totalWeight = eligible.reduce((total, candidate) => total + candidateWeight(candidate), 0);
    if (totalWeight <= 0) return null;
    let cursor = clamp(this.random(), 0, 0.999999) * totalWeight;
    let selected = eligible[eligible.length - 1];
    for (const candidate of eligible) {
      cursor -= candidateWeight(candidate);
      if (cursor < 0) {
        selected = candidate;
        break;
      }
    }
    this.previousId = selected.id;
    this.previousCategory = selected.category;
    this.lastPlayedAt.set(selected.id, nowSeconds);
    this.recentIds.unshift(selected.id);
    this.recentIds.splice(4);
    this.recentFamilies.unshift(selected.family ?? selected.id);
    this.recentFamilies.splice(3);
    return selected;
  }

  /**
   * A phrase is intentionally shorter than the source loop. Iris enters at a
   * compatible phase, says something through the body, then returns to a
   * living base pose before a viewer can recognize a repeated cycle.
   */
  planPhrase(candidate: IdleCandidate): IdlePhrasePlan {
    const durationRatio = 0.64 + this.random() * 0.28;
    return {
      durationSeconds: Math.max(1.2, candidate.durationSeconds * durationRatio),
      recoverySeconds: 0.8 + this.random() * 3.2,
      amplitude: 0.8 + this.random() * 0.36,
      playbackRate: 0.9 + this.random() * 0.22,
      variation: this.random() * Math.PI * 2,
    };
  }

  deferUntil(nowSeconds: number): void {
    // `nowSeconds` already includes the phrase recovery. Adding another idle
    // interval here made the next movement wait twice after every phrase.
    this.nextDueAt = nowSeconds;
  }

  private randomInterval(): number {
    // A squared random value creates many normal pauses and occasional long
    // rests. Uniform intervals were the main source of the old metronome.
    const drift = clamp(this.random(), 0, 1) ** 2;
    return this.profile.intervalMinSeconds
      + (this.profile.intervalMaxSeconds - this.profile.intervalMinSeconds) * drift;
  }
}

const ORGANIC_ZERO: OrganicMotionSample = {
  hipsX: 0,
  chestPitch: 0,
  chestYaw: 0,
  headPitch: 0,
  headYaw: 0,
  headRoll: 0,
};

function organicRange(presence: AvatarPresence): OrganicMotionSample {
  switch (presence) {
    case "listening":
      return { hipsX: 0.0014, chestPitch: 0.0035, chestYaw: 0.003, headPitch: 0.005, headYaw: 0.007, headRoll: 0.003 };
    case "thinking":
      return { hipsX: 0.0025, chestPitch: 0.007, chestYaw: 0.011, headPitch: 0.016, headYaw: 0.034, headRoll: 0.007 };
    case "speaking":
      return { hipsX: 0.002, chestPitch: 0.005, chestYaw: 0.007, headPitch: 0.008, headYaw: 0.016, headRoll: 0.004 };
    default:
      return { hipsX: 0.0038, chestPitch: 0.0085, chestYaw: 0.014, headPitch: 0.015, headYaw: 0.032, headRoll: 0.008 };
  }
}

/**
 * Smooth, non-periodic postural drift. It does not replace an authored clip;
 * it prevents its neutral moments from restarting at exactly the same pose.
 */
export class OrganicMotionDirector {
  private value: OrganicMotionSample = { ...ORGANIC_ZERO };
  private target: OrganicMotionSample = { ...ORGANIC_ZERO };
  private nextRetargetAt = 0;
  private presence: AvatarPresence = "idle";

  constructor(private readonly random: () => number = Math.random) {}

  reset(nowSeconds = 0, presence: AvatarPresence = "idle"): void {
    this.value = { ...ORGANIC_ZERO };
    this.presence = presence;
    this.retarget(nowSeconds, presence);
  }

  update(nowSeconds: number, deltaSeconds: number, presence: AvatarPresence, suppress = false): OrganicMotionSample {
    if (presence !== this.presence || nowSeconds >= this.nextRetargetAt) {
      this.presence = presence;
      this.retarget(nowSeconds, presence);
    }
    const response = 1 - Math.exp(-Math.max(0, deltaSeconds) * 2.45);
    for (const key of Object.keys(ORGANIC_ZERO) as (keyof OrganicMotionSample)[]) {
      this.value[key] += (this.target[key] - this.value[key]) * response;
    }
    if (!suppress) return { ...this.value };
    return {
      hipsX: this.value.hipsX * 0.3,
      chestPitch: this.value.chestPitch * 0.3,
      chestYaw: this.value.chestYaw * 0.3,
      headPitch: this.value.headPitch * 0.3,
      headYaw: this.value.headYaw * 0.3,
      headRoll: this.value.headRoll * 0.3,
    };
  }

  private retarget(nowSeconds: number, presence: AvatarPresence): void {
    const range = organicRange(presence);
    const centered = (limit: number) => (this.random() * 2 - 1) * limit;
    this.target = {
      hipsX: centered(range.hipsX),
      chestPitch: centered(range.chestPitch) + (presence === "thinking" ? range.chestPitch * 0.35 : 0),
      chestYaw: centered(range.chestYaw),
      headPitch: centered(range.headPitch) + (presence === "thinking" ? range.headPitch * 0.4 : 0),
      headYaw: centered(range.headYaw),
      headRoll: centered(range.headRoll),
    };
    // Retargets land on uneven holds, so even the quiet in-between moments
    // have no fixed period. Listening holds longer and keeps its gaze forward.
    const base = presence === "listening" ? 2.4 : presence === "thinking" ? 1.7 : 0.95;
    const spread = presence === "listening" ? 4.6 : presence === "idle" ? 3.1 : 3.9;
    this.nextRetargetAt = nowSeconds + base + (this.random() ** 2) * spread;
  }
}

/**
 * Keeps conversational accents sparse.  Speech has a visible cadence already;
 * an accent is punctuation, never a replacement for the talking loop.
 */
export class SpeechAccentScheduler {
  private readonly lastPlayedAt = new Map<string, number>();
  private previousId: string | null = null;
  private nextDueAt = 0;

  constructor(private readonly random: () => number = Math.random) {}

  start(nowSeconds: number): void {
    this.nextDueAt = nowSeconds + this.nextInterval();
  }

  stop(): void {
    this.nextDueAt = Number.POSITIVE_INFINITY;
    this.previousId = null;
  }

  schedule(
    nowSeconds: number,
    candidates: readonly SpeechAccentCandidate[],
    context: { speaking: boolean; explicitGesturePlaying: boolean },
  ): SpeechAccentCandidate | null {
    if (!context.speaking || context.explicitGesturePlaying || nowSeconds < this.nextDueAt) return null;
    this.nextDueAt = nowSeconds + this.nextInterval();
    const eligible = candidates.filter((candidate) => {
      if (candidate.id === this.previousId && candidates.length > 1) return false;
      const lastPlayed = this.lastPlayedAt.get(candidate.id);
      return lastPlayed === undefined || nowSeconds - lastPlayed >= candidate.cooldownSeconds;
    });
    if (eligible.length === 0) return null;

    const totalWeight = eligible.reduce((total, candidate) => total + Math.max(0, candidate.selectionWeight ?? 1), 0);
    if (totalWeight <= 0) return null;
    let cursor = clamp(this.random(), 0, 0.999999) * totalWeight;
    let selected = eligible[eligible.length - 1];
    for (const candidate of eligible) {
      cursor -= Math.max(0, candidate.selectionWeight ?? 1);
      if (cursor < 0) {
        selected = candidate;
        break;
      }
    }
    this.previousId = selected.id;
    this.lastPlayedAt.set(selected.id, nowSeconds);
    return selected;
  }

  private nextInterval(): number {
    // Seven to twelve seconds gives an answer room to breathe and avoids a
    // metronomic "talk with hands" loop during long answers.
    return 7 + this.random() * 5;
  }
}

/**
 * A small state machine rather than a modulo timer. It avoids the uncanny
 * regular 4.2-second blink and still gives a deterministic, testable output.
 */
export class BlinkScheduler {
  private nextBlinkAtMs = Number.POSITIVE_INFINITY;
  private blinkStartedAtMs: number | null = null;
  private blinkDurationMs = 140;

  constructor(private readonly random: () => number = Math.random) {}

  start(nowMs = 0): void {
    this.blinkStartedAtMs = null;
    this.nextBlinkAtMs = nowMs + this.randomIntervalMs();
  }

  update(nowMs: number): number {
    if (this.nextBlinkAtMs === Number.POSITIVE_INFINITY) this.start(nowMs);
    if (this.blinkStartedAtMs === null && nowMs >= this.nextBlinkAtMs) {
      this.blinkStartedAtMs = nowMs;
      // A slight duration range keeps blinks from reading as a looping effect.
      this.blinkDurationMs = 118 + this.random() * 52;
    }
    if (this.blinkStartedAtMs === null) return 0;

    const progress = Math.max(0, (nowMs - this.blinkStartedAtMs) / this.blinkDurationMs);
    if (progress >= 1) {
      this.blinkStartedAtMs = null;
      // Rare, natural double blink; otherwise leave a comfortably long pause.
      const doubleBlink = this.random() < 0.12;
      this.nextBlinkAtMs = nowMs + (doubleBlink ? 115 + this.random() * 95 : this.randomIntervalMs());
      return 0;
    }
    const half = progress <= 0.46 ? progress / 0.46 : (1 - progress) / 0.54;
    const eased = clamp(half, 0, 1);
    return eased * eased * (3 - 2 * eased);
  }

  private randomIntervalMs(): number {
    return 2_800 + this.random() * 3_600;
  }
}
