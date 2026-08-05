export const DEFAULT_AUDIO_DEVICE_ID = "";

export type AudioDeviceOption = {
  deviceId: string;
  label: string;
};

export type AudioDeviceCatalog = {
  inputs: AudioDeviceOption[];
  outputs: AudioDeviceOption[];
  canEnumerate: boolean;
  canSelectOutput: boolean;
};

type AudioElementWithSinkId = HTMLAudioElement & {
  setSinkId?: (deviceId: string) => Promise<void>;
};

type AudioContextWithSinkId = AudioContext & {
  setSinkId?: (deviceId: string) => Promise<void>;
};

function deviceLabel(device: MediaDeviceInfo, index: number, fallback: string): string {
  return device.label.trim() || `${fallback} ${index + 1}`;
}

function canUseMediaDevices(): boolean {
  return typeof navigator !== "undefined" && Boolean(navigator.mediaDevices?.enumerateDevices);
}

/** The Tauri WebView uses this for local audio URLs, while live TTS uses AudioContext. */
export function canSelectAudioOutput(): boolean {
  if (typeof HTMLAudioElement === "undefined" || typeof AudioContext === "undefined") return false;
  return typeof (HTMLAudioElement.prototype as AudioElementWithSinkId).setSinkId === "function"
    && typeof (AudioContext.prototype as AudioContextWithSinkId).setSinkId === "function";
}

/**
 * Device names are hidden until the person grants microphone access. Asking
 * for that access is deliberately opt-in from the settings screen.
 */
export async function getAudioDeviceCatalog(requestMicrophoneAccess = false): Promise<AudioDeviceCatalog> {
  if (!canUseMediaDevices()) {
    return { inputs: [], outputs: [], canEnumerate: false, canSelectOutput: false };
  }

  if (requestMicrophoneAccess && navigator.mediaDevices?.getUserMedia) {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((track) => track.stop());
  }

  const devices = await navigator.mediaDevices.enumerateDevices();
  const inputs = devices
    .filter((device) => device.kind === "audioinput" && device.deviceId !== "default")
    .map((device, index) => ({ deviceId: device.deviceId, label: deviceLabel(device, index, "Микрофон") }));
  const outputs = devices
    .filter((device) => device.kind === "audiooutput" && device.deviceId !== "default")
    .map((device, index) => ({ deviceId: device.deviceId, label: deviceLabel(device, index, "Устройство вывода") }));
  return { inputs, outputs, canEnumerate: true, canSelectOutput: canSelectAudioOutput() };
}

export async function setAudioElementOutput(audio: HTMLAudioElement, deviceId: string): Promise<void> {
  const setSinkId = (audio as AudioElementWithSinkId).setSinkId;
  if (typeof setSinkId !== "function") {
    if (deviceId) throw new Error("Выбор устройства вывода не поддерживается WebView");
    return;
  }
  await setSinkId.call(audio, deviceId);
}

export async function setAudioContextOutput(context: AudioContext, deviceId: string): Promise<void> {
  const setSinkId = (context as AudioContextWithSinkId).setSinkId;
  if (typeof setSinkId !== "function") {
    if (deviceId) throw new Error("Выбор устройства вывода не поддерживается WebView");
    return;
  }
  await setSinkId.call(context, deviceId);
}
