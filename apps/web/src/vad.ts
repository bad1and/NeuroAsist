export type VadState = "idle" | "listening" | "speech_candidate" | "speech" | "end_pending";
export type VadEvent = "speech_started" | "speech_ended" | null;

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

const WORKLET_SOURCE = `
class NeuroVadProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const samples = inputs[0]?.[0];
    if (!samples) return true;
    let sum = 0;
    for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
    const pcm = new Int16Array(samples.length);
    for (let i = 0; i < samples.length; i++) pcm[i] = Math.max(-1, Math.min(1, samples[i])) * 32767;
    this.port.postMessage({ rms: Math.sqrt(sum / samples.length), pcm: pcm.buffer }, [pcm.buffer]);
    return true;
  }
}
registerProcessor('neuro-vad', NeuroVadProcessor);`;

/**
 * Browser-only monitor. It emits PCM16 frames directly from AudioWorklet; no
 * MediaRecorder blob or local microphone file is created.
 */
export class BrowserVadRecorder {
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private sink: GainNode | null = null;
  private objectUrl: string | null = null;
  private readonly gate = new VoiceActivityGate();

  async start(onPcm: (pcm16: ArrayBuffer, sampleRate: number) => void, onState: (state: VadState) => void): Promise<void> {
    if (this.stream) return;
    if (!globalThis.AudioWorkletNode || !navigator.mediaDevices?.getUserMedia) {
      throw new Error("AudioWorklet VAD is unavailable in this browser");
    }
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    this.context = new AudioContext({ sampleRate: 16000 });
    this.objectUrl = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: "text/javascript" }));
    await this.context.audioWorklet.addModule(this.objectUrl);
    const source = this.context.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.context, "neuro-vad");
    this.sink = this.context.createGain();
    this.sink.gain.value = 0;
    source.connect(this.node);
    this.node.connect(this.sink).connect(this.context.destination);
    this.gate.start(performance.now());
    onState("listening");
    this.node.port.onmessage = ({ data }) => {
      onPcm(data.pcm as ArrayBuffer, this.context?.sampleRate ?? 16000);
      const event = this.gate.feed(Number(data.rms) || 0, performance.now());
      onState(this.gate.snapshot());
      void event;
    };
  }

  stop(): void {
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
  constructor(private readonly url: string, private readonly onEvent: (event: { type: string; transcript?: string; message?: string }) => void) {}
  async connect(sampleRate: number, language: string): Promise<void> {
    if (this.socket?.readyState === WebSocket.OPEN) return;
    const socket = new WebSocket(this.url);
    this.socket = socket;
    await new Promise<void>((resolve, reject) => {
      socket.onopen = () => { socket.send(JSON.stringify({ type: "voice.input.start", sample_rate: sampleRate, channels: 1, language })); resolve(); };
      socket.onerror = () => reject(new Error("PCM input WebSocket failed"));
      socket.onmessage = (message) => this.onEvent(JSON.parse(String(message.data)));
    });
  }
  sendPcm(pcm16: ArrayBuffer): void { if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(pcm16); }
  close(): void { this.socket?.send(JSON.stringify({ type: "voice.input.stop" })); this.socket?.close(); this.socket = null; }
}
