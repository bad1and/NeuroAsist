// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

import { getAudioDeviceCatalog, setAudioContextOutput, setAudioElementOutput } from "./audio-devices";

afterEach(() => vi.unstubAllGlobals());

describe("audio devices", () => {
  it("lists non-default input and output devices after a deliberate permission request", async () => {
    const stop = vi.fn();
    const getUserMedia = vi.fn(async () => ({ getTracks: () => [{ stop }] }));
    const enumerateDevices = vi.fn(async () => [
      { kind: "audioinput", deviceId: "default", label: "Default" },
      { kind: "audioinput", deviceId: "microphone", label: "USB Microphone" },
      { kind: "audiooutput", deviceId: "headphones", label: "Headphones" },
    ] as MediaDeviceInfo[]);
    vi.stubGlobal("navigator", { mediaDevices: { getUserMedia, enumerateDevices } });

    const catalog = await getAudioDeviceCatalog(true);

    expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(stop).toHaveBeenCalledTimes(1);
    expect(catalog.inputs).toEqual([{ deviceId: "microphone", label: "USB Microphone" }]);
    expect(catalog.outputs).toEqual([{ deviceId: "headphones", label: "Headphones" }]);
  });

  it("applies a selected sink to both native browser playback paths", async () => {
    const setElementSink = vi.fn(async () => undefined);
    const setContextSink = vi.fn(async () => undefined);

    await setAudioElementOutput({ setSinkId: setElementSink } as unknown as HTMLAudioElement, "headphones");
    await setAudioContextOutput({ setSinkId: setContextSink } as unknown as AudioContext, "headphones");

    expect(setElementSink).toHaveBeenCalledWith("headphones");
    expect(setContextSink).toHaveBeenCalledWith("headphones");
  });

  it("permits system-default playback when a sink API is unavailable", async () => {
    await expect(setAudioElementOutput({} as HTMLAudioElement, "")).resolves.toBeUndefined();
    await expect(setAudioContextOutput({} as AudioContext, "")).resolves.toBeUndefined();
  });
});
