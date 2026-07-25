// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getStatus: vi.fn(), getSettings: vi.fn(), getAvatarStatus: vi.fn(), getEvents: vi.fn(),
  getTimelineMessages: vi.fn(), getModels: vi.fn(), getBackups: vi.fn(), getAvatarOverlay: vi.fn(),
  getMemories: vi.fn(), createMemory: vi.fn(), getMemoryAudit: vi.fn(),
  getPronunciations: vi.fn(), updatePronunciations: vi.fn(), updateVoiceExpression: vi.fn(), updateVoiceStyle: vi.fn(),
  updateRuntimeSettings: vi.fn(), getTimelineJournal: vi.fn(), searchTimeline: vi.fn(),
  getVoiceTtsStatus: vi.fn(), sendChatMessage: vi.fn(), sendVoiceMessage: vi.fn(),
  installModel: vi.fn(), removeModel: vi.fn(), createBackup: vi.fn(),
  clearMemories: vi.fn(), reindexMemories: vi.fn(), resetAllCompanionData: vi.fn(),
  confirmMemory: vi.fn(), rejectMemory: vi.fn(), deleteMemory: vi.fn(), restoreMemory: vi.fn(), updateMemory: vi.fn(),
  deleteTimelineRange: vi.fn(), saveDesktopApiKey: vi.fn(), sendAvatarTestEmotion: vi.fn(),
  sendAvatarTestGesture: vi.fn(), sendAvatarTestPhrase: vi.fn(), stopAvatar: vi.fn(), updateAvatarOverlay: vi.fn(),
}));

vi.mock("./api", () => ({
  ...api,
  isDesktopManaged: () => false,
  resolveApiUrl: (value: string) => value,
  voiceWebSocketUrl: () => "ws://test/voice",
  voiceInputWebSocketUrl: () => "ws://test/voice-input",
  WS_EVENTS_URL: "ws://test/events",
}));

import App from "./App";
import { MemoryPage } from "./memory";

const settings = {
  provider: "deepseek", model: "deepseek-chat", personality: "default", voice_language: "ru",
  voice_stt_model: "small", voice_tts_enabled: true, avatar_enabled: false, voice_tts_voice: "F4",
  voice_tts_provider: "silero", voice_tts_model: "v5_5_ru", voice_tts_device: "cpu", voice_tts_style: "auto", voice_tts_expression_level: "natural",
  voice_playback_rate: 1, voice_live_playback_prebuffer_segments: 2, voice_live_playback_prebuffer_ms: 700,
  chat_history_limit: 40, episodes_enabled: true, episode_soft_inactivity_minutes: 30,
  episode_hard_inactivity_minutes: 120, episode_maximum_messages: 100, episode_maximum_estimated_tokens: 12000,
  memory_enabled: true, memory_mode: "balanced", memory_incognito: false, log_level: "info",
  api_key_configured: true, available_personalities: ["default"], available_voice_languages: ["ru"], available_tts_voices: ["F4"],
};

class MockWebSocket {
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close() {}
  send() {}
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", MockWebSocket);
  Object.defineProperty(HTMLElement.prototype, "scrollTo", { configurable: true, value: vi.fn() });
  api.getStatus.mockResolvedValue({ backend: "ok", version: "0.6.0", api_key_configured: true, llm_model: "deepseek-chat" });
  api.getSettings.mockResolvedValue(settings);
  api.getAvatarStatus.mockResolvedValue({ enabled: false, protocol_version: 1, broadcast_policy: "", client_count: 0, clients: [], emotion_engine: { mapping_valid: true, current_emotion: "neutral", target_emotion: "neutral", intensity: 0, gesture: "", motion_profile: "", attack_ms: 0, minimum_hold_ms: 0, release_ms: 0, generation: 0, speaking: false } });
  api.getEvents.mockResolvedValue({ events: [] });
  api.getTimelineMessages.mockResolvedValue({ items: [], next_offset: null });
  api.getModels.mockResolvedValue({ models: [] });
  api.getBackups.mockResolvedValue([]);
  api.getAvatarOverlay.mockResolvedValue({ visible: true, always_on_top: true, locked: true, scale: 1, monitor: "", x: 0, y: 0, width: 0, height: 0 });
  api.getPronunciations.mockResolvedValue({ pronunciations: {} });
  api.getMemories.mockResolvedValue({ items: [] });
  api.createMemory.mockResolvedValue({ memory: {} });
  api.getMemoryAudit.mockResolvedValue({ items: [] });
  api.updateRuntimeSettings.mockResolvedValue(settings);
});

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("русский интерфейс", () => {
  it("собирает диалог в отдельную рабочую область с закреплённым композером", async () => {
    const { container } = render(<App />);

    await screen.findByRole("button", { name: "Диалог" });
    expect(container.querySelector("main.workspace-chat")).toBeInTheDocument();
    expect(container.querySelector(".chat-panel .message-list")).toBeInTheDocument();
    expect(container.querySelector(".chat-panel .chat-composer")).toBeInTheDocument();
    expect(container.querySelector(".chat-composer textarea")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Свободные руки" })).toBeInTheDocument();
  });

  it("открывает системный подраздел без отдельного пункта событий", async () => {
    render(<App />);

    expect(await screen.findByRole("button", { name: "Диалог" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Events" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Настройки" }));
    await screen.findByRole("button", { name: "Система" });
    fireEvent.click(screen.getByRole("button", { name: "Система" }));

    expect(await screen.findByRole("heading", { name: "Модели" })).toBeInTheDocument();
    expect(screen.getByText("Журнал событий")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Журнал событий"));
    expect(await screen.findByRole("button", { name: "Обновить журнал событий" })).toBeInTheDocument();
  });

  it("показывает только выбранный раздел настроек", async () => {
    const { container } = render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Настройки" }));
    expect(screen.getByLabelText("Стиль общения")).toBeVisible();
    expect(container.querySelector(".system-stack")).toHaveAttribute("hidden");

    fireEvent.click(screen.getByRole("button", { name: "Голос" }));
    expect(screen.getByLabelText("Язык голосового ввода")).toBeVisible();
    expect(screen.getByLabelText("Голос Silero")).toBeVisible();
    expect(screen.getByText("Silero · CPU · активен")).toBeVisible();
    expect(screen.getByLabelText("Стиль общения")).not.toBeVisible();
  });

  it("создаёт запись памяти с тем же API-полезным содержимым", async () => {
    render(<MemoryPage />);
    await screen.findByText("Записей пока нет");

    fireEvent.click(screen.getByRole("button", { name: "Добавить запись" }));
    fireEvent.change(screen.getByLabelText("Тип записи"), { target: { value: "предпочтение" } });
    fireEvent.change(screen.getByLabelText("Содержание"), { target: { value: "Любит чай" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить запись" }));

    await waitFor(() => expect(api.createMemory).toHaveBeenCalledWith({
      predicate: "предпочтение", value_text: "Любит чай", source_message_ids: [],
    }));
  });

  it("переключает раздел памяти в таком же меню", async () => {
    render(<MemoryPage />);
    await screen.findByRole("button", { name: "Все" });

    fireEvent.click(screen.getByRole("button", { name: "На проверке" }));

    await waitFor(() => expect(api.getMemories).toHaveBeenLastCalledWith("candidate", undefined));
  });
});
