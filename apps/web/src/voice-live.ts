import type { VoiceServerEvent } from "./types";

export type TTSStreamPlayerOptions = {
  prebufferSegments?: number;
  prebufferMs?: number;
  playbackRate?: number;
  startLeadMs?: number;
};

export type PlaybackOwner = "unity" | "desktop_ui" | "none";

export type PlaybackLease = {
  owner: Exclude<PlaybackOwner, "none">;
  utteranceId: string;
  generation: number;
};

/** Ensures the browser and Unity never play the same utterance concurrently. */
export class PlaybackCoordinator {
  private current: PlaybackLease | null = null;
  private generation = 0;

  acquire(owner: Exclude<PlaybackOwner, "none">, utteranceId: string): PlaybackLease {
    this.generation += 1;
    this.current = { owner, utteranceId, generation: this.generation };
    return this.current;
  }

  release(lease: PlaybackLease | null): boolean {
    if (!lease || !this.isCurrent(lease)) return false;
    this.current = null;
    return true;
  }

  cancel(): void {
    this.generation += 1;
    this.current = null;
  }

  isOwner(owner: Exclude<PlaybackOwner, "none">, utteranceId: string): boolean {
    return this.current?.owner === owner && this.current.utteranceId === utteranceId;
  }

  isCurrent(lease: PlaybackLease): boolean {
    return this.current?.generation === lease.generation
      && this.current.utteranceId === lease.utteranceId
      && this.current.owner === lease.owner;
  }

  snapshot(): PlaybackLease | null {
    return this.current;
  }
}

export class TTSStreamPlayer {
  private context: AudioContext | null = null;
  private scheduledUntil = 0;
  private sources = new Set<AudioBufferSourceNode>();
  private readyBuffers: Array<{ buffer: AudioBuffer; text: string }> = [];
  private generation = 0;
  private started = false;
  private decodedBySegment = new Map<number, { buffer: AudioBuffer; text: string }>();
  private nextDecodedSegment = 0;
  private pendingDecodes = 0;
  private activeUtteranceId: string | null = null;
  private lastQueuedSegment = -1;
  private serverFinished = false;
  private prebufferTimer: ReturnType<typeof globalThis.setTimeout> | null = null;
  private prebufferSegments: number;
  private underrunPrebufferSegments = 0;
  private prebufferMs: number;
  private startLeadMs: number;

  constructor(
    private readonly onStarted: () => void,
    private readonly onFinished: () => void,
    private readonly onError: (error: Error) => void,
    options: TTSStreamPlayerOptions = {},
    private readonly onUnderrun: (gapMs: number) => void = () => undefined,
    private readonly onSegmentFinished: (text: string) => void = () => undefined,
    private readonly onDecoded: (segmentId: number, decodeMs: number) => void = () => undefined,
  ) {
    this.prebufferSegments = Math.max(1, options.prebufferSegments ?? 1);
    this.prebufferMs = Math.max(0, options.prebufferMs ?? 0);
    this.startLeadMs = Math.max(0, options.startLeadMs ?? 30);
  }

  updateOptions(options: TTSStreamPlayerOptions): void {
    this.prebufferSegments = Math.max(1, options.prebufferSegments ?? this.prebufferSegments);
    this.prebufferMs = Math.max(0, options.prebufferMs ?? this.prebufferMs);
    this.startLeadMs = Math.max(0, options.startLeadMs ?? this.startLeadMs);
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
    audio: Pick<VoiceServerEvent, "format" | "sample_rate" | "channels" | "text"> = {},
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
    const decodeStarted = performance.now();
    const result = (async () => {
      await this.unlock();
      const context = this.context!;
      const buffer = await context.decodeAudioData(data.slice(0));
      this.onDecoded(segmentId, Math.round(performance.now() - decodeStarted));
      const decoded = { buffer, text: audio.text ?? "" };
      if (generation !== this.generation || utteranceId !== this.activeUtteranceId) return;
      this.decodedBySegment.set(segmentId, decoded);
      this.flushDecodedInOrder();
    })();
    void result
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
    this.decodedBySegment.clear();
    this.nextDecodedSegment = 0;
    this.scheduledUntil = this.context?.currentTime ?? 0;
    this.started = false;
    this.pendingDecodes = 0;
    this.activeUtteranceId = null;
    this.lastQueuedSegment = -1;
    this.serverFinished = false;
  }

  private maybeFinished(): void {
    if (
      this.serverFinished
      && this.pendingDecodes === 0
      && this.sources.size === 0
      && this.readyBuffers.length === 0
      && this.decodedBySegment.size === 0
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

  private flushDecodedInOrder(): void {
    while (this.decodedBySegment.has(this.nextDecodedSegment)) {
      const decoded = this.decodedBySegment.get(this.nextDecodedSegment)!;
      this.decodedBySegment.delete(this.nextDecodedSegment);
      this.nextDecodedSegment += 1;
      if (!this.started) {
        this.readyBuffers.push(decoded);
        this.armPrebufferTimer();
        const bufferedSeconds = this.readyBuffers.reduce((sum, item) => sum + item.buffer.duration, 0);
        if (
          this.readyBuffers.length >= Math.max(this.prebufferSegments, this.underrunPrebufferSegments)
          || bufferedSeconds >= this.prebufferMs / 1000
          || this.serverFinished
        ) {
          this.flushPrebuffer();
        }
      } else {
        this.scheduleBuffer(decoded);
      }
    }
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

  private scheduleBuffer(item: { buffer: AudioBuffer; text: string }): void {
    const { buffer, text } = item;
    const context = this.context!;
    const gapMs = this.started ? Math.max(0, (context.currentTime - this.scheduledUntil) * 1000) : 0;
    if (gapMs > 50) {
      this.underrunPrebufferSegments = Math.min(
        3,
        Math.max(this.prebufferSegments, this.underrunPrebufferSegments) + 1,
      );
      this.onUnderrun(Math.round(gapMs));
    }
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.playbackRate.value = 1;
    source.connect(context.destination);
    const startAt = Math.max(context.currentTime + this.startLeadMs / 1000, this.scheduledUntil);
    this.scheduledUntil = startAt + buffer.duration;
    this.sources.add(source);
    source.onended = () => {
      this.sources.delete(source);
      source.disconnect();
      this.onSegmentFinished(text);
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
        // A cancelled lease has no active utterance: discard every late frame
        // until a fresh server-side start establishes the next generation.
        if (event.type !== "voice.utterance.started" && !this.activeUtteranceId) return;
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

  send(type: string, payload: Record<string, unknown> = {}): boolean {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type, utterance_id: this.activeUtteranceId, ...payload }));
      return true;
    }
    return false;
  }

  cancel(): boolean { return this.send("voice.cancel"); }
  close(): void {
    this.socket?.close();
    this.socket = null;
    this.connecting = null;
  }
}
