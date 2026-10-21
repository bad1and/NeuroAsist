// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { PublicSettings } from "../types";
const api = vi.hoisted(() => ({ getReadiness: vi.fn(), getSettings: vi.fn(), updateRuntimeSettings: vi.fn() }));
const devices = vi.hoisted(() => ({ getAudioDeviceCatalog: vi.fn() }));
vi.mock("../api", () => api);
vi.mock("../audio-devices", () => devices);
vi.mock("./ApiKeysSettings", () => ({ ApiKeysSettings: () => <div>Keys</div> }));
vi.mock("./ModelSettings", () => ({ ModelManager: () => <div>Models</div> }));
vi.mock("./AudioCheck", () => ({ AudioCheck: () => <div>Explicit audio check</div> }));
import { FirstConversationSetup } from "./FirstConversationSetup";
const settings = { api_key_configured: false, voice_input_device_id: "missing-mic", voice_output_device_id: "", voice_playback_rate: 1 } as PublicSettings;
beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear();
  api.getSettings.mockResolvedValue(settings);
  api.getReadiness.mockResolvedValue({ text_chat: "ready", live_ready: false });
  devices.getAudioDeviceCatalog.mockResolvedValue({ inputs: [], outputs: [], canEnumerate: true, canSelectOutput: false });
});
afterEach(cleanup);
it("requires a saved model key even when the text service reports ready", async () => {
  const start = vi.fn(), changed = vi.fn();
  const view = render(<FirstConversationSetup open settings={settings} onSettingsChanged={changed} onClose={vi.fn()} onStart={start} />);
  await act(async () => {});
  fireEvent.click(screen.getByRole("button", { name: "4. Первый разговор" }));
  expect(screen.getByRole("button", { name: "Начать разговор" })).toBeDisabled();
  expect(screen.getByText("Добавьте ключ модели на первом шаге.")).toBeInTheDocument();
  expect(localStorage.getItem("iris.setup.step.v1")).toBe("3");
  view.rerender(<FirstConversationSetup open settings={{ ...settings, api_key_configured: true }} onSettingsChanged={changed} onClose={vi.fn()} onStart={start} />);
  fireEvent.click(screen.getByRole("button", { name: "Начать разговор" }));
  expect(start).toHaveBeenCalledOnce();
});
it("resumes the saved device step without asking for microphone access", async () => {
  localStorage.setItem("iris.setup.step.v1", "2");
  render(<FirstConversationSetup open settings={settings} onSettingsChanged={vi.fn()} onClose={vi.fn()} onStart={vi.fn()} />);
  await act(async () => {});
  expect(screen.getByRole("button", { name: "3. Микрофон и звук" })).toHaveAttribute("aria-current", "step");
  expect(screen.getByRole("option", { name: "Выбранный микрофон недоступен" })).toBeInTheDocument();
  expect(devices.getAudioDeviceCatalog).toHaveBeenCalledWith(false);
  expect(api.updateRuntimeSettings).not.toHaveBeenCalled();
});
