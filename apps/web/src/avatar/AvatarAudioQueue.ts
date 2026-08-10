type PlaybackHandlers = {
  onStarted: () => void;
  onFinished: () => void;
  onFailed: (reason: string) => void;
};

type QueuedBuffer = { sequence: number; buffer: AudioBuffer };

/** Serialises WAV playback and exposes a stable speech-volume signal for lips. */
export class AvatarAudioQueue {
  private context: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private gain: GainNode | null = null;
  private source: AudioBufferSourceNode | null = null;
  private queued: QueuedBuffer[] = [];
  private streamEnded = false;
  private streamStarted = false;
  private generation = 0;
  private handlers: PlaybackHandlers | null = null;
  private muted = false;
  private nextSequence: number | null = null;
  private samples = new Uint8Array(256);

  async playUrl(url: string, handlers: PlaybackHandlers): Promise<void> {
    const generation = this.reset();
    this.handlers = handlers;
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`WAV download failed (HTTP ${response.status})`);
      const buffer = await this.audioContext().decodeAudioData(await response.arrayBuffer());
      if (generation !== this.generation) return;
      this.playBuffer(buffer, generation, true, true);
    } catch (error) {
      if (generation === this.generation) handlers.onFailed(error instanceof Error ? error.message : "WAV decode failed");
    }
  }

  beginStream(handlers: PlaybackHandlers): void {
    this.reset();
    this.handlers = handlers;
  }

  async enqueueBase64Wav(sequence: number, audioBase64: string): Promise<void> {
    const generation = this.generation;
    try {
      const raw = atob(audioBase64);
      const bytes = new Uint8Array(raw.length);
      for (let index = 0; index < raw.length; index += 1) bytes[index] = raw.charCodeAt(index);
      const buffer = await this.audioContext().decodeAudioData(bytes.buffer);
      if (generation !== this.generation) return;
      if (this.queued.some((item) => item.sequence === sequence)) return;
      this.queued.push({ sequence, buffer });
      this.queued.sort((left, right) => left.sequence - right.sequence);
      if (this.nextSequence === null) this.nextSequence = this.queued[0].sequence;
      this.startNext(generation);
    } catch (error) {
      if (generation === this.generation) this.fail(error instanceof Error ? error.message : "WAV decode failed");
      throw error;
    }
  }

  endStream(): void {
    this.streamEnded = true;
    if (!this.source && this.queued.length === 0) this.finish();
  }

  stop(): void { this.reset(); }

  dispose(): void {
    this.reset();
    void this.context?.close();
    this.context = null;
    this.analyser = null;
    this.gain = null;
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    if (this.gain) this.gain.gain.value = muted ? 0 : 1;
  }

  volume(): number {
    if (!this.analyser || !this.source) return 0;
    this.analyser.getByteTimeDomainData(this.samples);
    let energy = 0;
    for (const value of this.samples) {
      const sample = (value - 128) / 128;
      energy += sample * sample;
    }
    return Math.min(1, Math.sqrt(energy / this.samples.length) * 4.5);
  }

  private audioContext(): AudioContext {
    if (this.context) return this.context;
    this.context = new AudioContext();
    this.analyser = this.context.createAnalyser();
    this.analyser.fftSize = 512;
    this.gain = this.context.createGain();
    this.gain.gain.value = this.muted ? 0 : 1;
    this.analyser.connect(this.gain);
    this.gain.connect(this.context.destination);
    return this.context;
  }

  private reset(): number {
    this.generation += 1;
    this.source?.stop();
    this.source?.disconnect();
    this.source = null;
    this.queued = [];
    this.streamEnded = false;
    this.streamStarted = false;
    this.nextSequence = null;
    this.handlers = null;
    return this.generation;
  }

  private startNext(generation: number): void {
    if (this.source || generation !== this.generation || this.nextSequence === null) return;
    const index = this.queued.findIndex((item) => item.sequence === this.nextSequence);
    if (index < 0) return;
    const [item] = this.queued.splice(index, 1);
    this.nextSequence += 1;
    this.playBuffer(item.buffer, generation, !this.streamStarted, false);
  }

  private playBuffer(buffer: AudioBuffer, generation: number, announceStart: boolean, isSingle: boolean): void {
    const context = this.audioContext();
    // Tauri's WebView normally permits this directly; browsers that suspended
    // the context after a focus change resume as soon as the next speech event
    // arrives.
    if (context.state === "suspended") void context.resume();
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.analyser!);
    this.source = source;
    if (announceStart) {
      this.streamStarted = true;
      this.handlers?.onStarted();
    }
    source.onended = () => {
      if (generation !== this.generation || this.source !== source) return;
      source.disconnect();
      this.source = null;
      if (isSingle) this.finish();
      else if (this.queued.length) this.startNext(generation);
      else if (this.streamEnded) this.finish();
    };
    source.start();
  }

  private finish(): void {
    const handlers = this.handlers;
    this.handlers = null;
    handlers?.onFinished();
  }

  private fail(reason: string): void {
    const handlers = this.handlers;
    this.reset();
    handlers?.onFailed(reason);
  }
}
