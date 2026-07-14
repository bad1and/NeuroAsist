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
    this.port.postMessage(Math.sqrt(sum / samples.length));
    return true;
  }
}
registerProcessor('neuro-vad', NeuroVadProcessor);`;

/**
 * Browser-only VAD monitor. Audio remains in RAM and MediaRecorder is opened
 * only for a confirmed utterance; no raw microphone file is created locally.
 */
export class BrowserVadRecorder {
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private sink: GainNode | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private objectUrl: string | null = null;
  private readonly gate = new VoiceActivityGate();

  async start(onUtterance: (audio: Blob, endedAt: number) => void, onState: (state: VadState) => void): Promise<void> {
    if (this.stream) return;
    if (!globalThis.AudioWorkletNode || !navigator.mediaDevices?.getUserMedia) {
      throw new Error("AudioWorklet VAD is unavailable in this browser");
    }
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
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
    onState("listening");
    this.node.port.onmessage = ({ data }) => {
      const event = this.gate.feed(Number(data) || 0, performance.now());
      onState(this.gate.snapshot());
      if (event === "speech_started") this.beginCapture();
      if (event === "speech_ended") this.endCapture(onUtterance);
    };
  }

  stop(): void {
    this.gate.stop();
    if (this.recorder?.state === "recording") this.recorder.stop();
    this.recorder = null;
    this.node?.disconnect();
    this.sink?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    void this.context?.close();
    if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
    this.stream = null; this.context = null; this.node = null; this.sink = null; this.objectUrl = null; this.chunks = [];
  }

  private beginCapture(): void {
    if (!this.stream || this.recorder?.state === "recording") return;
    this.chunks = [];
    this.recorder = new MediaRecorder(this.stream);
    this.recorder.ondataavailable = (event) => { if (event.data.size) this.chunks.push(event.data); };
    this.recorder.start();
  }

  private endCapture(onUtterance: (audio: Blob, endedAt: number) => void): void {
    const recorder = this.recorder;
    if (!recorder || recorder.state !== "recording") return;
    recorder.onstop = () => {
      const audio = new Blob(this.chunks, { type: recorder.mimeType || "audio/webm" });
      this.chunks = [];
      if (audio.size) onUtterance(audio, Date.now());
    };
    recorder.stop();
  }
}
