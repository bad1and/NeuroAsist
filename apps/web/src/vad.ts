export type VadState = "idle" | "listening" | "speech_candidate" | "speech" | "end_pending";
export type VadEvent = "speech_started" | "speech_ended" | null;
export type MicrophoneProfile = "headset" | "balanced" | "speakers";
export type CaptureProfile = MicrophoneProfile | "live";

export type CaptureMetadata = {
  sampleRate: number;
  channels: number;
  profile: CaptureProfile;
  settings: MediaTrackSettings;
  constraints: MediaTrackConstraints;
  supportedConstraints: MediaTrackSupportedConstraints;
};

// Temporary default until the key becomes a runtime setting.
export const LIVE_MUTE_HOTKEY = "m";

export function microphoneConstraints(profile: CaptureProfile, inputDeviceId = ""): MediaTrackConstraints {
  const processing = {
    live: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    headset: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    balanced: { echoCancellation: true, noiseSuppression: false, autoGainControl: false },
    speakers: { echoCancellation: true, noiseSuppression: true, autoGainControl: false },
  }[profile];
  return {
    channelCount: { ideal: 1 },
    ...processing,
    ...(inputDeviceId ? { deviceId: { exact: inputDeviceId } } : {}),
  };
}

/** Deterministic debounce layer used by the AudioWorklet RMS monitor. */
export class VoiceActivityGate {
  private state: VadState = "idle";
  private since = 0;

  constructor(
    private readonly threshold = 0.012,
    private readonly candidateMs = 160,
    private readonly silenceMs = 700,
  ) {}

  start(now = 0): void { this.state = "listening"; this.since = now; }
  stop(): void { this.state = "idle"; this.since = 0; }
  snapshot(): VadState { return this.state; }

  feed(rms: number, now: number): VadEvent {
    if (this.state === "idle") return null;
    const speech = rms >= this.threshold;
    if (this.state === "listening" && speech) {
      this.state = "speech_candidate";
      this.since = now;
    } else if (this.state === "speech_candidate") {
      if (!speech) { this.state = "listening"; }
      else if (now - this.since >= this.candidateMs) { this.state = "speech"; return "speech_started"; }
    } else if (this.state === "speech" && !speech) {
      this.state = "end_pending";
      this.since = now;
    } else if (this.state === "end_pending") {
      if (speech) { this.state = "speech"; }
      else if (now - this.since >= this.silenceMs) { this.state = "listening"; return "speech_ended"; }
    }
    return null;
  }
}

const WORKLET_SOURCE = `
class NeuroVadProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.pending = [];
    this.frameSamples = Math.max(1, Math.round(sampleRate * 0.020));
    this.gain = 1;
  }
  process(inputs) {
    const channels = inputs[0];
    if (!channels?.length || !channels[0]?.length) return true;
    for (let i = 0; i < channels[0].length; i++) {
      let mono = 0;
      for (let channel = 0; channel < channels.length; channel++) mono += channels[channel][i] || 0;
      this.pending.push(mono / channels.length);
    }
    while (this.pending.length >= this.frameSamples) {
      const samples = this.pending.splice(0, this.frameSamples);
      const pcm = new Int16Array(samples.length);
      let inputSum = 0;
      for (let i = 0; i < samples.length; i++) inputSum += samples[i] * samples[i];
      const inputRms = Math.sqrt(inputSum / samples.length);
      if (inputRms > 0.0025) {
        const targetGain = Math.max(0.65, Math.min(2.0, 0.045 / inputRms));
        this.gain += (targetGain - this.gain) * 0.12;
      } else {
        this.gain += (1 - this.gain) * 0.04;
      }
      let sum = 0;
      for (let i = 0; i < samples.length; i++) {
        const amplified = Math.max(-1.2, Math.min(1.2, samples[i] * this.gain));
        const value = Math.tanh(amplified * 1.25);
        sum += value * value;
        pcm[i] = Math.round(value * 32767);
      }
      this.port.postMessage({
        rms: Math.sqrt(sum / samples.length),
        pcm: pcm.buffer,
        sampleRate,
        inputChannels: channels.length,
      }, [pcm.buffer]);
    }
    return true;
  }
}
registerProcessor('neuro-vad', NeuroVadProcessor);`;

/**
 * Browser-only monitor. It emits PCM16 frames directly from AudioWorklet; no
 * Encoded audio blob or local microphone file is created.
 */
export class BrowserVadRecorder {
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private sink: GainNode | null = null;
  private objectUrl: string | null = null;
  private readonly gate = new VoiceActivityGate();
  private muted = false;

  async start(
    onPcm: (pcm16: ArrayBuffer, sampleRate: number) => void,
    onState: (state: VadState, event: VadEvent) => void,
    profile: CaptureProfile = "live",
    inputDeviceId = "",
  ): Promise<CaptureMetadata> {
    if (this.stream && this.context) {
      const track = this.stream.getAudioTracks()[0];
      return {
        sampleRate: this.context.sampleRate,
        channels: 1,
        profile,
        settings: track?.getSettings() ?? {},
        constraints: track?.getConstraints() ?? {},
        supportedConstraints: navigator.mediaDevices.getSupportedConstraints(),
      };
    }
    if (!globalThis.AudioWorkletNode || !navigator.mediaDevices?.getUserMedia) {
      throw new Error("AudioWorklet VAD is unavailable in this browser");
    }
    const requestedConstraints = microphoneConstraints(profile, inputDeviceId);
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: requestedConstraints,
    });
    this.context = new AudioContext();
    this.objectUrl = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: "text/javascript" }));
    await this.context.audioWorklet.addModule(this.objectUrl);
    const source = this.context.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.context, "neuro-vad");
    this.sink = this.context.createGain();
    this.sink.gain.value = 0;
    source.connect(this.node);
    this.node.connect(this.sink).connect(this.context.destination);
    this.gate.start(performance.now());
    this.muted = false;
    onState("listening", null);
    this.node.port.onmessage = ({ data }) => {
      const pcm = data.pcm as ArrayBuffer;
      // Keep feeding silence while muted so backend VAD can close a speech
      // turn cleanly without tearing down the live session.
      onPcm(
        this.muted ? new ArrayBuffer(pcm.byteLength) : pcm,
        Number(data.sampleRate) || this.context?.sampleRate || 48000,
      );
      if (this.muted) return;
      const previousState = this.gate.snapshot();
      const event = this.gate.feed(Number(data.rms) || 0, performance.now());
      const nextState = this.gate.snapshot();
      // AudioWorklet calls this about a hundred times per second.  Forward only
      // meaningful VAD changes so consumers can safely attach one-shot actions
      // such as barge-in to the confirmed speech_started event.
      if (event || nextState !== previousState) {
        onState(nextState, event);
      }
    };
    const track = this.stream.getAudioTracks()[0];
    return {
      sampleRate: this.context.sampleRate,
      channels: 1,
      profile,
      settings: track?.getSettings() ?? {},
      constraints: track?.getConstraints() ?? requestedConstraints,
      supportedConstraints: navigator.mediaDevices.getSupportedConstraints(),
    };
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    const track = this.stream?.getAudioTracks()[0];
    if (track) track.enabled = !muted;
    if (muted) {
      this.gate.stop();
    } else if (this.context) {
      this.gate.start(performance.now());
    }
  }

  stop(): void {
    this.muted = false;
    this.gate.stop();
    this.node?.disconnect();
    this.sink?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    void this.context?.close();
    if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
    this.stream = null; this.context = null; this.node = null; this.sink = null; this.objectUrl = null;
  }
}

export class PcmInputClient {
  private socket: WebSocket | null = null;
  private ready = false;
  private pending: ArrayBuffer[] = [];
  private pendingBytes = 0;
  private maxPendingBytes = 192000;
  private connectionPromise: Promise<void> | null = null;
  private reconnectTimer: number | null = null;
  private reconnectAttempt = 0;
  private manuallyClosed = true;
  private config: { sampleRate: number; language: string; capture?: CaptureMetadata } | null = null;
  constructor(
    private readonly url: string,
    private readonly onEvent: (event: {
      type: string;
      transcript?: string;
      message?: string;
      phase?: string;
      action?: string;
      reason?: string;
      speaker_role?: string;
      generation?: number;
      observation_only?: boolean;
      initiative?: boolean;
    }) => void,
  ) {}
  async connect(
    sampleRate: number,
    language: string,
    capture?: CaptureMetadata,
  ): Promise<void> {
    this.config = { sampleRate, language, capture };
    this.manuallyClosed = false;
    if (this.socket?.readyState === WebSocket.OPEN) return;
    if (this.connectionPromise) return this.connectionPromise;
    this.connectionPromise = this.openSocket();
    try {
      await this.connectionPromise;
    } finally {
      this.connectionPromise = null;
    }
  }

  private async openSocket(): Promise<void> {
    const config = this.config;
    if (!config || this.manuallyClosed) return;
    const socket = new WebSocket(this.url);
    this.socket = socket;
    await new Promise<void>((resolve, reject) => {
      let settled = false;
      socket.onopen = () => {
        this.maxPendingBytes = Math.max(32000, config.sampleRate * 2);
        socket.send(JSON.stringify({
          type: "voice.input.start",
          protocol_version: 3,
          sample_rate: config.sampleRate,
          channels: 1,
          format: "pcm_s16le",
          language: config.language,
          capture_profile: config.capture?.profile ?? "live",
          capture_settings: config.capture?.settings ?? {},
          capture_constraints: config.capture?.constraints ?? {},
          supported_constraints: config.capture?.supportedConstraints ?? {},
        }));
      };
      socket.onerror = () => {
        if (!settled) {
          settled = true;
          reject(new Error("PCM input WebSocket failed"));
        }
      };
      socket.onmessage = (message) => {
        const event = JSON.parse(String(message.data));
        if (event.type === "voice.input.ready") {
          this.ready = true;
          for (const frame of this.pending) socket.send(frame);
          this.pending = [];
          this.pendingBytes = 0;
          this.reconnectAttempt = 0;
          settled = true;
          resolve();
        }
        this.onEvent(event);
      };
      socket.onclose = () => {
        const isCurrent = this.socket === socket;
        if (isCurrent) {
          this.socket = null;
          this.ready = false;
        }
        if (!settled) reject(new Error("PCM input WebSocket closed before ready"));
        if (isCurrent && !this.manuallyClosed) this.scheduleReconnect();
      };
    });
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null || this.manuallyClosed || !this.config) return;
    const delay = Math.min(2000, 250 * (2 ** this.reconnectAttempt));
    this.reconnectAttempt = Math.min(this.reconnectAttempt + 1, 4);
    this.onEvent({ type: "voice.input.reconnecting", message: `Повторное подключение через ${delay} мс` });
    this.reconnectTimer = globalThis.setTimeout(() => {
      this.reconnectTimer = null;
      void this.connect(this.config!.sampleRate, this.config!.language, this.config!.capture)
        .catch(() => undefined);
    }, delay);
  }

  sendPcm(pcm16: ArrayBuffer): void {
    if (this.manuallyClosed && this.config !== null) return;
    if (this.ready && this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(pcm16);
      return;
    }
    this.pending.push(pcm16);
    this.pendingBytes += pcm16.byteLength;
    while (this.pending.length > 1 && this.pendingBytes > this.maxPendingBytes) {
      this.pendingBytes -= this.pending.shift()!.byteLength;
    }
  }
  close(): void {
    this.manuallyClosed = true;
    this.config = null;
    if (this.reconnectTimer !== null) {
      globalThis.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: "voice.input.stop" }));
    }
    this.socket?.close();
    this.socket = null;
    this.ready = false;
    this.pending = [];
    this.pendingBytes = 0;
  }
}
