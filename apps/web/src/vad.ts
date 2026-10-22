import workletUrl from "./audio/neuro-vad.worklet.js?url&no-inline";

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

export function microphoneConstraints(profile: CaptureProfile, inputDeviceId = ""): MediaTrackConstraints {
  const processing = {
    live: { echoCancellation: true, noiseSuppression: true, autoGainControl: false },
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
    private readonly threshold = 0.018,
    private readonly candidateMs = 120,
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



/**
 * Browser-only monitor. It emits PCM16 frames directly from AudioWorklet; no
 * Encoded audio blob or local microphone file is created.
 */
export class BrowserVadRecorder {
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private sink: GainNode | null = null;
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
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: requestedConstraints,
      });
    } catch (err) {
      if (inputDeviceId) {
        this.stream = await navigator.mediaDevices.getUserMedia({
          audio: microphoneConstraints(profile, ""),
        });
      } else {
        throw err;
      }
    }
    try {
      this.context = new AudioContext();
      if (this.context.state === "suspended") {
        await this.context.resume().catch(() => undefined);
      }
      await this.context.audioWorklet.addModule(workletUrl);
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
    } catch (error) {
      this.stop();
      throw error;
    }
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
    void this.context?.close().catch(() => undefined);
    this.stream = null; this.context = null; this.node = null; this.sink = null;
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
    this.connectionPromise = (async () => {
      try {
        await this.openSocket();
      } catch (firstErr) {
        if (!this.manuallyClosed) {
          // Quick retry before failing to absorb backend session transition delays
          await new Promise((r) => globalThis.setTimeout(r, 250));
          if (!this.manuallyClosed) {
            await this.openSocket();
            return;
          }
        }
        throw firstErr;
      }
    })();
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
          if (!this.manuallyClosed) {
            reject(new Error("PCM input WebSocket failed"));
          } else {
            resolve();
          }
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
        if (!settled) {
          settled = true;
          if (!this.manuallyClosed) {
            reject(new Error("PCM input WebSocket closed before ready"));
          } else {
            resolve();
          }
        }
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
