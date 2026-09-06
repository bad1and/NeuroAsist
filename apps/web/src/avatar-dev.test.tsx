// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { AvatarDevStudioStandalonePage } from "./components/AvatarDevPanel";
import App from "./App";

afterEach(() => {
  cleanup();
});

vi.mock("./api", () => ({
  getAvatarStatus: vi.fn().mockResolvedValue({
    enabled: true,
    client_count: 1,
    clients: [{ client_name: "Unity Avatar", state: "idle" }],
  }),
  sendAvatarTestEmotion: vi.fn().mockResolvedValue(undefined),
  sendAvatarTestGesture: vi.fn().mockResolvedValue(undefined),
  sendAvatarTestPhrase: vi.fn().mockResolvedValue(undefined),
  stopAvatar: vi.fn().mockResolvedValue(undefined),
  isDesktopManaged: () => true,
  getStatus: vi.fn().mockResolvedValue({}),
  getSettings: vi.fn().mockResolvedValue({}),
  getEvents: vi.fn().mockResolvedValue([]),
  getPronunciations: vi.fn().mockResolvedValue({ pronunciations: {} }),
  getSttTerms: vi.fn().mockResolvedValue({ terms: {} }),
  getAvatarOverlay: vi.fn().mockResolvedValue(null),
}));

vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({ label: "qa_studio" }),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn().mockResolvedValue(() => undefined),
}));

import { fireEvent } from "@testing-library/react";
import { SettingsPage } from "./App";
import { openQaStudioWindow, closeQaStudioWindow } from "./desktop";

describe("AvatarDevStudioStandalonePage", () => {
  it("renders standalone page without crashing and handles tabs", () => {
    render(<AvatarDevStudioStandalonePage />);
    expect(screen.getByText("Iris QA Studio")).toBeInTheDocument();
    expect(screen.getByText("QA STUDIO v2.0")).toBeInTheDocument();

    // Switch to Gestures tab
    const gesturesTab = screen.getByRole("button", { name: /Жесты/ });
    fireEvent.click(gesturesTab);
    expect(screen.getByText("Руки & Приветствия")).toBeInTheDocument();

    // Switch to Speech tab
    const speechTab = screen.getByRole("button", { name: /Речь & Сценарии/ });
    fireEvent.click(speechTab);
    expect(screen.getByText("Быстрые сценарии тестирования")).toBeInTheDocument();
  });

  it("renders App when isQaStudioWindow is true", () => {
    (window as any).__IRIS_VIEW__ = "qa-studio";
    render(<App />);
    expect(screen.getByText("Iris QA Studio")).toBeInTheDocument();
  });

  it("renders SettingsPage with QA Studio switch and toggles it", () => {
    const onToggle = vi.fn();
    const mockSettings = {
      api_key_configured: true,
      provider: "test",
      model: "test",
      chat_history_limit: 10,
      log_level: "info",
      voice_language: "ru",
      voice_tts_voice: "ru_f1",
      voice_playback_rate: 1,
      voice_tts_provider: "teratts",
      developer_mode_enabled: true,
      interface_locale: "ru" as const,
      available_voice_languages: ["ru"],
      available_personalities: ["default"],
      available_tts_voices: ["ru_f1"],
    };

    const { rerender } = render(
      <SettingsPage
        settings={mockSettings as any}
        avatarStatus={null}
        avatarOverlay={null}
        events={[]}
        onRefreshEvents={vi.fn()}
        onRefreshAvatar={vi.fn()}
        onAvatarOverlayChanged={vi.fn()}
        onInterfaceLocaleChange={vi.fn()}
        onSettingsChanged={vi.fn()}
        qaStudioEnabled={false}
        onToggleQaStudioEnabled={onToggle}
      />,
    );

    // Expand Sistema group first, then switch to Interface section
    const systemBtn = screen.getByRole("button", { name: /Система/ });
    fireEvent.click(systemBtn);

    const interfaceBtn = screen.getByRole("button", { name: /Интерфейс/ });
    fireEvent.click(interfaceBtn);

    const switchInput = screen.getByRole("switch", { name: /Окно тестирования аватара/ });
    expect(switchInput).not.toBeChecked();

    fireEvent.click(switchInput);
    expect(onToggle).toHaveBeenCalledWith(true);

    // Rerender as checked
    rerender(
      <SettingsPage
        settings={mockSettings as any}
        avatarStatus={null}
        avatarOverlay={null}
        events={[]}
        onRefreshEvents={vi.fn()}
        onRefreshAvatar={vi.fn()}
        onAvatarOverlayChanged={vi.fn()}
        onInterfaceLocaleChange={vi.fn()}
        onSettingsChanged={vi.fn()}
        qaStudioEnabled={true}
        onToggleQaStudioEnabled={onToggle}
      />,
    );

    expect(screen.getByRole("switch", { name: /Окно тестирования аватара/ })).toBeChecked();
  });

  it("renders separate hidden DeepSeek and Coding API fields", () => {
    const mockSettings = {
      api_key_configured: true,
      coding_api_key_configured: false,
      provider: "deepseek",
      model: "deepseek-v4-flash",
      chat_history_limit: 10,
      log_level: "info",
      voice_language: "ru",
      voice_tts_voice: "ru_f1",
      voice_playback_rate: 1,
      voice_tts_provider: "teratts",
      developer_mode_enabled: false,
      interface_locale: "ru" as const,
      available_voice_languages: ["ru"],
      available_personalities: ["default"],
      available_tts_voices: ["ru_f1"],
    };

    render(
      <SettingsPage
        settings={mockSettings as any}
        initialSection="api-keys"
        avatarStatus={null}
        avatarOverlay={null}
        events={[]}
        onRefreshEvents={vi.fn()}
        onRefreshAvatar={vi.fn()}
        onAvatarOverlayChanged={vi.fn()}
        onInterfaceLocaleChange={vi.fn()}
        onSettingsChanged={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: "API-ключи" })).toBeInTheDocument();
    expect(screen.getByLabelText(/API-ключ DeepSeek/)).toHaveAttribute("type", "password");
    expect(screen.getByLabelText(/API-ключ Coding Agent/)).toHaveAttribute("type", "password");
    expect(screen.getByText("Ключ настроен")).toBeInTheDocument();
    expect(screen.getByText("Ключ не настроен")).toBeInTheDocument();
  });
});

