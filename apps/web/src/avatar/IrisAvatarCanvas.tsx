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
import { AvatarAudioQueue } from "./AvatarAudioQueue";
import { AvatarProtocolClient, type AvatarEnvelope } from "./AvatarProtocolClient";

const IDLE_FILES = ["X Bot@Idle.fbx", "X Bot@Idle 1.fbx", "X Bot@Look Around.fbx"];
const GESTURE_FILES: Record<string, string> = {
  talk: "X Bot@Talking.fbx",
  greeting: "X Bot@Waving.fbx",
  agreement: "X Bot@Agreeing.fbx",
  disagreement: "X Bot@Shaking Head No.fbx",
  question: "X Bot@TalkingQuestion.fbx",
  explanation: "X Bot@Talking.fbx",
  thinking: "X Bot@Thinking.fbx",
  surprise: "X Bot@Surprised.fbx",
  frustration: "X Bot@Angry.fbx",
  farewell: "X Bot@WavingGoodbye.fbx",
  shrug: "X Bot@Shrugging.fbx",
};

const MIXAMO_BONE_NAMES: Record<string, string> = {
  J_Bip_C_Hips: "mixamorigHips", J_Bip_C_Spine: "mixamorigSpine", J_Bip_C_Chest: "mixamorigSpine1", J_Bip_C_UpperChest: "mixamorigSpine2", J_Bip_C_Neck: "mixamorigNeck", J_Bip_C_Head: "mixamorigHead",
  J_Bip_L_Shoulder: "mixamorigLeftShoulder", J_Bip_L_UpperArm: "mixamorigLeftArm", J_Bip_L_LowerArm: "mixamorigLeftForeArm", J_Bip_L_Hand: "mixamorigLeftHand",
  J_Bip_R_Shoulder: "mixamorigRightShoulder", J_Bip_R_UpperArm: "mixamorigRightArm", J_Bip_R_LowerArm: "mixamorigRightForeArm", J_Bip_R_Hand: "mixamorigRightHand",
  J_Bip_L_UpperLeg: "mixamorigLeftUpLeg", J_Bip_L_LowerLeg: "mixamorigLeftLeg", J_Bip_L_Foot: "mixamorigLeftFoot", J_Bip_L_ToeBase: "mixamorigLeftToeBase",
  J_Bip_R_UpperLeg: "mixamorigRightUpLeg", J_Bip_R_LowerLeg: "mixamorigRightLeg", J_Bip_R_Foot: "mixamorigRightFoot", J_Bip_R_ToeBase: "mixamorigRightToeBase",
};

// Mixamo FBX files store root translations in centimetres, while the VRM
// scene uses metres. Without this conversion the idle clip lifts the hips to
// roughly Y=100 and the avatar leaves the camera after the first frame.
const MIXAMO_TRANSLATION_SCALE = 0.01;
const RAW_ARM_REST_CORRECTIONS: Record<string, number> = {
  J_Bip_L_UpperArm: Math.PI * 0.43,
  J_Bip_R_UpperArm: -Math.PI * 0.43,
  J_Bip_L_LowerArm: -Math.PI * 0.12,
  J_Bip_R_LowerArm: Math.PI * 0.12,
};
const ARM_RETARGET_DAMPING: Record<string, number> = {
  J_Bip_L_Shoulder: 0.35, J_Bip_R_Shoulder: 0.35,
  J_Bip_L_UpperArm: 0.45, J_Bip_R_UpperArm: 0.45,
  J_Bip_L_LowerArm: 0.82, J_Bip_R_LowerArm: 0.82,
  J_Bip_L_Hand: 0.72, J_Bip_R_Hand: 0.72,
};
const IDENTITY_QUATERNION = new THREE.Quaternion();

type ExpressionName = string;

function assetUrl(file: string): string {
  // Vite resolves static files with a literal `@` in the filename. Encode
  // spaces and other unsafe characters, but do not turn `@` into `%40` or it
  // falls through to index.html instead of returning the FBX binary.
  return `/avatar/animations/${encodeURI(file)}`;
}

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
  private readonly loader = new FBXLoader();
  private readonly clips = new Map<string, THREE.AnimationClip>();
  private readonly mixer: THREE.AnimationMixer;
  private readonly retargetTarget: THREE.SkinnedMesh | null;
  private readonly normalizedNameByRawName = new Map<string, string>();
  private active: THREE.AnimationAction | null = null;
  private idleAction: THREE.AnimationAction | null = null;
  private fallbackGesture = "";
  private fallbackUntil = 0;
  private disposed = false;

  constructor(private readonly vrm: VRM) {
    // The normalized VRM rig is a technical retargeting rig and its rest pose
    // is not Iris's authored pose. Keep the visible raw bones in control and
    // let VRM continue updating expressions and spring bones around them.
    if (vrm.humanoid) vrm.humanoid.autoUpdateHumanBones = false;
    this.mixer = new THREE.AnimationMixer(vrm.scene);
    this.retargetTarget = this.createRetargetTarget();
    this.applyAuthoredRestPose();
  }

  async startIdle(): Promise<void> {
    const file = IDLE_FILES[0];
    const clip = await this.load(file);
    if (!clip || this.disposed) return;
    this.idleAction = this.mixer.clipAction(clip).reset().setLoop(THREE.LoopRepeat, Infinity);
    // A gesture can arrive while the idle FBX is still loading. Installing
    // the idle action is always safe, but it must not interrupt that gesture.
    if (!this.active) this.playIdle();
  }

  async trigger(gesture: string, intensity: number): Promise<number> {
    if (this.disposed) return 0;
    const normalized = gesture.toLowerCase();
    const file = GESTURE_FILES[normalized] ?? GESTURE_FILES.talk;
    const clip = await this.load(file);
    if (!clip) {
      this.fallbackGesture = normalized;
      this.fallbackUntil = performance.now() + 1_400 * Math.max(0.45, intensity);
      return 1_400 * Math.max(0.45, intensity);
    }
    this.fallbackGesture = "";
    this.fallbackUntil = 0;
    const action = this.mixer.clipAction(clip).reset().setLoop(THREE.LoopOnce, 1);
    action.clampWhenFinished = true;
    this.crossFadeTo(action, Math.min(1, Math.max(0.3, intensity)), 0.12);
    return clip.duration * 1_000;
  }

  update(delta: number): void {
    this.mixer.update(delta);
    if (this.active && this.active !== this.idleAction && !this.active.isRunning()) this.playIdle();
    const head = this.vrm.humanoid?.getRawBoneNode(VRMHumanBoneName.Head);
    if (!head || performance.now() >= this.fallbackUntil) return;
    const phase = performance.now() / 150;
    if (this.fallbackGesture === "agreement") head.rotation.x += Math.sin(phase) * 0.012;
    if (this.fallbackGesture === "disagreement") head.rotation.y += Math.sin(phase) * 0.015;
    if (this.fallbackGesture === "thinking") head.rotation.z += 0.0015;
  }

  dispose(): void {
    this.disposed = true;
    this.mixer.stopAllAction();
    this.mixer.uncacheRoot(this.vrm.scene);
    this.retargetTarget?.geometry.dispose();
    if (Array.isArray(this.retargetTarget?.material)) this.retargetTarget.material.forEach((material) => material.dispose());
    else this.retargetTarget?.material.dispose();
    this.active = null;
    this.idleAction = null;
  }

  private playIdle(): void {
    if (!this.idleAction || this.disposed) return;
    if (this.active === this.idleAction && this.idleAction.isRunning()) return;
    this.crossFadeTo(this.idleAction, 1, 0.18);
  }

  private crossFadeTo(action: THREE.AnimationAction, weight: number, duration: number): void {
    if (this.active && this.active !== action) this.active.fadeOut(duration);
    action
      .reset()
      .setLoop(action === this.idleAction ? THREE.LoopRepeat : THREE.LoopOnce, action === this.idleAction ? Infinity : 1)
      .setEffectiveTimeScale(1)
      .setEffectiveWeight(weight)
      .fadeIn(duration)
      .play();
    this.active = action;
  }

  private async load(file: string): Promise<THREE.AnimationClip | null> {
    const cached = this.clips.get(file);
    if (cached) return cached;
    try {
      const source = await this.loader.loadAsync(assetUrl(file));
      const sourceClip = source.animations[0];
      if (!sourceClip) return null;
      const sourceBones: THREE.Bone[] = [];
      source.traverse((node) => { if ((node as THREE.Bone).isBone) sourceBones.push(node as THREE.Bone); });
      if (sourceBones.length === 0 || !this.retargetTarget) return null;
      // Retarget local motion relative to each Mixamo bone's rest pose. The
      // FBX armature stores its limbs with a different axis basis than the
      // normalized VRM rig (e.g. the Mixamo leg has a 180° rest rotation).
      // Copying absolute FBX quaternions makes arms turn backwards and flips
      // the lower body. Applying only rest-relative deltas keeps the VRM
      // proportions and lets the full humanoid chain move naturally.
      const clip = this.createRetargetedClip(source, sourceBones, sourceClip);
      this.clips.set(file, clip);
      return clip;
    } catch {
      return null;
    }
  }

  private createRetargetedClip(
    source: THREE.Object3D,
    sourceBones: THREE.Bone[],
    sourceClip: THREE.AnimationClip,
  ): THREE.AnimationClip {
    const sourceByName = new Map(sourceBones.map((bone) => [bone.name, bone]));
    const targetByRawName = new Map(this.retargetTarget!.skeleton.bones.map((bone) => [bone.name, bone]));
    const targetRest = new Map(this.retargetTarget!.skeleton.bones.map((bone) => [bone.name, {
      position: bone.position.clone(),
      quaternion: bone.quaternion.clone(),
    }]));

    const sourceFps = Math.max(...sourceClip.tracks.map((track) => track.times.length)) / sourceClip.duration;
    const fps = Math.min(60, Math.max(24, Math.ceil(sourceFps || 30)));
    const frameCount = Math.max(2, Math.ceil(sourceClip.duration * fps) + 1);
    const times = new Float32Array(frameCount);
    const quaternionValues = new Map<string, Float32Array>();
    const hipPositionValues = new Float32Array(frameCount * 3);

    for (const [rawName] of Object.entries(MIXAMO_BONE_NAMES)) {
      if (targetByRawName.has(rawName)) quaternionValues.set(rawName, new Float32Array(frameCount * 4));
    }

    const sourceMixer = new THREE.AnimationMixer(source);
    sourceMixer.clipAction(sourceClip).play();
    // These FBX files are animation-only exports. Their embedded bind pose
    // is not the pose the clip starts from, so use frame zero as the motion
    // baseline. This prevents a visible T-pose jump when idle begins.
    sourceMixer.setTime(0);
    source.updateMatrixWorld(true);
    const sourceRest = new Map(sourceBones.map((bone) => [bone.name, {
      position: bone.position.clone(),
      quaternion: bone.quaternion.clone(),
    }]));
    const sourceDelta = new THREE.Quaternion();
    const targetQuaternion = new THREE.Quaternion();
    const frameTime = sourceClip.duration / (frameCount - 1);

    for (let frame = 0; frame < frameCount; frame += 1) {
      const time = Math.min(sourceClip.duration, frame * frameTime);
      times[frame] = time;
      sourceMixer.setTime(time);
      source.updateMatrixWorld(true);

      for (const [rawName, sourceName] of Object.entries(MIXAMO_BONE_NAMES)) {
        const sourceBone = sourceByName.get(sourceName);
        const targetBone = targetByRawName.get(rawName);
        const sourceRestBone = sourceRest.get(sourceName);
        const targetRestBone = targetRest.get(rawName);
        const values = quaternionValues.get(rawName);
        if (!sourceBone || !targetBone || !sourceRestBone || !targetRestBone || !values) continue;

        sourceDelta.copy(sourceRestBone.quaternion).invert().multiply(sourceBone.quaternion).normalize();
        const armDamping = ARM_RETARGET_DAMPING[rawName];
        if (armDamping !== undefined) sourceDelta.slerp(IDENTITY_QUATERNION, 1 - armDamping);
        targetQuaternion.copy(targetRestBone.quaternion).multiply(sourceDelta).normalize();
        targetQuaternion.toArray(values, frame * 4);

        if (rawName === "J_Bip_C_Hips") {
          const positionOffset = sourceBone.position.clone().sub(sourceRestBone.position).multiplyScalar(MIXAMO_TRANSLATION_SCALE);
          hipPositionValues[frame * 3] = targetRestBone.position.x + positionOffset.x;
          hipPositionValues[frame * 3 + 1] = targetRestBone.position.y + positionOffset.y;
          hipPositionValues[frame * 3 + 2] = targetRestBone.position.z + positionOffset.z;
        }
      }
    }

    sourceMixer.stopAllAction();
    sourceMixer.uncacheAction(sourceClip);
    sourceMixer.uncacheRoot(source);

    const tracks: THREE.KeyframeTrack[] = [];
    for (const [rawName, values] of quaternionValues) {
      const animationName = this.normalizedNameByRawName.get(rawName);
      if (!animationName) continue;
      tracks.push(new THREE.QuaternionKeyframeTrack(`${animationName}.quaternion`, times, values));
    }
    const hipsName = this.normalizedNameByRawName.get("J_Bip_C_Hips");
    if (hipsName) tracks.push(new THREE.VectorKeyframeTrack(`${hipsName}.position`, times, hipPositionValues));
    return new THREE.AnimationClip(sourceClip.name, sourceClip.duration, tracks);
  }

  private applyAuthoredRestPose(): void {
    for (const [rawName, angle] of Object.entries(RAW_ARM_REST_CORRECTIONS)) {
      const bone = this.vrm.scene.getObjectByName(rawName) as THREE.Bone | undefined;
      if (!bone?.isBone) continue;
      bone.quaternion.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), angle));
    }
  }

  private createRetargetTarget(): THREE.SkinnedMesh | null {
    const humanoid = this.vrm.humanoid;
    if (!humanoid) return null;

    const targetBones: THREE.Bone[] = [];
    for (const humanBoneName of Object.values(VRMHumanBoneName) as VRMHumanBoneName[]) {
      const rawNode = humanoid.getRawBoneNode(humanBoneName);
      const normalizedNode = humanoid.getNormalizedBoneNode(humanBoneName);
      if (!rawNode || !normalizedNode || !MIXAMO_BONE_NAMES[rawNode.name]) continue;
      // Tracks are bound to the visible raw VRM nodes. The normalized node is
      // only queried here to ensure the human bone is available.
      this.normalizedNameByRawName.set(rawNode.name, rawNode.name);
    }
    if (this.normalizedNameByRawName.size === 0) return null;

    const rawRoot = humanoid.getRawBoneNode(VRMHumanBoneName.Hips);
    if (!rawRoot) return null;
    const cloneNode = (source: THREE.Object3D): THREE.Bone => {
      const clone = new THREE.Bone();
      clone.name = source.name;
      clone.position.copy(source.position);
      clone.quaternion.copy(source.quaternion);
      const correction = RAW_ARM_REST_CORRECTIONS[clone.name];
      if (correction) clone.quaternion.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), correction));
      clone.scale.copy(source.scale);
      if (this.normalizedNameByRawName.has(clone.name)) targetBones.push(clone);
      source.children.forEach((child) => clone.add(cloneNode(child)));
      return clone;
    };

    const cloneRoot = cloneNode(rawRoot);
    const target = new THREE.SkinnedMesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial());
    target.add(cloneRoot);
    target.updateMatrixWorld(true);
    target.bind(new THREE.Skeleton(targetBones));
    return target;
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
    let currentEmotion: ExpressionName = VRMExpressionPresetName.Neutral;
    let currentEmotionIntensity = 0;
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
    const applyEmotion = (value: string, intensity = 1) => {
      const nextEmotion = emotionPreset(value);
      const nextIntensity = Math.min(1, Math.max(0, intensity));
      const previousEmotion = currentEmotion;
      currentEmotion = nextEmotion;
      currentEmotionIntensity = nextIntensity;
      const expressions = vrm?.expressionManager;
      if (!expressions) return;
      expressions.setValue(previousEmotion, 0);
      expressions.setValue(nextEmotion, nextIntensity);
    };
    const playGesture = async (client: AvatarProtocolClient, gesture: string, intensity: number, replyTo: string) => {
      if (!motion || gesture === "none" || gesture === "auto") return;
      client.send("avatar.gesture.started", { gesture, intensity }, replyTo);
      const duration = await motion.trigger(gesture, intensity);
      if (gestureTimer !== null) window.clearTimeout(gestureTimer);
      gestureTimer = window.setTimeout(() => client.send("avatar.gesture.finished", { gesture, intensity }, replyTo), duration);
    };
    const protocol = new AvatarProtocolClient({
      url: avatarWebSocketUrl(),
      onConnectionChange: (connected) => { if (connected) sendState(protocol, "Idle"); },
      onMessage: (message) => { void handleMessage(message); },
    });
    const playbackHandlers = (utteranceId: string, replyTo: string) => ({
      onStarted: () => {
        currentUtterance = utteranceId;
        sendState(protocol, "Speaking");
        protocol.send("avatar.playback.started", { utterance_id: utteranceId, client_latency_ms: 0 }, replyTo);
      },
      onFinished: () => {
        clearMouth();
        if (currentUtterance === utteranceId) currentUtterance = null;
        sendState(protocol, "Idle");
        protocol.send("avatar.playback.finished", { utterance_id: utteranceId, client_latency_ms: 0 }, replyTo);
      },
      onFailed: (reason: string) => {
        clearMouth();
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
            clearMouth();
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
      // Keep the complete rig inside the frame. The feet are part of the
      // motion proof: cropping them makes a working leg animation look frozen.
      const top = bounds.max.y + size.y * 0.06;
      const bottom = bounds.min.y - size.y * 0.04;
      const portraitHeight = Math.max(0.1, top - bottom);
      const portraitWidth = Math.max(0.1, size.x * 1.24);
      const verticalDistance = portraitHeight / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)));
      const horizontalDistance = portraitWidth / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * camera.aspect);
      const center = bounds.getCenter(new THREE.Vector3());
      const portraitZoom = 1.1;
      camera.position.set(center.x, (top + bottom) / 2, (Math.max(verticalDistance, horizontalDistance) + 0.15) / portraitZoom + center.z);
      camera.lookAt(center.x, (top + bottom) / 2, center.z);
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
      // The motion mixer drives the authored raw VRM bones; VRM.update keeps
      // expressions and spring bones alive without overwriting that pose.
      motion?.update(delta);
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
        applyEmotion(currentEmotion, currentEmotionIntensity);
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
