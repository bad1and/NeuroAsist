// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getStatus: vi.fn(), getSettings: vi.fn(), getAvatarStatus: vi.fn(), getEvents: vi.fn(),
  getTimelineMessages: vi.fn(), getModels: vi.fn(), getBackups: vi.fn(), getAvatarOverlay: vi.fn(),
  getMemories: vi.fn(), createMemory: vi.fn(), getMemoryAudit: vi.fn(),
  getPronunciations: vi.fn(), updatePronunciations: vi.fn(), updateVoiceExpression: vi.fn(), updateVoiceStyle: vi.fn(),
  getSttTerms: vi.fn(), updateSttTerms: vi.fn(),
  updateRuntimeSettings: vi.fn(), getTimelineJournal: vi.fn(), searchTimeline: vi.fn(),
  getVoiceTtsStatus: vi.fn(), sendChatMessage: vi.fn(), sendVoiceMessage: vi.fn(),
  installModel: vi.fn(), removeModel: vi.fn(), createBackup: vi.fn(),
  clearMemories: vi.fn(), reindexMemories: vi.fn(), resetAllCompanionData: vi.fn(),
  resetConversationSession: vi.fn(), getConversationSession: vi.fn(),
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
import { JournalPage } from "./journal";
import { MemoryPage } from "./memory";

const settings = {
  provider: "deepseek", model: "deepseek-chat", personality: "default", voice_language: "ru",
  voice_microphone_profile: "balanced", voice_vad: { configured_provider: "silero", active_provider: "silero", ready: true, fallback: false },
  voice_input_diagnostic_audio_enabled: false,
  voice_stt_model: "small", voice_tts_enabled: true, avatar_enabled: false, avatar_placement: "desktop_overlay", avatar_in_app_visible: true, voice_tts_voice: "F4",
  voice_tts_provider: "silero", voice_tts_model: "v5_5_ru", voice_tts_device: "cpu", voice_tts_style: "auto", voice_tts_expression_level: "natural",
  voice_playback_rate: 1, voice_live_playback_prebuffer_segments: 2, voice_live_playback_prebuffer_ms: 700,
  voice_live_playback_start_lead_ms: 30,
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
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { this.removeAttribute("open"); this.dispatchEvent(new Event("close")); } });
  api.getStatus.mockResolvedValue({ app_name: "Iris", backend: "ok", database: "ok", version: "0.6.0", api_key_configured: true, llm_provider: "deepseek", llm_model: "deepseek-chat" });
  api.getSettings.mockResolvedValue(settings);
  api.getAvatarStatus.mockResolvedValue({ enabled: false, protocol_version: 1, broadcast_policy: "", client_count: 0, clients: [], emotion_engine: { mapping_valid: true, current_emotion: "neutral", target_emotion: "neutral", intensity: 0, gesture: "", motion_profile: "", attack_ms: 0, minimum_hold_ms: 0, release_ms: 0, generation: 0, speaking: false } });
  api.getEvents.mockResolvedValue({ events: [] });
  api.getTimelineMessages.mockResolvedValue({ items: [], next_offset: null });
  api.resetConversationSession.mockResolvedValue({ session_id: "test-session", messages: 0, episodes: 0 });
  api.getConversationSession.mockResolvedValue({ session_id: "test-session", created: false });
  api.getModels.mockResolvedValue({ models: [] });
  api.getBackups.mockResolvedValue([]);
  api.getAvatarOverlay.mockResolvedValue({ visible: true, always_on_top: true, locked: true, scale: 1, monitor: "", x: 0, y: 0, width: 0, height: 0 });
  api.getPronunciations.mockResolvedValue({ pronunciations: {} });
  api.getSttTerms.mockResolvedValue({ terms: {} });
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
    expect(screen.getByRole("img", { name: "Iris" })).toBeInTheDocument();
    expect(container.querySelector("img.brand-logo")).toHaveAttribute("src", "/brand/iris-wordmark-light.svg");
    fireEvent.click(screen.getByRole("button", { name: "Диалог" }));
    expect(container.querySelector("main.workspace-chat")).toBeInTheDocument();
    expect(container.querySelector(".chat-panel .message-list")).toBeInTheDocument();
    expect(container.querySelector(".chat-panel .chat-composer")).toBeInTheDocument();
    expect(container.querySelector(".chat-composer textarea")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Свободные руки" })).toBeInTheDocument();
  });

  it("закрепляет встроенный аватар слева от чата и даёт переключить размещение", async () => {
    api.getSettings.mockResolvedValue({ ...settings, avatar_placement: "in_app" });
    const { container } = render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Диалог" }));
    expect(container.querySelector(".chat-panel.has-in-app-avatar .in-app-avatar-stage")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Настройки" }));
    fireEvent.click(await screen.findByRole("button", { name: "Система" }));
    fireEvent.click(screen.getByText("Аватар"));
    expect(screen.getByText("Где показывать аватар")).toBeInTheDocument();
    expect(screen.getByLabelText("Внутри Iris")).toBeChecked();
    expect(screen.getByLabelText("Отдельным оверлеем")).not.toBeChecked();
  });

  it("не связывает встроенный аватар со скрытым внешним оверлеем", async () => {
    api.getSettings.mockResolvedValue({ ...settings, avatar_placement: "in_app", avatar_in_app_visible: true });
    api.getAvatarOverlay.mockResolvedValue({ visible: false, always_on_top: true, locked: true, scale: 1, monitor: "", x: 0, y: 0, width: 0, height: 0 });
    const { container } = render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Диалог" }));
    expect(container.querySelector(".chat-panel.has-in-app-avatar .in-app-avatar-stage")).toBeInTheDocument();
  });

  it("восстанавливает активную сессию без сброса диалога при новом входе", async () => {
    render(<App />);

    await screen.findByRole("button", { name: "Диалог" });
    await waitFor(() => expect(api.getConversationSession).toHaveBeenCalledTimes(1));
    expect(api.resetConversationSession).not.toHaveBeenCalled();
  });

  it("сохраняет открытый чат при переходе между разделами", async () => {
    api.getTimelineMessages.mockResolvedValue({
      items: [{ id: "saved-message", role: "user", content: "Не теряй меня", metadata: {} }],
      next_offset: null,
    });
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Диалог" }));
    expect(await screen.findByText("Не теряй меня")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Обзор" }));
    fireEvent.click(screen.getByRole("button", { name: "Диалог" }));

    expect(screen.getByText("Не теряй меня")).toBeVisible();
    expect(api.getTimelineMessages).toHaveBeenCalledTimes(1);
  });

  it("открывает сохранённый диалог на последнем сообщении", async () => {
    api.getTimelineMessages.mockResolvedValue({
      items: [{ id: "last-message", role: "assistant", content: "Последнее сообщение", metadata: {} }],
      next_offset: null,
    });
    const { container } = render(<App />);

    await screen.findByText("Последнее сообщение");
    const list = container.querySelector<HTMLElement>(".chat-panel .message-list");
    expect(list).not.toBeNull();
    Object.defineProperty(list!, "scrollHeight", { configurable: true, value: 640 });
    fireEvent.click(screen.getByRole("button", { name: "Диалог" }));

    await waitFor(() => expect(HTMLElement.prototype.scrollTo).toHaveBeenCalledWith({
      top: 640,
      behavior: "auto",
    }));
  });

  it("открывает обзор с реальными данными и переводит к диалогу", async () => {
    api.getTimelineJournal.mockResolvedValue({
      items: [{ day: "2026-07-27", message_count: 8, started_at: "2026-07-27T10:00:00Z", last_activity_at: "2026-07-27T10:40:00Z", title: "Идеи интерфейса" }],
    });
    api.getMemories.mockResolvedValue({
      items: [
        { id: "m1", status: "active", predicate: "имя", value_text: "Роман", source_message_ids: [] },
      ],
    });

    render(<App />);

    expect(await screen.findByRole("heading", { name: "О чём поговорим?" })).toBeInTheDocument();
    expect(await screen.findByText("Идеи интерфейса")).toBeInTheDocument();
    expect(screen.getByText("Iris самостоятельно поддерживает актуальность фактов.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Начать диалог/ }));
    expect(screen.getByPlaceholderText("Напишите сообщение…")).toBeInTheDocument();
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

  it("не показывает ручное создание и очередь проверки", async () => {
    render(<MemoryPage />);
    await screen.findByText("Записей пока нет");

    expect(screen.queryByRole("button", { name: "Добавить запись" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "На проверке" })).not.toBeInTheDocument();
    expect(api.createMemory).not.toHaveBeenCalled();
  });

  it("переключает раздел памяти в таком же меню", async () => {
    render(<MemoryPage />);
    await screen.findByRole("button", { name: "Текущие" });

    fireEvent.click(screen.getByRole("button", { name: "Архив" }));

    await waitFor(() => expect(api.getMemories).toHaveBeenLastCalledWith(undefined, undefined));
  });

  it("скрывает заменённые записи из текущей памяти и объясняет архив", async () => {
    api.getMemories.mockResolvedValue({
      items: [
        {
          id: "active", status: "active", predicate: "name", slot_key: "user.name",
          value_text: "Федя", source_message_ids: ["source"], source_count: 1,
          access_count: 2, user_locked: false,
        },
        {
          id: "old", status: "superseded", predicate: "name", slot_key: "user.name",
          value_text: "Федор", source_message_ids: ["source"], source_count: 1,
          access_count: 3, user_locked: false,
          replacement: { id: "active", predicate: "name", value_text: "Федя", status: "active" },
        },
      ],
    });
    render(<MemoryPage />);

    expect(await screen.findByText("Федя")).toBeInTheDocument();
    expect(screen.queryByText("Федор")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Архив" }));

    expect(await screen.findByText("Федор")).toBeInTheDocument();
    expect(screen.getByText("Заменено на: Федя")).toBeInTheDocument();
    expect(screen.getByText("Имя пользователя")).toBeInTheDocument();
    expect(screen.getByText(/использовалось до замены: 3/)).toBeInTheDocument();
  });

  it("подтверждает сброс сессии и сохраняет память", async () => {
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Настройки" }));
    fireEvent.click(screen.getByRole("button", { name: "Живой разговор" }));
    fireEvent.click(await screen.findByRole("button", { name: "Сбросить сессию" }));
    expect(screen.getByRole("heading", { name: "Сбросить текущую сессию?" })).toBeInTheDocument();
    expect(screen.getByText(/Долгосрочная память Iris останется/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Сбросить сессию" })[1]);

    await waitFor(() => expect(api.resetConversationSession).toHaveBeenCalledTimes(1));
  });

  it("оставляет только историю и забывание записи", async () => {
    api.getMemories.mockResolvedValue({
      items: [{
        id: "memory-1", scope: "user", kind: "fact", subject: "user", predicate: "напиток",
        value_text: "Чай", importance: 0.8, confidence: 0.9, sensitivity: "normal",
        status: "active", user_locked: false, source_message_ids: [], created_at: "", updated_at: "",
        access_count: 1,
      }],
    });
    render(<MemoryPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Дополнительные действия" }));
    expect(screen.getByRole("button", { name: "История записи" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Забыть" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Изменить" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Закрепить" })).not.toBeInTheDocument();
    expect(api.updateMemory).not.toHaveBeenCalled();
  });

  it("подтверждает удаление истории во встроенном диалоге", async () => {
    api.getTimelineJournal.mockResolvedValue({
      items: [{ day: "2026-07-27", message_count: 4, started_at: "2026-07-27T10:00:00Z", last_activity_at: "2026-07-27T11:00:00Z" }],
    });
    api.deleteTimelineRange.mockResolvedValue({ deleted: 4 });
    render(<JournalPage />);

    fireEvent.click(await screen.findByRole("button", { name: /Удалить историю до/ }));
    expect(screen.getByRole("heading", { name: "Удалить часть истории?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Удалить историю" }));

    await waitFor(() => expect(api.deleteTimelineRange).toHaveBeenCalledWith("2026-07-27T23:59:59.999Z"));
  });
});
