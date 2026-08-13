import type { Emotion } from "../generated/character-protocol";

export type IdleCategory = "micro" | "normal" | "long";

export type IdleCandidate = {
  id: string;
  category: IdleCategory;
  durationSeconds: number;
  cooldownSeconds: number;
};

export type IdleSchedulerProfile = {
  intervalMinSeconds: number;
  intervalMaxSeconds: number;
  alternativeProbability: number;
};

export type IdleSchedulerContext = {
  speaking: boolean;
  gesturePlaying: boolean;
};

export type EmotionProfile = {
  weight: number;
  attackMs: number;
  minimumHoldMs: number;
  releaseMs: number;
  motionProfile: string;
};

export const EMOTION_PROFILES: Record<Emotion, EmotionProfile> = {
  neutral: { weight: 0.35, attackMs: 180, minimumHoldMs: 450, releaseMs: 260, motionProfile: "idle" },
  happy: { weight: 0.8, attackMs: 150, minimumHoldMs: 550, releaseMs: 240, motionProfile: "energetic" },
  sad: { weight: 0.7, attackMs: 240, minimumHoldMs: 700, releaseMs: 320, motionProfile: "calm" },
  angry: { weight: 0.75, attackMs: 130, minimumHoldMs: 600, releaseMs: 300, motionProfile: "tense" },
  annoyed: { weight: 0.65, attackMs: 160, minimumHoldMs: 550, releaseMs: 280, motionProfile: "tense" },
  smirk: { weight: 0.6, attackMs: 180, minimumHoldMs: 500, releaseMs: 240, motionProfile: "playful" },
  thinking: { weight: 0.6, attackMs: 180, minimumHoldMs: 500, releaseMs: 260, motionProfile: "thoughtful" },
  surprised: { weight: 0.8, attackMs: 90, minimumHoldMs: 450, releaseMs: 300, motionProfile: "alert" },
  embarrassed: { weight: 0.65, attackMs: 200, minimumHoldMs: 500, releaseMs: 280, motionProfile: "shy" },
  concerned: { weight: 0.7, attackMs: 180, minimumHoldMs: 550, releaseMs: 300, motionProfile: "attentive" },
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
  private nextDueAt = 0;
  private previousId: string | null = null;
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

  start(nowSeconds: number): void {
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
    if (context.gesturePlaying || this.random() > this.profile.alternativeProbability) return null;

    const eligible = candidates.filter((candidate) => {
      if (context.speaking && candidate.category === "long") return false;
      if (candidate.id === this.previousId && candidates.length > 1) return false;
      const lastPlayed = this.lastPlayedAt.get(candidate.id);
      return lastPlayed === undefined || nowSeconds - lastPlayed >= candidate.cooldownSeconds;
    });
    if (eligible.length === 0) return null;

    const selected = eligible[Math.min(eligible.length - 1, Math.floor(this.random() * eligible.length))];
    this.previousId = selected.id;
    this.lastPlayedAt.set(selected.id, nowSeconds);
    return selected;
  }

  private randomInterval(): number {
    return this.profile.intervalMinSeconds
      + (this.profile.intervalMaxSeconds - this.profile.intervalMinSeconds) * clamp(this.random(), 0, 1);
  }
}
