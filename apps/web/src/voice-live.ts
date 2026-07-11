import type { VoiceServerEvent } from "./types";

export type TTSStreamPlayerOptions = {
  prebufferSegments?: number;
  prebufferMs?: number;
};

export class TTSStreamPlayer {
  private context: AudioContext | null = null;
  private scheduledUntil = 0;
  private sources = new Set<AudioBufferSourceNode>();
  private readyBuffers: AudioBuffer[] = [];
  private generation = 0;
  private started = false;
  private decodeChain: Promise<void> = Promise.resolve();
  private pendingDecodes = 0;
  private activeUtteranceId: string | null = null;
  private lastQueuedSegment = -1;
  private serverFinished = false;
  private prebufferTimer: ReturnType<typeof globalThis.setTimeout> | null = null;
  private readonly prebufferSegments: number;
  private readonly prebufferMs: number;

  constructor(
    private readonly onStarted: () => void,
    private readonly onFinished: () => void,
    private readonly onError: (error: Error) => void,
    options: TTSStreamPlayerOptions = {},
    private readonly onUnderrun: (gapMs: number) => void = () => undefined,
  ) {
    this.prebufferSegments = Math.max(1, options.prebufferSegments ?? 2);
    this.prebufferMs = Math.max(0, options.prebufferMs ?? 700);
  }

  async unlock(): Promise<void> {
    this.context ??= new AudioContext();
    if (this.context.state === "suspended") await this.context.resume();
  }

  begin(utteranceId: string): void {
    if (this.activeUtteranceId !== utteranceId) this.stop();
    this.activeUtteranceId = utteranceId;
    this.serverFinished = false;
  }

  enqueue(
    utteranceId: string,
    segmentId: number,
    data: ArrayBuffer,
    audio: Pick<VoiceServerEvent, "format" | "sample_rate" | "channels"> = {},
  ): Promise<void> {
    if (utteranceId !== this.activeUtteranceId) return Promise.resolve();
    if (segmentId !== this.lastQueuedSegment + 1) {
      const error = new Error(`Unexpected TTS segment order: ${segmentId}`);
      this.onError(error);
      return Promise.reject(error);
    }
    this.lastQueuedSegment = segmentId;
    const generation = this.generation;
    this.pendingDecodes += 1;
    const decode = async () => {
      await this.unlock();
      const context = this.context!;
      const buffer = await context.decodeAudioData(data.slice(0));
      if (generation !== this.generation || utteranceId !== this.activeUtteranceId) return;
      if (!this.started) {
        this.readyBuffers.push(buffer);
        this.armPrebufferTimer();
        const bufferedSeconds = this.readyBuffers.reduce((sum, item) => sum + item.duration, 0);
        if (
          this.readyBuffers.length >= this.prebufferSegments
          || bufferedSeconds >= this.prebufferMs / 1000
          || this.serverFinished
        ) {
          this.flushPrebuffer();
        }
      } else {
        this.scheduleBuffer(buffer);
      }
    };
    const result = this.decodeChain.then(decode);
    this.decodeChain = result
      .catch((error: unknown) => {
        if (generation === this.generation) {
          this.onError(error instanceof Error ? error : new Error("Could not decode TTS audio"));
        }
      })
      .finally(() => {
        if (generation === this.generation) {
          this.pendingDecodes -= 1;
          this.maybeFinished();
        }
      });
    return result;
  }

  finish(utteranceId: string): void {
    if (utteranceId !== this.activeUtteranceId) return;
    this.serverFinished = true;
    if (!this.started && this.readyBuffers.length > 0) this.flushPrebuffer();
    this.maybeFinished();
  }

  stop(): void {
    this.generation += 1;
    this.clearPrebufferTimer();
    for (const source of this.sources) {
      try { source.stop(); } catch { /* already stopped */ }
      source.disconnect();
    }
    this.sources.clear();
    this.readyBuffers = [];
    this.scheduledUntil = this.context?.currentTime ?? 0;
    this.started = false;
    this.pendingDecodes = 0;
    this.activeUtteranceId = null;
    this.lastQueuedSegment = -1;
    this.serverFinished = false;
    this.decodeChain = Promise.resolve();
  }

  private maybeFinished(): void {
    if (
      this.serverFinished
      && this.pendingDecodes === 0
      && this.sources.size === 0
      && this.readyBuffers.length === 0
    ) {
      this.serverFinished = false;
      this.onFinished();
    }
  }

  private armPrebufferTimer(): void {
    if (this.prebufferTimer !== null || this.prebufferMs <= 0) return;
    this.prebufferTimer = globalThis.setTimeout(() => {
      this.prebufferTimer = null;
      this.flushPrebuffer();
    }, this.prebufferMs);
  }

  private clearPrebufferTimer(): void {
    if (this.prebufferTimer === null) return;
    globalThis.clearTimeout(this.prebufferTimer);
    this.prebufferTimer = null;
  }

  private flushPrebuffer(): void {
    if (this.activeUtteranceId === null || this.readyBuffers.length === 0) return;
    this.clearPrebufferTimer();
    const buffers = this.readyBuffers;
    this.readyBuffers = [];
    for (const buffer of buffers) this.scheduleBuffer(buffer);
    this.maybeFinished();
  }

  private scheduleBuffer(buffer: AudioBuffer): void {
    const context = this.context!;
    const gapMs = this.started ? Math.max(0, (context.currentTime - this.scheduledUntil) * 1000) : 0;
    if (gapMs > 50) this.onUnderrun(Math.round(gapMs));
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    const startAt = Math.max(context.currentTime + 0.075, this.scheduledUntil);
    this.scheduledUntil = startAt + buffer.duration;
    this.sources.add(source);
    source.onended = () => {
      this.sources.delete(source);
      source.disconnect();
      this.maybeFinished();
    };
    source.start(startAt);
    if (!this.started) {
      this.started = true;
      globalThis.setTimeout(this.onStarted, Math.max(0, (startAt - context.currentTime) * 1000));
    }
  }

}

export class VoiceSocketClient {
  private socket: WebSocket | null = null;
  private connecting: Promise<void> | null = null;
  private pendingSegment: VoiceServerEvent | null = null;
  activeUtteranceId: string | null = null;

  constructor(
    private readonly url: string,
    private readonly onEvent: (event: VoiceServerEvent) => void,
    private readonly onAudio: (audio: ArrayBuffer, segment: VoiceServerEvent) => void,
  ) {}

  async connect(): Promise<void> {
    if (this.socket?.readyState === WebSocket.OPEN) return;
    if (this.connecting) return this.connecting;
    this.socket = new WebSocket(this.url);
    this.socket.binaryType = "arraybuffer";
    this.connecting = new Promise<void>((resolve, reject) => {
      const socket = this.socket!;
      let opened = false;
      const fail = () => {
        if (!opened) reject(new Error(`Live voice connection failed: ${this.url}`));
      };
      socket.onopen = () => {
        opened = true;
        resolve();
      };
      socket.onerror = () => {
        fail();
        socket.close();
      };
      socket.onclose = () => {
        this.pendingSegment = null;
        if (this.socket === socket) this.socket = null;
        fail();
      };
      socket.onmessage = (message) => {
        if (message.data instanceof ArrayBuffer) {
          if (this.pendingSegment) {
            this.onAudio(message.data, this.pendingSegment);
            this.pendingSegment = null;
          }
          return;
        }
        const event = JSON.parse(String(message.data)) as VoiceServerEvent;
        if (event.type === "voice.utterance.started") {
          this.activeUtteranceId = event.utterance_id;
        }
        if (this.activeUtteranceId && event.utterance_id !== this.activeUtteranceId) return;
        if (event.type === "tts.segment.started") this.pendingSegment = event;
        this.onEvent(event);
      };
    }).finally(() => {
      this.connecting = null;
    });
    return this.connecting;
  }

  activate(utteranceId: string): void {
    this.activeUtteranceId = utteranceId;
  }

  clearActive(): void {
    this.activeUtteranceId = null;
    this.pendingSegment = null;
  }

  send(type: string, payload: Record<string, unknown> = {}): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type, utterance_id: this.activeUtteranceId, ...payload }));
    }
  }

  cancel(): void { this.send("voice.cancel"); }
  close(): void {
    this.socket?.close();
    this.socket = null;
    this.connecting = null;
  }
}
