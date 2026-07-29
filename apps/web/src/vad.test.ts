import { afterEach, describe, expect, it, vi } from "vitest";
import { microphoneConstraints, PcmInputClient, VoiceActivityGate } from "./vad";

afterEach(() => vi.unstubAllGlobals());

describe("VoiceActivityGate", () => {
  it("debounces speech onset and end", () => {
    const gate = new VoiceActivityGate(.1, 100, 300);
    gate.start(0);
    expect(gate.feed(.2, 0)).toBeNull();
    expect(gate.feed(.2, 99)).toBeNull();
    expect(gate.feed(.2, 100)).toBe("speech_started");
    expect(gate.feed(0, 120)).toBeNull();
    expect(gate.feed(0, 419)).toBeNull();
    expect(gate.feed(0, 420)).toBe("speech_ended");
  });

  it("rejects a short noise candidate and resumes after a brief pause", () => {
    const gate = new VoiceActivityGate(.1, 100, 300);
    gate.start();
    gate.feed(.2, 0);
    expect(gate.feed(0, 10)).toBeNull();
    expect(gate.snapshot()).toBe("listening");
    gate.feed(.2, 20);
    expect(gate.feed(.2, 120)).toBe("speech_started");
    gate.feed(0, 150);
    gate.feed(.2, 200);
    expect(gate.snapshot()).toBe("speech");
  });

  it("maps microphone profiles to explicit browser processing", () => {
    expect(microphoneConstraints("headset")).toMatchObject({
      echoCancellation: false, noiseSuppression: false, autoGainControl: false,
    });
    expect(microphoneConstraints("balanced")).toMatchObject({
      echoCancellation: true, noiseSuppression: false, autoGainControl: false,
    });
    expect(microphoneConstraints("speakers")).toMatchObject({
      echoCancellation: true, noiseSuppression: true, autoGainControl: false,
    });
  });

  it("buffers initial PCM until the backend ready handshake", async () => {
    class FakeSocket {
      static last: FakeSocket;
      readyState = 1;
      sent: unknown[] = [];
      onopen: (() => void) | null = null;
      onmessage: ((event: { data: string }) => void) | null = null;
      onerror: (() => void) | null = null;
      onclose: (() => void) | null = null;
      constructor(_url: string) { FakeSocket.last = this; }
      send(value: unknown) { this.sent.push(value); }
      close() { this.onclose?.(); }
    }
    Object.assign(FakeSocket, { OPEN: 1 });
    vi.stubGlobal("WebSocket", FakeSocket);
    const client = new PcmInputClient("ws://voice", () => undefined);
    const first = new ArrayBuffer(640);
    client.sendPcm(first);
    const connecting = client.connect(48_000, "ru", "hands_free");
    FakeSocket.last.onopen?.();

    expect(FakeSocket.last.sent).toHaveLength(1);
    expect(JSON.parse(FakeSocket.last.sent[0] as string)).toMatchObject({
      type: "voice.input.start",
      sample_rate: 48_000,
      format: "pcm_s16le",
    });
    FakeSocket.last.onmessage?.({ data: JSON.stringify({ type: "voice.input.ready" }) });
    await connecting;
    expect(FakeSocket.last.sent[1]).toBe(first);
  });
});
