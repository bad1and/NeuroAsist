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
  EmotionBlendController,
  IdleMotionScheduler,
  parseEmotion,
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
  { id: "idle-neutral", category: "micro", durationSeconds: 8, cooldownSeconds: 10 },
  { id: "idle-weight-shift", category: "normal", durationSeconds: 7, cooldownSeconds: 18 },
  { id: "idle-look-around", category: "normal", durationSeconds: 6, cooldownSeconds: 22 },
];

const EMOTION_EXPRESSION_KEYS = [
  VRMExpressionPresetName.Neutral,
  VRMExpressionPresetName.Happy,
  VRMExpressionPresetName.Sad,
  VRMExpressionPresetName.Angry,
  VRMExpressionPresetName.Relaxed,
  "Surprised",
];

const MOTION_PROFILES: Record<string, { intervalMinSeconds: number; intervalMaxSeconds: number; probability: number }> = {
  idle: { intervalMinSeconds: 7, intervalMaxSeconds: 15, probability: 0.85 },
  energetic: { intervalMinSeconds: 5.5, intervalMaxSeconds: 12, probability: 0.95 },
  calm: { intervalMinSeconds: 9, intervalMaxSeconds: 18, probability: 0.7 },
  tense: { intervalMinSeconds: 6, intervalMaxSeconds: 13, probability: 0.85 },
  playful: { intervalMinSeconds: 6, intervalMaxSeconds: 13, probability: 0.9 },
  thoughtful: { intervalMinSeconds: 8, intervalMaxSeconds: 17, probability: 0.72 },
  alert: { intervalMinSeconds: 5, intervalMaxSeconds: 11, probability: 0.9 },
  shy: { intervalMinSeconds: 8, intervalMaxSeconds: 17, probability: 0.68 },
  attentive: { intervalMinSeconds: 7, intervalMaxSeconds: 15, probability: 0.8 },
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
  loop: boolean;
  aliasOf?: string;
};

const CLIP_SOURCES: Record<string, ClipSource> = {
  thinking: { file: "X Bot@Thinking.fbx", loop: false },
  angry: { file: "X Bot@Angry.fbx", loop: false },
  frustration: { file: "X Bot@Angry.fbx", loop: false, aliasOf: "angry" },
  surprise: { file: "X Bot@Surprised.fbx", loop: false },
  greeting: { file: "X Bot@Waving.fbx", loop: false },
  farewell: { file: "X Bot@WavingGoodbye.fbx", loop: false },
  shrug: { file: "X Bot@Shrugging.fbx", loop: false },
  agreement: { file: "X Bot@Agreeing.fbx", loop: false },
  disagreement: { file: "X Bot@Shaking Head No.fbx", loop: false },
  talk: { file: "X Bot@Talking.fbx", loop: true },
  talkingquestion: { file: "X Bot@TalkingQuestion.fbx", loop: true },
  question: { file: "X Bot@TalkingQuestion.fbx", loop: true, aliasOf: "talkingquestion" },
  explanation: { file: "X Bot@Talking.fbx", loop: true, aliasOf: "talk" },
};

const PROCEDURAL_IDLE_CLIPS: Record<string, { kind: ProceduralIdleKind; duration: number }> = {
  "idle-neutral": { kind: "neutral", duration: 8 },
  "idle-weight-shift": { kind: "weight-shift", duration: 7 },
  "idle-look-around": { kind: "look-around", duration: 6 },
};

function payloadString(payload: Record<string, unknown>, key: string, fallback = ""): string {
  return typeof payload[key] === "string" ? payload[key] : fallback;
}

function payloadNumber(payload: Record<string, unknown>, key: string, fallback = 1): number {
  return typeof payload[key] === "number" ? payload[key] : fallback;
}

function payloadBoolean(payload: Record<string, unknown>, key: string, fallback = false): boolean {
  return typeof payload[key] === "boolean" ? payload[key] : fallback;
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

class AvatarMotionPlayer {
  private readonly idleScheduler = new IdleMotionScheduler();
  private readonly clips = new Map<string, MotionClip>();
  private readonly normalizedByHuman = new Map<VRMHumanBoneName, THREE.Object3D>();
  private readonly normalizedRestPositions = new Map<VRMHumanBoneName, THREE.Vector3>();
  private readonly targetBindRotations = createIrisTargetBindRotations();
  private readonly transitionFrom = new Map<VRMHumanBoneName, { position: THREE.Vector3; quaternion: THREE.Quaternion }>();
  private clipsReady: Promise<void> | null = null;
  private motionProfile = "idle";
  private elapsedSeconds = 0;
  private gazeTime = 0;
  private speaking = false;
  private gestureGeneration = 0;
  private fallbackGesture = "";
  private fallbackUntil = 0;
  private currentIdleId = "idle-neutral";
  private currentIdleTime = 0;
  private activeClip: MotionClip | null = null;
  private transitionElapsed = 1;
  private transitionDuration = 0.4;
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
    this.idleScheduler.start(this.elapsedSeconds);
    if (!this.fallbackGesture && !this.speaking) this.switchTo("idle-neutral", 0.45);
  }

  setSpeaking(value: boolean): void {
    if (this.speaking === value) return;
    this.speaking = value;
    if (value && !this.fallbackGesture) {
      if (this.clips.has("talk")) this.switchTo("talk", 0.25);
      else {
        void this.ensureClipsLoaded().then(() => {
          if (!this.disposed && this.speaking && !this.fallbackGesture) this.switchTo("talk", 0.25);
        });
      }
    }
    if (!value && !this.fallbackGesture) this.returnToCurrentIdle(0.3);
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

  async trigger(gesture: string, intensity: number): Promise<{ durationMs: number; generation: number }> {
    const generation = ++this.gestureGeneration;
    if (this.disposed) return { durationMs: 0, generation };
    await this.ensureClipsLoaded();
    // A gesture may have been superseded while its FBX files were loading.
    // Never let that stale async continuation overwrite the newer pose.
    if (this.disposed || generation !== this.gestureGeneration) return { durationMs: 0, generation };
    const normalized = gesture.toLowerCase();
    const clipId = CLIP_SOURCES[normalized] ? normalized : "talk";
    const clip = this.clips.get(clipId);
    if (!clip) return { durationMs: 0, generation };
    this.captureCurrentIdle();
    this.fallbackGesture = normalized;
    const durationMs = clip.duration * 1_000 * Math.max(0.65, intensity);
    this.fallbackUntil = performance.now() + durationMs;
    this.switchTo(clipId, 0.2);
    return { durationMs, generation };
  }

  isGestureGenerationCurrent(generation: number): boolean {
    return !this.disposed && generation === this.gestureGeneration;
  }

  stop(): void {
    this.gestureGeneration += 1;
    this.fallbackGesture = "";
    this.fallbackUntil = 0;
    this.speaking = false;
    this.returnToCurrentIdle(0.32);
  }

  update(delta: number): void {
    const safeDelta = Math.max(0, delta);
    this.elapsedSeconds += safeDelta;
    if (this.fallbackGesture && performance.now() >= this.fallbackUntil) {
      this.fallbackGesture = "";
      this.fallbackUntil = 0;
      if (this.speaking) this.switchTo("talk", 0.3);
      else this.returnToCurrentIdle(0.3);
    }

    if (this.activeClip) {
      this.activeClip.mixer?.update(safeDelta);
      const duration = Math.max(0.001, this.activeClip.duration);
      this.activeClip.time = this.activeClip.loop
        ? (this.activeClip.time + safeDelta) % duration
        : Math.min(duration, this.activeClip.time + safeDelta);
      this.transitionElapsed += safeDelta;
      this.applySample(this.activeClip.sample(this.activeClip.time));
      if (!this.fallbackGesture && !this.speaking && this.activeClip.id === this.currentIdleId) {
        this.currentIdleTime = this.activeClip.time;
      }
    }

    if (!this.fallbackGesture && !this.speaking) {
      const candidate = this.idleScheduler.schedule(this.elapsedSeconds, IDLE_DEFINITIONS, { speaking: false, gesturePlaying: false });
      if (candidate) {
        this.currentIdleId = candidate.id;
        this.currentIdleTime = 0;
        this.switchTo(candidate.id, 0.42);
      }
    }
  }

  // Gaze is applied to the same normalized rig after the clip has been
  // sampled, then VRM copies it to Iris's authored raw bones in vrm.update().
  applyPreVrmPose(delta: number): void {
    this.gazeTime += Math.max(0, delta);
    const head = this.normalizedByHuman.get(VRMHumanBoneName.Head);
    if (!head) return;
    const intensity = this.fallbackGesture ? 0.35 : 1;
    head.rotation.x += Math.sin(this.gazeTime * 0.57) * 0.004 * intensity;
    head.rotation.y += Math.sin(this.gazeTime * 0.31 + 1.7) * 0.009 * intensity;
    head.rotation.z += Math.sin(this.gazeTime * 0.23 + 0.6) * 0.002 * intensity;
  }

  private ensureClipsLoaded(): Promise<void> {
    this.clipsReady ??= this.loadClips();
    return this.clipsReady;
  }

  private async loadClips(): Promise<void> {
    const sources = Object.entries(CLIP_SOURCES).map(([id, source]) => ({ id, source }));
    const loaded = await Promise.all(sources.map(async ({ id, source }) => {
      if (source.aliasOf) return null;
      try {
        const root = await new FBXLoader().loadAsync(`/avatar/animations/${source.file}`);
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
          sample: () => retargetMixamoPose(
            bones,
            reference,
            this.targetBindRotations,
            this.normalizedRestPositions,
          ),
        } satisfies MotionClip;
      } catch {
        return null;
      }
    }));
    for (const clip of loaded) {
      if (!clip) continue;
      this.clips.set(clip.id, clip);
    }
    for (const [id, source] of Object.entries(CLIP_SOURCES)) {
      if (!source.aliasOf) continue;
      const clip = this.clips.get(source.aliasOf);
      if (clip) this.clips.set(id, clip);
    }
  }

  private switchTo(id: string, duration: number, initialTime = 0): void {
    const next = this.clips.get(id);
    if (!next || this.activeClip === next && Math.abs(initialTime - next.time) < 0.01) return;
    this.transitionFrom.clear();
    for (const [human, node] of this.normalizedByHuman) {
      this.transitionFrom.set(human, {
        position: node.position.clone(),
        quaternion: node.quaternion.clone(),
      });
    }
    const startTime = Math.max(0, initialTime) % Math.max(0.001, next.duration);
    next.action?.reset().play();
    next.mixer?.setTime(startTime);
    next.time = startTime;
    this.activeClip = next;
    this.transitionElapsed = 0;
    this.transitionDuration = Math.max(0.05, duration);
  }

  private captureCurrentIdle(): void {
    if (this.activeClip && this.activeClip.id === this.currentIdleId && !this.fallbackGesture && !this.speaking) {
      this.currentIdleTime = this.activeClip.time;
    }
  }

  private returnToCurrentIdle(duration: number): void {
    const id = this.clips.has(this.currentIdleId) ? this.currentIdleId : "idle-neutral";
    this.switchTo(id, duration, this.currentIdleTime);
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
        ),
      });
    }
  }

  private applySample(pose: NormalizedPose): void {
    const rawBlend = Math.min(1, this.transitionElapsed / this.transitionDuration);
    const blend = rawBlend * rawBlend * (3 - 2 * rawBlend);
    const quaternion = new THREE.Quaternion();
    for (const [human, node] of this.normalizedByHuman) {
      const target = pose.rotations.get(human);
      if (!target) continue;
      const from = this.transitionFrom.get(human);
      if (from) {
        quaternion.copy(from.quaternion).slerp(target, blend).normalize();
        node.quaternion.copy(quaternion);
        if (human === VRMHumanBoneName.Hips) node.position.lerpVectors(from.position, pose.hipsPosition, blend);
      } else {
        node.quaternion.copy(target);
        if (human === VRMHumanBoneName.Hips) node.position.copy(pose.hipsPosition);
      }
    }
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
    let currentUtterance: string | null = null;
    let gestureTimer: number | null = null;
    const audio = new AvatarAudioQueue();
    const timer = new THREE.Timer();
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, 1, 0.01, 100);
    let lastDpr = Math.min(window.devicePixelRatio || 1, 2);
    let slowFrames = 0;
    let fastFrames = 0;

    const sendState = (client: AvatarProtocolClient, state: string) => client.send("avatar.state.changed", { state });
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
      if (!motion || gesture === "none" || gesture === "auto") return;
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
      onConnectionChange: (connected) => { if (connected) sendState(protocol, "Idle"); },
      onMessage: (message) => { void handleMessage(message); },
    });
    const playbackHandlers = (utteranceId: string, replyTo: string) => ({
      onStarted: () => {
        currentUtterance = utteranceId;
        motion?.setSpeaking(true);
        sendState(protocol, "Speaking");
        protocol.send("avatar.playback.started", { utterance_id: utteranceId, client_latency_ms: 0 }, replyTo);
      },
      onFinished: () => {
        clearMouth();
        motion?.setSpeaking(false);
        motion?.stop();
        releaseEmotion();
        if (currentUtterance === utteranceId) currentUtterance = null;
        sendState(protocol, "Idle");
        protocol.send("avatar.playback.finished", { utterance_id: utteranceId, client_latency_ms: 0 }, replyTo);
      },
      onFailed: (reason: string) => {
        clearMouth();
        motion?.setSpeaking(false);
        motion?.stop();
        releaseEmotion();
        if (currentUtterance === utteranceId) currentUtterance = null;
        sendState(protocol, "Error");
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
            applyEmotion(payloadString(payload, "emotion"), payloadNumber(payload, "gesture_intensity"));
            void playGesture(protocol, payloadString(payload, "gesture", "talk"), payloadNumber(payload, "gesture_intensity"), message.message_id);
            await audio.playUrl(resolveApiUrl(payloadString(payload, "audio_url")), playbackHandlers(utterance, message.message_id));
            break;
          }
          case "avatar.stream.start": {
            const utterance = payloadString(payload, "utterance_id");
            if (payloadBoolean(payload, "interrupt", true)) audio.stop();
            motion?.setSpeaking(true);
            audio.beginStream(playbackHandlers(utterance, message.message_id));
            break;
          }
          case "avatar.stream.metadata":
            applyEmotion(payloadString(payload, "emotion"), payloadNumber(payload, "gesture_intensity"));
            void playGesture(protocol, payloadString(payload, "gesture", "talk"), payloadNumber(payload, "gesture_intensity"), message.message_id);
            break;
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
            motion?.setSpeaking(false);
            motion?.stop();
            clearMouth();
            releaseEmotion();
            sendState(protocol, "Idle");
            break;
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
      if (disposed || !renderer) return;
      frame = window.requestAnimationFrame(animate);
      timer.update();
      const delta = Math.min(timer.getDelta(), 0.1);
      if (delta > 1 / 45) { slowFrames += 1; fastFrames = 0; }
      else { fastFrames += 1; slowFrames = 0; }
      if (slowFrames > 135 && lastDpr > 1) { lastDpr = 1; resize(); slowFrames = 0; }
      if (fastFrames > 600 && lastDpr < Math.min(window.devicePixelRatio || 1, 2)) { lastDpr = Math.min(window.devicePixelRatio || 1, 2); resize(); fastFrames = 0; }
      const volume = audio.volume();
      if (vrm?.expressionManager) {
        clearMouth();
        const emotionSnapshot = emotionController.update(delta, performance.now());
        applyEmotionExpressions(emotionSnapshot.weights);
        const blinkPhase = (performance.now() % 4_200) / 4_200;
        const blink = blinkPhase > 0.91 && blinkPhase < 0.95
          ? 1 - Math.abs(blinkPhase - 0.93) / 0.02
          : 0;
        vrm.expressionManager.setValue(VRMExpressionPresetName.Blink, Math.max(0, blink));
        if (volume > 0.018) {
          const vowels = [VRMExpressionPresetName.Aa, VRMExpressionPresetName.Ih, VRMExpressionPresetName.Ou, VRMExpressionPresetName.Ee, VRMExpressionPresetName.Oh];
          const vowel = vowels[Math.floor(performance.now() / 110) % vowels.length];
          vrm.expressionManager.setValue(vowel, Math.min(1, volume * 1.5));
        }
      }
      motion?.update(delta);
      motion?.applyPreVrmPose(delta);
      vrm?.update(delta);
      renderer.render(scene, camera);
    };

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
        vrm.update(0);
        applyEmotionExpressions(emotionController.snapshot().weights);
        void motion.startIdle().then(() => { if (!disposed) fitPortrait(); });
        fitPortrait();
        setStatus("ready");
      }).catch(() => { if (!disposed) setStatus("failed"); });
      protocol.start();
      animate();
    } catch {
      setStatus("failed");
    }

    return () => {
      disposed = true;
      if (frame) window.cancelAnimationFrame(frame);
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
