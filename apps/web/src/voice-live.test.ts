import { beforeEach, describe, expect, it, vi } from "vitest";

import { TTSStreamPlayer } from "./voice-live";

type Deferred = {
  resolve: (buffer: AudioBuffer) => void;
  reject: (error: Error) => void;
};

class FakeSource {
  buffer: AudioBuffer | null = null;
  onended: (() => void) | null = null;
  connect = vi.fn();
  disconnect = vi.fn();
  stop = vi.fn();
  start = vi.fn();
}

class FakeAudioContext {
  static instance: FakeAudioContext;
  static initialState: AudioContextState = "running";
  currentTime = 1;
  state: AudioContextState;
  destination = {} as AudioDestinationNode;
  deferred: Deferred[] = [];
  sources: FakeSource[] = [];

  constructor() {
    this.state = FakeAudioContext.initialState;
    FakeAudioContext.instance = this;
  }
  resume = vi.fn(async () => undefined);
  decodeAudioData = vi.fn(() => new Promise<AudioBuffer>((resolve, reject) => {
    this.deferred.push({ resolve, reject });
  }));
  createBufferSource = vi.fn(() => {
    const source = new FakeSource();
    this.sources.push(source);
    return source as unknown as AudioBufferSourceNode;
  });
}

const audio = () => new ArrayBuffer(8);
const buffer = (duration: number) => ({ duration }) as AudioBuffer;
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("TTSStreamPlayer", () => {
  beforeEach(() => {
    vi.useRealTimers();
    FakeAudioContext.initialState = "running";
    vi.stubGlobal("AudioContext", FakeAudioContext);
  });

  it("resumes a suspended context during explicit unlock", async () => {
    FakeAudioContext.initialState = "suspended";
    const player = new TTSStreamPlayer(vi.fn(), vi.fn(), vi.fn());
    await player.unlock();
    expect(FakeAudioContext.instance.resume).toHaveBeenCalledTimes(1);
  });

  it("decodes and schedules segments strictly in sequence", async () => {
    const player = new TTSStreamPlayer(vi.fn(), vi.fn(), vi.fn());
    player.begin("utterance");
    const first = player.enqueue("utterance", 0, audio());
    const second = player.enqueue("utterance", 1, audio());
    await tick();
    const context = FakeAudioContext.instance;
    expect(context.decodeAudioData).toHaveBeenCalledTimes(1);
    context.deferred[0].resolve(buffer(1));
    await first;
    expect(context.createBufferSource).not.toHaveBeenCalled();
    await tick();
    expect(context.decodeAudioData).toHaveBeenCalledTimes(2);
    context.deferred[1].resolve(buffer(0.5));
    await second;
    expect(context.sources[0].start).toHaveBeenCalledWith(1.03);
    expect(context.sources[1].start.mock.calls[0][0]).toBeCloseTo(2.03);
  });

  it("starts prebuffer after timeout when only one buffer is ready", async () => {
    vi.useFakeTimers();
    const player = new TTSStreamPlayer(vi.fn(), vi.fn(), vi.fn(), {
      prebufferSegments: 2,
      prebufferMs: 700,
    });
    player.begin("utterance");
    await player.unlock();
    const first = player.enqueue("utterance", 0, audio());
    await Promise.resolve();
    await Promise.resolve();
    const context = FakeAudioContext.instance;
    context.deferred[0].resolve(buffer(1));
    await first;
    expect(context.createBufferSource).not.toHaveBeenCalled();
    vi.advanceTimersByTime(700);
    expect(context.createBufferSource).toHaveBeenCalledTimes(1);
  });

  it("rejects duplicate or skipped segment ids", async () => {
    const onError = vi.fn();
    const player = new TTSStreamPlayer(vi.fn(), vi.fn(), onError);
    player.begin("utterance");
    await expect(player.enqueue("utterance", 1, audio())).rejects.toThrow(
      "Unexpected TTS segment order",
    );
    expect(onError).toHaveBeenCalledTimes(1);
  });

  it("invalidates an unfinished decode on stop", async () => {
    const player = new TTSStreamPlayer(vi.fn(), vi.fn(), vi.fn());
    player.begin("utterance");
    const pending = player.enqueue("utterance", 0, audio());
    await tick();
    const context = FakeAudioContext.instance;
    player.stop();
    context.deferred[0].resolve(buffer(1));
    await pending;
    expect(context.createBufferSource).not.toHaveBeenCalled();
  });

  it("reports decode failures", async () => {
    const onError = vi.fn();
    const player = new TTSStreamPlayer(vi.fn(), vi.fn(), onError);
    player.begin("utterance");
    const pending = player.enqueue("utterance", 0, audio());
    await tick();
    FakeAudioContext.instance.deferred[0].reject(new Error("bad mp3"));
    await expect(pending).rejects.toThrow("bad mp3");
    await tick();
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: "bad mp3" }));
  });
});
