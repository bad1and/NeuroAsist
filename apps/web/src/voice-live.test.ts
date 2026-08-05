import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlaybackCoordinator, TTSStreamPlayer } from "./voice-live";

describe("PlaybackCoordinator", () => {
  it("gives exactly one owner a generation-scoped lease", () => {
    const coordinator = new PlaybackCoordinator();
    const unity = coordinator.acquire("unity", "first");
    const browser = coordinator.acquire("desktop_ui", "second");

    expect(coordinator.isCurrent(unity)).toBe(false);
    expect(coordinator.isOwner("unity", "first")).toBe(false);
    expect(coordinator.isCurrent(browser)).toBe(true);
    expect(coordinator.isOwner("desktop_ui", "second")).toBe(true);
  });

  it("does not let an old completion release a newer utterance", () => {
    const coordinator = new PlaybackCoordinator();
    const first = coordinator.acquire("desktop_ui", "first");
    const second = coordinator.acquire("desktop_ui", "second");

    expect(coordinator.release(first)).toBe(false);
    expect(coordinator.snapshot()).toEqual(second);
    expect(coordinator.release(second)).toBe(true);
    expect(coordinator.snapshot()).toBeNull();
  });
});

type Deferred = {
  resolve: (buffer: AudioBuffer) => void;
  reject: (error: Error) => void;
};

class FakeSource {
  buffer: AudioBuffer | null = null;
  onended: (() => void) | null = null;
  playbackRate = { value: 1 };
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
  setSinkId = vi.fn(async () => undefined);
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

  it("routes live synthesis to the selected output device", async () => {
    const player = new TTSStreamPlayer(vi.fn(), vi.fn(), vi.fn(), { outputDeviceId: "headphones" });
    await player.unlock();
    expect(FakeAudioContext.instance.setSinkId).toHaveBeenCalledWith("headphones");
  });

  it("decodes and schedules segments strictly in sequence", async () => {
    const player = new TTSStreamPlayer(vi.fn(), vi.fn(), vi.fn());
    player.begin("utterance");
    const first = player.enqueue("utterance", 0, audio());
    const second = player.enqueue("utterance", 1, audio());
    await tick();
    const context = FakeAudioContext.instance;
    expect(context.decodeAudioData).toHaveBeenCalledTimes(2);
    context.deferred[1].resolve(buffer(0.5));
    await second;
    expect(context.createBufferSource).not.toHaveBeenCalled();
    context.deferred[0].resolve(buffer(1));
    await first;
    expect(context.createBufferSource).toHaveBeenCalledTimes(2);
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
    context.deferred[0].resolve(buffer(0.5));
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

  it("decodes WAV segments through AudioContext", async () => {
    const player = new TTSStreamPlayer(vi.fn(), vi.fn(), vi.fn());
    player.begin("utterance");
    const pending = player.enqueue("utterance", 0, audio(), { format: "wav" });
    await tick();
    const context = FakeAudioContext.instance;
    expect(context.decodeAudioData).toHaveBeenCalledTimes(1);
    context.deferred[0].resolve(buffer(0.25));
    player.finish("utterance");
    await pending;
    expect(context.createBufferSource).toHaveBeenCalledTimes(1);
  });

  it("keeps backend-rendered live buffers at normal browser playback rate", async () => {
    const player = new TTSStreamPlayer(vi.fn(), vi.fn(), vi.fn(), {
      playbackRate: 1.15,
    });
    player.begin("utterance");
    const pending = player.enqueue("utterance", 0, audio());
    await tick();
    const context = FakeAudioContext.instance;
    context.deferred[0].resolve(buffer(0.25));
    player.finish("utterance");
    await pending;
    expect(context.sources[0].playbackRate.value).toBe(1);
  });

  it.each([0.75, 1, 1.25])("never applies backend tempo twice at playback rate %s", async (rate) => {
    const player = new TTSStreamPlayer(vi.fn(), vi.fn(), vi.fn(), { playbackRate: rate });
    player.begin("utterance");
    const first = player.enqueue("utterance", 0, audio());
    const second = player.enqueue("utterance", 1, audio());
    await tick();
    const context = FakeAudioContext.instance;
    context.deferred[1].resolve(buffer(0.5));
    await second;
    context.deferred[0].resolve(buffer(1));
    await first;

    expect(context.sources[1].start.mock.calls[0][0]).toBeCloseTo(2.03);
    expect(context.sources[1].playbackRate.value).toBe(1);
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
