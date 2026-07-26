import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  Brain,
  ChevronDown,
  CircleAlert,
  Database,
  History,
  Menu,
  MessageCircle,
  Mic,
  MonitorCog,
  RefreshCw,
  SendHorizontal,
  Settings,
  SlidersHorizontal,
  Volume2,
  Wifi,
  WifiOff,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import {
  getAvatarStatus,
  getAvatarOverlay,
  clearMemories,
  createBackup,
  getBackups,
  getEvents,
  getTimelineJournal,
  getTimelineMessages,
  getSettings,
  getStatus,
  getVoiceTtsStatus,
  getModels,
  getPronunciations,
  installModel,
  interruptVoiceSession,
  isDesktopManaged,
  removeModel,
  reindexMemories,
  resetAllCompanionData,
  resolveApiUrl,
  saveDesktopApiKey,
  sendChatMessage,
  sendLiveTextMessage,
  searchTimeline,
  deleteTimelineRange,
  sendVoiceMessage,
  updateRuntimeSettings,
  updatePronunciations,
  updateVoiceExpression,
  updateVoiceStyle,
  voiceWebSocketUrl,
  voiceInputWebSocketUrl,
  WS_EVENTS_URL,
  sendAvatarTestEmotion,
  sendAvatarTestGesture,
  sendAvatarTestPhrase,
  stopAvatar,
  updateAvatarOverlay,
} from "./api";
import type {
  BackendEvent,
  AvatarStatusResponse,
  AvatarOverlaySettings,
  ChatMessage,
  EventLevel,
  PublicSettings,
  ManagedModel,
  StatusResponse,
  TimelineJournalItem,
  TimelineMessage,
  VoiceChatResponse,
  VoiceTtsStatusResponse,
  MemoryUpdate,
} from "./types";
import type { VoiceServerEvent } from "./types";
import { PlaybackCoordinator, TTSStreamPlayer, VoiceSocketClient } from "./voice-live";
import { BrowserVadRecorder, PcmInputClient, type VadState } from "./vad";
import { JournalPage } from "./journal";
import { MemoryPage } from "./memory";

type AppView = "chat" | "journal" | "memory" | "settings";
type SettingsSection = "general" | "voice" | "memory" | "system";
type WsState = "connected" | "disconnected" | "reconnecting";
type LevelFilter = "all" | EventLevel;
type VoiceState = "idle" | "recording" | "transcribing" | "thinking" | "speaking" | "stopping" | "error";

const SESSION_ID = "default";
const AVATAR_EMOTION_LABELS: Record<string, string> = {
  neutral: "Нейтральная", happy: "Радость", sad: "Грусть", angry: "Злость",
  annoyed: "Раздражение", smirk: "Улыбка", thinking: "Задумчивость", surprised: "Удивление",
  embarrassed: "Смущение", concerned: "Обеспокоенность",
};
const AVATAR_GESTURE_LABELS: Record<string, string> = {
  greeting: "Приветствие", agreement: "Согласие", disagreement: "Несогласие", question: "Вопрос",
  explanation: "Объяснение", thinking: "Размышление", surprise: "Удивление", frustration: "Фрустрация",
  farewell: "Прощание", shrug: "Пожимание плечами", talk: "Разговор",
};

function formatPronunciations(entries: Record<string, string>): string {
  return Object.entries(entries)
    .sort(([left], [right]) => left.localeCompare(right, "ru"))
    .map(([term, pronunciation]) => `${term} = ${pronunciation}`)
    .join("\n");
}

function parsePronunciations(value: string): Record<string, string> {
  return Object.fromEntries(
    value.split("\n")
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#"))
      .map((line) => line.split(/\s*=\s*/, 2))
      .filter(([term, pronunciation]) => term && pronunciation),
  );
}
const RECORDING_MIME_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/ogg",
  "audio/mp4",
];

function getRecordingMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") {
    return undefined;
  }
  return RECORDING_MIME_TYPES.find((mimeType) => MediaRecorder.isTypeSupported(mimeType));
}

function dedupeEvents(events: BackendEvent[]): BackendEvent[] {
  const map = new Map<string, BackendEvent>();
  for (const event of events) {
    map.set(event.id, event);
  }
  return Array.from(map.values()).slice(-300);
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function boolLabel(value: boolean): string {
  return value ? "Да" : "Нет";
}

function personalityLabel(value: string): string {
  return value === "default" ? "Стандартный" : value;
}

function isLiveVoiceTransportError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  return (
    error.message.includes("Live voice connection failed") ||
    error.message.includes("Voice WebSocket must be connected") ||
    error.message.includes("Live text requires backend TTS")
  );
}

export default function App() {
  const [activeView, setActiveView] = useState<AppView>("chat");
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [avatarStatus, setAvatarStatus] = useState<AvatarStatusResponse | null>(null);
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [events, setEvents] = useState<BackendEvent[]>([]);
  const [wsState, setWsState] = useState<WsState>("disconnected");
  const [statusError, setStatusError] = useState<string | null>(null);
  const setupRequired = Boolean(settings && !settings.api_key_configured && isDesktopManaged());

  const refreshEvents = useCallback(async () => {
    const payload = await getEvents(100);
    setEvents((current) => dedupeEvents([...current, ...payload.events]));
  }, []);

  const refreshOverview = useCallback(async () => {
    try {
      const [nextStatus, nextSettings] = await Promise.all([
        getStatus(),
        getSettings(),
      ]);
      setStatus(nextStatus);
      setSettings(nextSettings);
      try {
        setAvatarStatus(await getAvatarStatus());
      } catch {
        setAvatarStatus(null);
      }
      setStatusError(null);
    } catch (error) {
      setStatusError(error instanceof Error ? error.message : "Сервис недоступен");
    }
  }, []);

  useEffect(() => {
    void refreshOverview();
    void refreshEvents();
    const timer = window.setInterval(() => {
      void refreshOverview();
    }, 10000);
    return () => window.clearInterval(timer);
  }, [refreshEvents, refreshOverview]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let reconnectTimer = 0;
    let closed = false;

    const connect = () => {
      setWsState((current) =>
        current === "disconnected" ? "reconnecting" : current,
      );
      socket = new WebSocket(WS_EVENTS_URL);

      socket.onopen = () => {
        setWsState("connected");
        void refreshEvents();
      };

      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as BackendEvent;
          setEvents((current) => dedupeEvents([...current, event]));
        } catch {
          // Ignore malformed event frames.
        }
      };

      socket.onclose = () => {
        if (closed) {
          return;
        }
        setWsState("reconnecting");
        reconnectTimer = window.setTimeout(connect, 2000);
      };

      socket.onerror = () => {
        socket?.close();
      };
    };

    connect();

    return () => {
      closed = true;
      window.clearTimeout(reconnectTimer);
      socket?.close();
      setWsState("disconnected");
    };
  }, [refreshEvents]);

  if (setupRequired) {
    return <div className="app-shell setup-shell"><SetupWizard onComplete={refreshOverview} /></div>;
  }

  const switchView = (view: AppView) => {
    setActiveView(view);
    setNavigationOpen(false);
  };

  return (
    <div className="app-shell">
      <Sidebar
        activeView={activeView}
        isOpen={navigationOpen}
        onNavigate={switchView}
        onClose={() => setNavigationOpen(false)}
      />
      {navigationOpen && <button className="navigation-scrim" aria-label="Закрыть меню" onClick={() => setNavigationOpen(false)} />}
      <section className="app-content">
        <Header
          status={status}
          wsState={wsState}
          statusError={statusError}
          onOpenNavigation={() => setNavigationOpen(true)}
        />
        <main className={`workspace workspace-${activeView}`}>
          {activeView === "chat" && (
            <ChatPage
              events={events}
              settings={settings}
              avatarStatus={avatarStatus}
              onRefreshEvents={refreshEvents}
              onOpenMemory={() => switchView("memory")}
            />
          )}
          {activeView === "journal" && <JournalPage />}
          {activeView === "memory" && <MemoryPage />}
          {activeView === "settings" && (
            <SettingsPage
              settings={settings}
              avatarStatus={avatarStatus}
              events={events}
              onRefreshEvents={refreshEvents}
              onRefreshAvatar={refreshOverview}
              onSettingsChanged={(nextSettings) => {
                setSettings(nextSettings);
                void refreshOverview();
                void refreshEvents();
              }}
            />
          )}
        </main>
      </section>
    </div>
  );
}

function SetupWizard({ onComplete }: { onComplete: () => Promise<void> }) {
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      await saveDesktopApiKey(apiKey);
      setApiKey("");
      await onComplete();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось сохранить ключ API.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="setup-workspace">
      <section className="setup-card" aria-labelledby="setup-title">
        <span className="eyebrow">ПЕРВИЧНАЯ НАСТРОЙКА</span>
        <h1 id="setup-title">Подключите Iris</h1>
        <p>Введите ключ DeepSeek один раз. Он хранится в диспетчере учётных данных Windows, а не в файлах проекта.</p>
        <form className="setup-form" onSubmit={submit}>
          <label>
            Ключ API DeepSeek
            <input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="sk-…" required />
          </label>
          <button className="primary-button" type="submit" disabled={busy || !apiKey.trim()}>{busy ? "Подключаем…" : "Продолжить"}</button>
        </form>
        <p className="setup-hint">Настройки голоса и моделей можно изменить позже в разделе «Настройки».</p>
        {message && <div className="notice" role="status">{message}</div>}
      </section>
    </main>
  );
}

const MAIN_NAVIGATION: Array<{ id: Exclude<AppView, "settings">; label: string; icon: LucideIcon }> = [
  { id: "chat", label: "Диалог", icon: MessageCircle },
  { id: "journal", label: "История", icon: History },
  { id: "memory", label: "Память", icon: Brain },
];

function Sidebar({
  activeView,
  isOpen,
  onNavigate,
  onClose,
}: {
  activeView: AppView;
  isOpen: boolean;
  onNavigate: (view: AppView) => void;
  onClose: () => void;
}) {
  return (
    <aside className={`sidebar${isOpen ? " is-open" : ""}`} aria-label="Основная навигация">
      <div className="sidebar-brand">
        <img className="brand-logo" src="/brand/iris-wordmark-light.svg" alt="Iris" />
        <button className="icon-button sidebar-close" aria-label="Закрыть меню" title="Закрыть меню" onClick={onClose}><X size={18} /></button>
      </div>
      <nav className="sidebar-nav" aria-label="Разделы приложения">
        {MAIN_NAVIGATION.map(({ id, label, icon: Icon }) => (
          <NavigationButton key={id} icon={Icon} label={label} active={activeView === id} onClick={() => onNavigate(id)} />
        ))}
      </nav>
      <div className="sidebar-footer">
        <NavigationButton icon={Settings} label="Настройки" active={activeView === "settings"} onClick={() => onNavigate("settings")} />
      </div>
    </aside>
  );
}

function NavigationButton({
  icon: Icon,
  label,
  active,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button className={`navigation-button${active ? " is-active" : ""}`} aria-current={active ? "page" : undefined} onClick={onClick}>
      <Icon size={19} aria-hidden="true" />
      <span>{label}</span>
    </button>
  );
}

function Header({
  status,
  wsState,
  statusError,
  onOpenNavigation,
}: {
  status: StatusResponse | null;
  wsState: WsState;
  statusError: string | null;
  onOpenNavigation: () => void;
}) {
  const backendOk = status?.backend === "ok" && !statusError;
  const connected = backendOk && wsState === "connected";
  const pending = backendOk && !connected;

  return (
    <header className="topbar">
      <button className="icon-button menu-toggle" aria-label="Открыть меню" title="Открыть меню" onClick={onOpenNavigation}><Menu size={20} /></button>
      <StatusPill label={connected ? "Подключено" : pending ? "Подключаемся" : "Нет подключения"} state={connected ? "ok" : pending ? "warn" : "bad"} />
    </header>
  );
}

function StatusPill({
  label,
  state,
}: {
  label: string;
  state: "ok" | "warn" | "bad";
}) {
  return (
    <span className={`status-pill ${state}`}>
      {state === "bad" ? <WifiOff size={15} aria-hidden="true" /> : <Wifi size={15} aria-hidden="true" />}
      {label}
    </span>
  );
}

function ChatPage({
  events,
  settings,
  avatarStatus,
  onRefreshEvents,
  onOpenMemory,
}: {
  events: BackendEvent[];
  settings: PublicSettings | null;
  avatarStatus: AvatarStatusResponse | null;
  onRefreshEvents: () => Promise<void>;
  onOpenMemory: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [retryText, setRetryText] = useState<string | null>(null);
  const [memoryNotice, setMemoryNotice] = useState<string | null>(null);
  const [handsFree, setHandsFree] = useState(false);
  const [vadState, setVadState] = useState<VadState>("idle");
  const listRef = useRef<HTMLDivElement | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const recordTimeoutRef = useRef<number | null>(null);
  const handledVoiceEventIdsRef = useRef<Set<string>>(new Set());
  const activeAudioRef = useRef<HTMLAudioElement | null>(null);
  const liveSocketRef = useRef<VoiceSocketClient | null>(null);
  const livePlayerRef = useRef<TTSStreamPlayer | null>(null);
  const vadRecorderRef = useRef<BrowserVadRecorder | null>(null);
  const pcmInputRef = useRef<PcmInputClient | null>(null);
  const submitVoiceRef = useRef<(audio: Blob, endedAt?: number) => void>(() => undefined);
  const playbackCoordinatorRef = useRef(new PlaybackCoordinator());
  const avatarOwnsAudioRef = useRef(false);
  const liveAudioStartedRef = useRef(false);
  const liveMetadataRef = useRef({ emotion: "neutral", intent: "unknown" });

  const showMemoryUpdates = useCallback((updates?: MemoryUpdate[]) => {
    const update = updates && updates.length ? updates[updates.length - 1] : undefined;
    if (!update) return;
    setMemoryNotice(update.action === "saved"
      ? `Сохранено в памяти: ${update.predicate}.`
      : "Новая запись готова к проверке в разделе «Память».");
  }, []);

  useEffect(() => {
    void getTimelineMessages().then((payload) => {
      setMessages(payload.items
        .filter((message) => message.role === "user" || message.role === "assistant")
        .map((message) => ({ id: message.id, role: message.role as "user" | "assistant", content: message.content })));
    }).catch(() => {
      // The V0.4 compatibility backend may intentionally keep Timeline V2 disabled.
    });
  }, []);

  const voiceSupported =
    typeof navigator !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia) &&
    typeof MediaRecorder !== "undefined";
  const handsFreeSupported =
    typeof navigator !== "undefined"
    && Boolean(navigator.mediaDevices?.getUserMedia)
    && typeof AudioWorkletNode !== "undefined";
  const browserSpeechSupported =
    typeof window !== "undefined" &&
    "speechSynthesis" in window &&
    "SpeechSynthesisUtterance" in window;
  const avatarOwnsAudio = Boolean(avatarStatus?.enabled && avatarStatus.client_count > 0);

  useEffect(() => {
    avatarOwnsAudioRef.current = avatarOwnsAudio;
  }, [avatarOwnsAudio]);

  const stopVoicePlayback = useCallback((except?: HTMLAudioElement) => {
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }

    const activeAudio = activeAudioRef.current;
    if (activeAudio && activeAudio !== except) {
      activeAudio.pause();
      activeAudio.currentTime = 0;
    }
    activeAudioRef.current = except ?? null;
  }, []);

  const interruptAssistantSpeech = useCallback(() => {
    const socket = liveSocketRef.current;
    const utteranceId = socket?.activeUtteranceId ?? undefined;
    // Local audio must stop before waiting for either WebSocket or REST I/O.
    stopVoicePlayback();
    livePlayerRef.current?.stop();
    const sentOverLiveSocket = socket?.cancel() ?? false;
    socket?.clearActive();
    playbackCoordinatorRef.current.cancel();
    setLoading(false);
    // A live socket normally carries the cancellation.  REST covers a batch
    // fallback (or a temporarily disconnected socket), including Unity audio.
    if (!sentOverLiveSocket) {
      void interruptVoiceSession(SESSION_ID, utteranceId).catch(() => undefined);
    }
  }, [stopVoicePlayback]);

  const playAudioUrl = useCallback(
    async (audioUrl: string): Promise<boolean> => {
      stopVoicePlayback();
      const audio = new Audio(audioUrl);
      audio.playbackRate = settings?.voice_playback_rate ?? 1;
      activeAudioRef.current = audio;
      audio.onended = () => {
        if (activeAudioRef.current === audio) {
          activeAudioRef.current = null;
        }
      };
      audio.onerror = () => {
        if (activeAudioRef.current === audio) {
          activeAudioRef.current = null;
        }
      };

      try {
        await audio.play();
        return true;
      } catch {
        if (activeAudioRef.current === audio) {
          activeAudioRef.current = null;
        }
        return false;
      }
    },
    [settings?.voice_playback_rate, stopVoicePlayback],
  );

  const playMessageAudioTrack = useCallback(
    async (messageId: string, fallbackAudioUrl: string): Promise<boolean> => {
      const audio =
        document.querySelector<HTMLAudioElement>(
          `audio[data-message-id="${CSS.escape(messageId)}"]`,
        ) ?? new Audio(fallbackAudioUrl);

      stopVoicePlayback(audio);
      audio.playbackRate = settings?.voice_playback_rate ?? 1;
      activeAudioRef.current = audio;
      audio.onended = () => {
        if (activeAudioRef.current === audio) {
          activeAudioRef.current = null;
        }
      };

      try {
        audio.currentTime = 0;
        await audio.play();
        return true;
      } catch {
        if (activeAudioRef.current === audio) {
          activeAudioRef.current = null;
        }
        return false;
      }
    },
    [settings?.voice_playback_rate, stopVoicePlayback],
  );

  const speakTextInBrowser = useCallback(
    (text: string): boolean => {
      if (!browserSpeechSupported) {
        return false;
      }
      stopVoicePlayback();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = settings?.voice_language === "en" ? "en-US" : "ru-RU";
      utterance.rate = settings?.voice_playback_rate ?? 1;
      window.speechSynthesis.speak(utterance);
      return true;
    },
    [browserSpeechSupported, settings?.voice_language, settings?.voice_playback_rate, stopVoicePlayback],
  );

  const ensureLivePlayer = useCallback(() => {
    if (!livePlayerRef.current) {
      livePlayerRef.current = new TTSStreamPlayer(
        () => {
          liveAudioStartedRef.current = true;
          liveSocketRef.current?.send("playback.started");
          setVoiceState("speaking");
        },
        () => {
          liveSocketRef.current?.send("playback.finished");
          playbackCoordinatorRef.current.release(playbackCoordinatorRef.current.snapshot());
          liveSocketRef.current?.clearActive();
          setLoading(false);
          setVoiceState("idle");
        },
        (playerError) => {
          livePlayerRef.current?.stop();
          playbackCoordinatorRef.current.cancel();
          liveSocketRef.current?.cancel();
          setError(`Не удалось воспроизвести ответ: ${playerError.message}`);
          setLoading(false);
          setVoiceState("error");
        },
        {
          prebufferSegments: settings?.voice_live_playback_prebuffer_segments ?? 1,
          prebufferMs: settings?.voice_live_playback_prebuffer_ms ?? 0,
          playbackRate: settings?.voice_playback_rate ?? 1,
        },
        (gapMs) => {
          liveSocketRef.current?.send("playback.underrun", { underrun_ms: gapMs });
        },
      );
    }
    livePlayerRef.current.updateOptions({
      prebufferSegments: settings?.voice_live_playback_prebuffer_segments ?? 1,
      prebufferMs: settings?.voice_live_playback_prebuffer_ms ?? 0,
      playbackRate: settings?.voice_playback_rate ?? 1,
    });
    return livePlayerRef.current;
  }, [
    settings?.voice_live_playback_prebuffer_ms,
    settings?.voice_live_playback_prebuffer_segments,
    settings?.voice_playback_rate,
  ]);

  const ensureLiveVoice = useCallback(async () => {
    const player = ensureLivePlayer();
    if (!liveSocketRef.current) {
      const onEvent = (event: VoiceServerEvent) => {
        if (event.type === "voice.utterance.started") {
          playbackCoordinatorRef.current.acquire(
            avatarOwnsAudioRef.current ? "unity" : "desktop_ui",
            event.utterance_id,
          );
          liveSocketRef.current?.activate(event.utterance_id);
          livePlayerRef.current?.begin(event.utterance_id);
          setVoiceState("thinking");
        } else if (event.type === "voice.metadata") {
          liveMetadataRef.current = {
            emotion: event.emotion ?? "neutral",
            intent: event.intent ?? "unknown",
          };
          setMessages((current) => current.map((message) =>
            message.utteranceId === event.utterance_id
              ? { ...message, emotion: event.emotion, intent: event.intent }
              : message,
          ));
        } else if (event.type === "voice.text.delta" && event.delta) {
          setMessages((current) => {
            const index = current.findIndex((message) => message.utteranceId === event.utterance_id);
            if (index < 0) {
              return [...current, {
                id: crypto.randomUUID(), role: "assistant", content: event.delta!,
                utteranceId: event.utterance_id,
                emotion: liveMetadataRef.current.emotion,
                intent: liveMetadataRef.current.intent,
              }];
            }
            return current.map((message, messageIndex) => messageIndex === index
              ? { ...message, content: message.content + event.delta }
              : message);
          });
        } else if (event.type === "voice.text.completed") {
          showMemoryUpdates(event.memory_updates);
        } else if (event.type === "tts.segment.started") {
          setVoiceState("speaking");
        } else if (event.type === "voice.utterance.finished") {
          if (avatarOwnsAudioRef.current) {
            playbackCoordinatorRef.current.release(playbackCoordinatorRef.current.snapshot());
            liveSocketRef.current?.clearActive();
            setLoading(false);
            setVoiceState("idle");
          } else {
            livePlayerRef.current?.finish(event.utterance_id);
          }
        } else if (event.type === "voice.utterance.cancelled") {
          livePlayerRef.current?.stop();
          stopVoicePlayback();
          playbackCoordinatorRef.current.cancel();
          liveSocketRef.current?.clearActive();
          setLoading(false);
          setVoiceState("idle");
        } else if (event.type === "voice.error") {
          livePlayerRef.current?.stop();
          playbackCoordinatorRef.current.cancel();
          liveSocketRef.current?.clearActive();
          setError(event.message ?? event.code ?? "Не удалось выполнить голосовой запрос");
          setLoading(false);
          setVoiceState("error");
          if (!liveAudioStartedRef.current) {
            setMessages((current) => {
              const message = current.find((item) => item.utteranceId === event.utterance_id);
              if (message) speakTextInBrowser(message.content);
              return current;
            });
          }
        }
      };
      liveSocketRef.current = new VoiceSocketClient(
        voiceWebSocketUrl(SESSION_ID),
        onEvent,
        (audio, segment) => {
          if (
            segment.segment_id !== undefined
            && playbackCoordinatorRef.current.isOwner("desktop_ui", segment.utterance_id)
          ) {
            void livePlayerRef.current?.enqueue(
              segment.utterance_id, segment.segment_id, audio, segment,
            ).catch(() => undefined);
          }
        },
      );
    }
    await player.unlock();
    await liveSocketRef.current.connect();
  }, [ensureLivePlayer, showMemoryUpdates, speakTextInBrowser, stopVoicePlayback]);

  useEffect(() => () => {
    livePlayerRef.current?.stop();
    liveSocketRef.current?.close();
    vadRecorderRef.current?.stop();
    pcmInputRef.current?.close();
  }, []);

  useEffect(() => () => stopVoicePlayback(), [stopVoicePlayback]);

  const applyTtsStatus = useCallback((status: VoiceTtsStatusResponse) => {
    setMessages((current) =>
      current.map((message) => {
        if (message.voiceRequestId !== status.voice_request_id) {
          return message;
        }

        if (status.status === "ready" && status.audio_url) {
          return {
            ...message,
            audioUrl: resolveApiUrl(status.audio_url),
            ttsStatus: "ready",
            ttsError: undefined,
          };
        }

        if (status.status === "failed") {
          return {
            ...message,
            ttsStatus: "failed",
            ttsError: browserSpeechSupported
              ? undefined
              : "TTS failed; no browser speech support",
          };
        }

        return {
          ...message,
          ttsStatus: status.status,
          ttsError:
            status.status === "queued" ? "Аудио ещё создаётся" : message.ttsError,
        };
      }),
    );
  }, [browserSpeechSupported]);

  const syncVoiceTtsStatus = useCallback(
    async (voiceRequestId: string): Promise<VoiceTtsStatusResponse | null> => {
      try {
        const status = await getVoiceTtsStatus(voiceRequestId);
        applyTtsStatus(status);
        return status;
      } catch (statusError) {
        setMessages((current) =>
          current.map((message) =>
            message.voiceRequestId === voiceRequestId
              ? {
                  ...message,
                  ttsError:
                    statusError instanceof Error
                      ? statusError.message
                      : "Не удалось проверить статус аудио",
                }
              : message,
          ),
        );
        return null;
      }
    },
    [applyTtsStatus],
  );

  const pollVoiceTtsStatus = useCallback(
    async (voiceRequestId: string) => {
      const started = Date.now();
      while (Date.now() - started < 30000) {
        const status = await syncVoiceTtsStatus(voiceRequestId);
        if (status?.status === "ready" || status?.status === "failed") {
          return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 500));
      }
    },
    [syncVoiceTtsStatus],
  );

  const appendBatchVoiceResponse = useCallback(
    (response: VoiceChatResponse) => {
      showMemoryUpdates(response.memory_updates);
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "user",
          content: response.transcript,
        },
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: response.reply,
          emotion: response.emotion,
          intent: response.intent,
          voiceRequestId: response.voice_request_id,
          ttsStatus: response.tts_status,
          audioUrl: response.reply_audio_url
            ? resolveApiUrl(response.reply_audio_url)
            : undefined,
        },
      ]);
      if (response.tts_status === "queued") {
        void pollVoiceTtsStatus(response.voice_request_id);
      }
    },
    [pollVoiceTtsStatus, showMemoryUpdates],
  );

  useEffect(() => {
    listRef.current?.scrollTo({
      top: listRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  useEffect(() => {
    for (const event of events) {
      if (handledVoiceEventIdsRef.current.has(event.id)) {
        continue;
      }
      if (event.type !== "voice.tts_ready" && event.type !== "voice.tts_failed") {
        continue;
      }
      handledVoiceEventIdsRef.current.add(event.id);

      const voiceRequestId = getStringMetadata(event, "voice_request_id");
      if (!voiceRequestId) {
        continue;
      }

      if (event.type === "voice.tts_ready") {
        const audioUrl = getStringMetadata(event, "audio_url");
        if (!audioUrl) {
          continue;
        }
        const resolvedAudioUrl = resolveApiUrl(audioUrl);
        setMessages((current) =>
          current.map((message) =>
            message.voiceRequestId === voiceRequestId
              ? {
                  ...message,
                  audioUrl: resolvedAudioUrl,
                  ttsStatus: "ready",
                  ttsError: undefined,
                }
              : message,
          ),
        );
        if (!avatarOwnsAudio) {
          void playAudioUrl(resolvedAudioUrl);
        }
      } else {
        const fallbackMessage = messages.find(
          (message) => message.voiceRequestId === voiceRequestId,
        );
        const fallbackAlreadyStarted = fallbackMessage?.ttsStatus === "browser_fallback";
        const fallbackStarted = browserSpeechSupported && fallbackAlreadyStarted
          ? true
          : browserSpeechSupported && fallbackMessage
            ? speakTextInBrowser(fallbackMessage.content)
            : false;
        setMessages((current) =>
          current.map((message) =>
            message.voiceRequestId === voiceRequestId
              ? {
                  ...message,
                  ttsStatus: fallbackStarted ? "browser_fallback" : "failed",
                  ttsError: fallbackStarted
                    ? undefined
                    : "Не удалось синтезировать голос",
                }
              : message,
          ),
        );
      }
    }
  }, [avatarOwnsAudio, browserSpeechSupported, events, messages, playAudioUrl, speakTextInBrowser]);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || loading) {
      return;
    }

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
    };
    setMessages((current) => [...current, userMessage]);
    setDraft("");
    setLoading(true);
    setError(null);
    setRetryText(null);

    try {
      try {
        await ensureLiveVoice();
        liveSocketRef.current?.clearActive();
        liveAudioStartedRef.current = false;
        const response = await sendLiveTextMessage(SESSION_ID, text);
        liveSocketRef.current?.activate(response.utterance_id);
        setVoiceState("thinking");
        return;
      } catch (liveError) {
        if (!isLiveVoiceTransportError(liveError)) {
          throw liveError;
        }
        liveSocketRef.current?.close();
        liveSocketRef.current = null;
        setError("Потоковый режим недоступен: использован обычный ответ.");
      }
      const response = await sendChatMessage(SESSION_ID, text);
      showMemoryUpdates(response.memory_updates);
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: response.reply,
          emotion: response.emotion,
          intent: response.intent,
          voiceRequestId: response.voice_request_id ?? undefined,
          ttsStatus: response.tts_status ?? undefined,
        },
      ]);
      if (response.voice_request_id && response.tts_status === "queued") {
        void pollVoiceTtsStatus(response.voice_request_id);
      }
      await onRefreshEvents();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Не удалось отправить сообщение");
      setRetryText(text);
      setMessages((current) => current.filter((message) => message.id !== userMessage.id));
    } finally {
      if (!liveSocketRef.current?.activeUtteranceId) {
        setLoading(false);
        setVoiceState("idle");
      }
    }
  };

  const startRecording = async (bargeIn = false) => {
    if (!voiceSupported || (!bargeIn && (loading || voiceState !== "idle"))) {
      return;
    }

    if (bargeIn) {
      interruptAssistantSpeech();
    }
    setError(null);
    try {
      await ensureLivePlayer().unlock();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = getRecordingMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onstop = () => {
        if (recordTimeoutRef.current !== null) {
          window.clearTimeout(recordTimeoutRef.current);
          recordTimeoutRef.current = null;
        }
        stream.getTracks().forEach((track) => track.stop());
        const audio = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        chunksRef.current = [];
        void submitVoice(audio, Date.now());
      };

      recorderRef.current = recorder;
      recorder.start();
      recordTimeoutRef.current = window.setTimeout(() => {
        stopRecording();
      }, 60000);
      setVoiceState("recording");
    } catch (recordError) {
      setError(
        recordError instanceof Error ? recordError.message : "Микрофон недоступен",
      );
      setVoiceState("idle");
    }
  };

  const stopRecording = () => {
    if (recorderRef.current?.state === "recording") {
      recorderRef.current.stop();
      setVoiceState("transcribing");
    }
  };

  const toggleRecording = async () => {
    if (voiceState === "recording") {
      stopRecording();
      return;
    }
    // The avatar can still be speaking after the browser has released its
    // local playback lease.  Treat every new push-to-talk recording as a
    // barge-in instead of relying on UI state to detect that case.
    await startRecording(true);
  };

  const submitVoice = async (audio: Blob, endOfSpeechUnixMs?: number) => {
    if (audio.size === 0) {
      setError("Запись пуста");
      setVoiceState("idle");
      return;
    }
    if (audio.size < 800) {
      setError("Запись слишком короткая");
      setVoiceState("idle");
      return;
    }

    setLoading(true);
    setVoiceState("transcribing");
    setError(null);
    const thinkingTimer = window.setTimeout(() => {
      setVoiceState("thinking");
    }, 500);
    try {
      let response;
      try {
        await ensureLiveVoice();
        liveSocketRef.current?.clearActive();
        liveAudioStartedRef.current = false;
        response = await sendVoiceMessage(
          SESSION_ID,
          audio,
          settings?.voice_language ?? "ru",
          true,
          endOfSpeechUnixMs,
        );
      } catch (liveError) {
        if (!isLiveVoiceTransportError(liveError)) {
          throw liveError;
        }
        liveSocketRef.current?.close();
        liveSocketRef.current = null;
        response = await sendVoiceMessage(
          SESSION_ID,
          audio,
          settings?.voice_language ?? "ru",
          false,
          endOfSpeechUnixMs,
        );
      setError("Потоковый голосовой режим недоступен: использован обычный ответ.");
      }
      if ("status" in response) {
        liveSocketRef.current?.activate(response.utterance_id);
        setMessages((current) => [
          ...current,
          {
            id: crypto.randomUUID(),
            role: "user",
            content: response.transcript,
          },
        ]);
        setVoiceState("thinking");
        return;
      }
      appendBatchVoiceResponse(response);
      await onRefreshEvents();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Не удалось отправить голосовое сообщение");
    } finally {
      window.clearTimeout(thinkingTimer);
      if (!liveSocketRef.current?.activeUtteranceId) {
        setLoading(false);
        setVoiceState("idle");
      }
    }
  };

  useEffect(() => {
    submitVoiceRef.current = (audio: Blob, endedAt?: number) => { void submitVoice(audio, endedAt); };
  }, [submitVoice]);

  const toggleHandsFree = async () => {
    if (handsFree) {
      vadRecorderRef.current?.stop();
      pcmInputRef.current?.close();
      pcmInputRef.current = null;
      vadRecorderRef.current = null;
      setHandsFree(false);
      setVadState("idle");
      return;
    }
    try {
      await ensureLiveVoice();
      const input = new PcmInputClient(voiceInputWebSocketUrl(SESSION_ID), (event) => {
        if (event.type === "voice.input.transcript" && event.transcript) {
          setMessages((current) => [...current, { id: crypto.randomUUID(), role: "user", content: event.transcript! }]);
          setVoiceState("thinking");
        } else if (event.type === "voice.input.error") {
          setError(event.message ?? "Не удалось обработать голосовой ввод");
        }
      });
      await input.connect(16000, settings?.voice_language ?? "ru");
      pcmInputRef.current = input;
      const recorder = new BrowserVadRecorder();
      vadRecorderRef.current = recorder;
      await recorder.start(
        (pcm16) => pcmInputRef.current?.sendPcm(pcm16),
        (nextState, event) => {
          setVadState(nextState);
          if (event === "speech_started") {
            interruptAssistantSpeech();
          }
        },
      );
      setHandsFree(true);
    } catch (vadError) {
      vadRecorderRef.current?.stop();
      vadRecorderRef.current = null;
      setError(vadError instanceof Error ? vadError.message : "Режим свободных рук недоступен");
      setHandsFree(false);
      setVadState("idle");
    }
  };

  return (
    <section className="panel chat-panel">
      {memoryNotice && <div className="notice" role="status">{memoryNotice}<button className="text-button" onClick={onOpenMemory}>Открыть память</button></div>}
      <div className="message-list" ref={listRef}>
        {messages.length === 0 && (
          <div className="empty-state">
            <MessageCircle size={28} aria-hidden="true" />
            <strong>Начните разговор</strong>
            <span>Напишите сообщение или запишите голосовое.</span>
          </div>
        )}
        {messages.map((message) => (
          <article className={`message ${message.role}`} key={message.id}>
            <div className="message-role">{message.role === "user" ? "Вы" : "Iris"}</div>
            <p>{message.content}</p>
            {message.ttsError && <div className="message-error">{message.ttsError}</div>}
            {message.audioUrl && (
              <audio
                className="reply-audio"
                controls
                data-message-id={message.id}
                onPlay={(event) => {
                  event.currentTarget.playbackRate = settings?.voice_playback_rate ?? 1;
                  stopVoicePlayback(event.currentTarget);
                }}
                src={message.audioUrl}
              />
            )}
            {message.role === "assistant" && (
              <button
                className="speak-button"
                disabled={!message.audioUrl && !message.voiceRequestId && !browserSpeechSupported}
                onClick={async () => {
                  if (message.audioUrl) {
                    const played = await playMessageAudioTrack(message.id, message.audioUrl);
                    if (!played) {
                      setMessages((current) =>
                        current.map((currentMessage) =>
                          currentMessage.id === message.id
                            ? {
                                ...currentMessage,
                                ttsError: "Не удалось начать воспроизведение аудио",
                              }
                            : currentMessage,
                        ),
                      );
                    }
                    return;
                  }
                  if (message.voiceRequestId) {
                    const status = await syncVoiceTtsStatus(message.voiceRequestId);
                    if (status?.status === "ready" && status.audio_url) {
                      const resolvedAudioUrl = resolveApiUrl(status.audio_url);
                      window.setTimeout(() => {
                        void playMessageAudioTrack(message.id, resolvedAudioUrl);
                      }, 50);
                    }
                    return;
                  }
                  if (!speakTextInBrowser(message.content)) {
                    setMessages((current) =>
                      current.map((currentMessage) =>
                        currentMessage.id === message.id
                          ? {
                              ...currentMessage,
                              ttsError: "Аудио ещё не готово",
                            }
                          : currentMessage,
                      ),
                    );
                  }
                }}
                type="button"
              >
                {message.audioUrl || message.voiceRequestId || browserSpeechSupported
                  ? "Озвучить"
                  : "Аудио готовится"}
              </button>
            )}
          </article>
        ))}
        {loading && <div className="assistant-thinking" role="status"><span aria-hidden="true" /><span aria-hidden="true" /><span aria-hidden="true" />Iris печатает</div>}
      </div>

      {error && <div className="error-banner" role="alert"><CircleAlert size={18} aria-hidden="true" />{error}{retryText && <button className="text-button" type="button" onClick={() => { setDraft(retryText); setRetryText(null); }}>Повторить</button>}</div>}

      <div className="chat-composer">
        <form className="chat-form" onSubmit={onSubmit}>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Напишите сообщение…"
            rows={2}
          />
          <button
            className="primary-button send-button"
            type="submit"
            disabled={loading || draft.trim().length === 0}
            aria-label={loading ? "Отправка сообщения" : "Отправить сообщение"}
            title={loading ? "Отправка сообщения" : "Отправить сообщение"}
          >
            <SendHorizontal size={18} aria-hidden="true" />
          </button>
        </form>

        <div className="voice-controls">
          <button
            className={`voice-button${voiceState === "recording" ? " recording" : ""}`}
            disabled={!voiceSupported || voiceState === "transcribing" || voiceState === "stopping"}
            onClick={() => void toggleRecording()}
            type="button"
          >
            <Mic size={18} aria-hidden="true" />
            {voiceButtonLabel(voiceState)}
          </button>
          <button
            className={handsFree ? "voice-button recording" : "secondary voice-button"}
            disabled={!handsFreeSupported || voiceState === "transcribing"}
            onClick={() => void toggleHandsFree()}
            type="button"
          >
            {handsFree ? "Свободные руки: вкл." : "Свободные руки"}
          </button>
          {(handsFree || voiceState !== "idle" || !voiceSupported) && <span>
            {voiceSupported
              ? `Голос: ${settings?.voice_language === "en" ? "английский" : "русский"}${handsFree ? ` · ${vadState}` : ""}`
              : "Голосовой ввод недоступен"}
          </span>}
        </div>
      </div>
    </section>
  );
}

function voiceButtonLabel(voiceState: VoiceState): string {
  if (voiceState === "recording") {
    return "Остановить и отправить";
  }
  if (voiceState === "transcribing") {
    return "Распознаём речь";
  }
  if (voiceState === "thinking") {
    return "Перебить и говорить";
  }
  if (voiceState === "speaking") {
    return "Перебить и говорить";
  }
  if (voiceState === "stopping") {
    return "Останавливаем";
  }
  if (voiceState === "error") {
    return "Попробовать снова";
  }
  return "Голосовое сообщение";
}

function getStringMetadata(event: BackendEvent, key: string): string | null {
  const value = event.metadata[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function EventsPage({
  events,
  onRefreshEvents,
  compact = false,
}: {
  events: BackendEvent[];
  onRefreshEvents: () => Promise<void>;
  compact?: boolean;
}) {
  const [levelFilter, setLevelFilter] = useState<LevelFilter>("all");
  const filteredEvents = useMemo(
    () =>
      levelFilter === "all"
        ? events
        : events.filter((event) => event.level === levelFilter),
    [events, levelFilter],
  );

  return (
    <section className="panel events-panel">
      {compact ? <div className="events-toolbar"><button className="icon-button" onClick={() => void onRefreshEvents()} aria-label="Обновить журнал событий" title="Обновить журнал событий">
          <RefreshCw size={16} />
        </button></div> : <div className="panel-header">
        <div><h2>Журнал системы</h2><span>Технические события и диагностика</span></div>
        <button className="secondary" onClick={() => void onRefreshEvents()}>
          <RefreshCw size={16} aria-hidden="true" />
          Обновить
        </button>
      </div>}

      <div className="filters">
        {(["all", "info", "warning", "error", "critical"] as LevelFilter[]).map(
          (level) => {
            const labels: Record<LevelFilter, string> = { all: "Все", debug: "Отладка", info: "Информация", warning: "Предупреждения", error: "Ошибки", critical: "Критические" };
            return (
            <button
              key={level}
              className={levelFilter === level ? "active" : ""}
              onClick={() => setLevelFilter(level)}
            >
              {labels[level]}
            </button>
          );
          },
        )}
      </div>

      <div className="event-list">
        {filteredEvents.length === 0 && (
          <div className="empty-state"><Archive size={28} aria-hidden="true" /><strong>Событий нет</strong><span>Для этого фильтра пока ничего не найдено.</span></div>
        )}
        {filteredEvents
          .slice()
          .reverse()
          .map((event) => (
            <article className={`event-row ${event.level}`} key={event.id}>
              <div className="event-main">
                <span className="event-time">{formatTime(event.created_at)}</span>
                <span className="event-level">{event.level}</span>
                <span className="event-type">{event.type}</span>
                <strong>{event.message}</strong>
              </div>
              <details className="event-details"><summary>Технические данные</summary><pre>{JSON.stringify(event.metadata, null, 2)}</pre></details>
            </article>
          ))}
      </div>
    </section>
  );
}

function SettingsPage({
  settings,
  avatarStatus,
  events,
  onRefreshEvents,
  onRefreshAvatar,
  onSettingsChanged,
}: {
  settings: PublicSettings | null;
  avatarStatus: AvatarStatusResponse | null;
  events: BackendEvent[];
  onRefreshEvents: () => Promise<void>;
  onRefreshAvatar: () => Promise<void>;
  onSettingsChanged: (settings: PublicSettings) => void;
}) {
  const [activeSection, setActiveSection] = useState<SettingsSection>("general");
  const [personality, setPersonality] = useState("");
  const [voiceLanguage, setVoiceLanguage] = useState("ru");
  const [voiceTtsVoice, setVoiceTtsVoice] = useState("");
  const [voiceTtsStyle, setVoiceTtsStyle] = useState("auto");
  const [voiceExpressionLevel, setVoiceExpressionLevel] = useState("natural");
  const [pronunciationsText, setPronunciationsText] = useState("");
  const [voicePlaybackRate, setVoicePlaybackRate] = useState(1);
  const [prebufferSegments, setPrebufferSegments] = useState(1);
  const [prebufferMs, setPrebufferMs] = useState(0);
  const [memoryMode, setMemoryMode] = useState("balanced");
  const [memoryIncognito, setMemoryIncognito] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (settings) {
      setPersonality(settings.personality);
      setVoiceLanguage(settings.voice_language);
      setVoiceTtsVoice(settings.voice_tts_voice);
      setVoiceTtsStyle(settings.voice_tts_style);
      setVoiceExpressionLevel(settings.voice_tts_expression_level);
      setVoicePlaybackRate(settings.voice_playback_rate);
      setPrebufferSegments(settings.voice_live_playback_prebuffer_segments);
      setPrebufferMs(settings.voice_live_playback_prebuffer_ms);
      setMemoryMode(settings.memory_mode);
      setMemoryIncognito(settings.memory_incognito);
    }
  }, [settings]);

  useEffect(() => {
    void getPronunciations()
      .then((result) => setPronunciationsText(formatPronunciations(result.pronunciations)))
      .catch(() => setPronunciationsText(""));
  }, []);

  const saveSettings = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const nextSettings = await updateRuntimeSettings({
        personality,
        voice_language: voiceLanguage,
        voice_tts_voice: voiceTtsVoice,
        voice_playback_rate: voicePlaybackRate,
        voice_live_playback_prebuffer_segments: prebufferSegments,
        voice_live_playback_prebuffer_ms: prebufferMs,
        memory_mode: memoryMode,
        memory_incognito: memoryIncognito,
      });
      onSettingsChanged(nextSettings);
      setMessage("Настройки сохранены.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось сохранить настройки.");
    } finally {
      setSaving(false);
    }
  };

  const changeVoiceStyle = async (value: string) => {
    setSaving(true);
    setMessage(null);
    try {
      const nextSettings = await updateVoiceStyle(value);
      onSettingsChanged(nextSettings);
      setVoiceTtsStyle(nextSettings.voice_tts_style);
      setMessage("Подача голоса изменена до перезапуска.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось изменить подачу голоса.");
    } finally {
      setSaving(false);
    }
  };

  const changeVoiceExpression = async (value: string) => {
    setSaving(true);
    setMessage(null);
    try {
      const nextSettings = await updateVoiceExpression(value);
      onSettingsChanged(nextSettings);
      setVoiceExpressionLevel(nextSettings.voice_tts_expression_level);
      setMessage("Выразительность изменена до перезапуска.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось изменить выразительность.");
    } finally {
      setSaving(false);
    }
  };

  const savePronunciations = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const result = await updatePronunciations(parsePronunciations(pronunciationsText));
      setPronunciationsText(formatPronunciations(result.pronunciations));
      setMessage("Словарь произношений сохранён и применён.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось сохранить словарь.");
    } finally {
      setSaving(false);
    }
  };

  if (!settings) {
    return (
      <section className="panel">
        <div className="empty-state"><CircleAlert size={28} aria-hidden="true" /><strong>Настройки недоступны</strong><span>Подключитесь к сервису и попробуйте ещё раз.</span></div>
      </section>
    );
  }

  const ttsProviderLabel = settings.voice_tts_provider === "silero" ? "Silero" : settings.voice_tts_provider;
  const ttsRuntimeLabel = [ttsProviderLabel, settings.voice_tts_device?.toUpperCase()]
    .filter(Boolean)
    .join(" · ");

  return (
    <section className="panel settings-panel">
      <nav className="settings-navigation" aria-label="Разделы настроек">
        <SettingsSectionButton section="general" current={activeSection} label="Общее" icon={SlidersHorizontal} onClick={setActiveSection} />
        <SettingsSectionButton section="voice" current={activeSection} label="Голос" icon={Volume2} onClick={setActiveSection} />
        <SettingsSectionButton section="memory" current={activeSection} label="Память" icon={Brain} onClick={setActiveSection} />
        <SettingsSectionButton section="system" current={activeSection} label="Система" icon={MonitorCog} onClick={setActiveSection} />
      </nav>

      <div className="settings-grid system-status-grid" hidden={activeSection !== "system"}>
        <InfoRow label="Ключ API" value={settings.api_key_configured ? "Настроен" : "Не настроен"} />
        <InfoRow label="Провайдер" value={settings.provider} />
        <InfoRow label="Модель" value={settings.model} />
        <InfoRow label="История в контексте" value={`${settings.chat_history_limit} сообщений`} />
        <InfoRow label="Уровень журнала" value={settings.log_level} />
        <InfoRow
          label="Голос"
          value={`${settings.voice_language} / ${settings.voice_tts_voice} / ${settings.voice_playback_rate.toFixed(2)}x`}
        />
      </div>

      <div className="system-stack" hidden={activeSection !== "system"}>
        <ModelManager />
        <BackupControls />
        <SystemMaintenance />
        <AvatarControls avatarStatus={avatarStatus} onRefresh={onRefreshAvatar} />
        <details className="system-disclosure events-disclosure">
          <summary>
            <span><strong>Журнал событий</strong><small>Технические события и диагностика</small></span>
            <ChevronDown size={18} aria-hidden="true" />
          </summary>
          <EventsPage events={events} onRefreshEvents={onRefreshEvents} compact />
        </details>
      </div>

      <div className="form-grid settings-form" hidden={activeSection === "system"}>
        <fieldset className="settings-group" hidden={activeSection !== "general"}>
          <legend>Общее</legend>
          <label>
            Стиль общения
            <select
              value={personality}
              onChange={(event) => setPersonality(event.target.value)}
            >
              {settings.available_personalities.map((availablePersonality) => (
                <option key={availablePersonality} value={availablePersonality}>
                  {personalityLabel(availablePersonality)}
                </option>
              ))}
            </select>
          </label>
        </fieldset>

        <fieldset className="settings-group" hidden={activeSection !== "voice"}>
          <legend>Голос</legend>
          <label>
            Язык голосового ввода
            <select
              value={voiceLanguage}
              onChange={(event) => setVoiceLanguage(event.target.value)}
            >
              {settings.available_voice_languages.map((availableLanguage) => (
                <option key={availableLanguage} value={availableLanguage}>
                  {availableLanguage === "ru" ? "Русский" : availableLanguage === "en" ? "Английский" : availableLanguage}
                </option>
              ))}
            </select>
          </label>

          <label>
            Голос {ttsProviderLabel}
            <select
              value={voiceTtsVoice}
              onChange={(event) => setVoiceTtsVoice(event.target.value)}
            >
              {settings.available_tts_voices.map((availableVoice) => (
                <option key={availableVoice} value={availableVoice}>
                  {availableVoice}
                </option>
              ))}
            </select>
          </label>

          <label>
            Скорость воспроизведения <strong>{voicePlaybackRate.toFixed(2)}×</strong>
            <input
              min="0.75"
              max="1.25"
              step="0.05"
              type="range"
              value={voicePlaybackRate}
              onChange={(event) => setVoicePlaybackRate(Number(event.target.value))}
            />
          </label>

          <label>
            Подача голоса
            <select value={voiceTtsStyle} onChange={(event) => void changeVoiceStyle(event.target.value)} disabled={saving}>
              <option value="auto">Авто — по эмоции нейросети</option>
              <option value="calm">Спокойно</option>
              <option value="normal">Обычно</option>
              <option value="energetic">Энергично</option>
              <option value="thoughtful">Задумчиво</option>
              <option value="assertive">Напористо</option>
            </select>
            <small>Действует до перезапуска приложения.</small>
          </label>

          <label>
            Выразительность
            <select value={voiceExpressionLevel} onChange={(event) => void changeVoiceExpression(event.target.value)} disabled={saving}>
              <option value="minimal">Минимальная — почти нейтрально</option>
              <option value="natural">Естественная — рекомендовано</option>
              <option value="noticeable">Заметная — сильнее эмоции</option>
            </select>
            <small>Усиливает или смягчает выбранную подачу; обычный профиль не меняется.</small>
          </label>

          <div className="readonly-setting">
            <span>Движок синтеза</span>
            <strong>
              {ttsRuntimeLabel}
              {" · активен"}
            </strong>
          </div>
        </fieldset>

        <fieldset className="settings-group" hidden={activeSection !== "voice"}>
          <legend>Словарь произношений</legend>
          <label>
            Термин = как произносить
            <textarea
              rows={8}
              value={pronunciationsText}
              onChange={(event) => setPronunciationsText(event.target.value)}
              placeholder={"OpenAI = Оупен Эй Ай\nКак-то = к+ак-то\nМука = му́ка"}
              disabled={saving}
            />
            <small>
              Одна пара на строку. Ударение можно задать как «к+ак-то» или «ка́к-то».
              Изменения применяются к следующей фразе без перезапуска.
            </small>
          </label>
          <button className="secondary" type="button" onClick={() => void savePronunciations()} disabled={saving}>
            Сохранить словарь
          </button>
        </fieldset>

        <fieldset className="settings-group" hidden={activeSection !== "voice"}>
          <legend>Дополнительно</legend>
          <label>
            Сегментов в буфере
            <input
              min="1"
              max="4"
              step="1"
              type="number"
              value={prebufferSegments}
              onChange={(event) => setPrebufferSegments(Number(event.target.value))}
            />
          </label>

          <label>
            Задержка буфера, мс
            <input
              min="0"
              max="1500"
              step="50"
              type="number"
              value={prebufferMs}
              onChange={(event) => setPrebufferMs(Number(event.target.value))}
            />
          </label>
        </fieldset>

        <fieldset className="settings-group" hidden={activeSection !== "memory"}>
          <legend>Память</legend>
          <label>
            Режим сохранения
            <select value={memoryMode} onChange={(event) => setMemoryMode(event.target.value)}>
              <option value="off">Не сохранять</option>
              <option value="balanced">Умный — только важные устойчивые факты</option>
              <option value="automatic">Автоматический — все обычные факты</option>
            </select>
          </label>
          <label>
            <input type="checkbox" checked={memoryIncognito} onChange={(event) => setMemoryIncognito(event.target.checked)} />
            Не сохранять текущий разговор (инкогнито)
          </label>
        </fieldset>

        <button className="primary-button settings-save" onClick={saveSettings} disabled={saving}>
          {saving ? "Сохраняем…" : "Сохранить изменения"}
        </button>
      </div>

      {message && <div className="notice" role="status">{message}</div>}
    </section>
  );
}

function SettingsSectionButton({
  section,
  current,
  label,
  icon: Icon,
  onClick,
}: {
  section: SettingsSection;
  current: SettingsSection;
  label: string;
  icon: LucideIcon;
  onClick: (section: SettingsSection) => void;
}) {
  return (
    <button
      className={`settings-nav-button${section === current ? " is-active" : ""}`}
      aria-current={section === current ? "page" : undefined}
      onClick={() => onClick(section)}
    >
      <Icon size={17} aria-hidden="true" />
      {label}
    </button>
  );
}

function ModelManager() {
  const [models, setModels] = useState<ManagedModel[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setModels((await getModels()).models);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Модели недоступны.");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const install = async (modelId: string) => {
    setMessage(null);
    try {
      await installModel(modelId);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось начать загрузку модели.");
    }
  };

  const remove = async (modelId: string) => {
    setMessage(null);
    try {
      await removeModel(modelId);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось удалить модель.");
    }
  };

  return (
    <section className="system-card" aria-label="Управление моделями">
      <div className="panel-header"><div><h2>Модели</h2><span>Хранятся вне папки приложения</span></div><button className="secondary" onClick={() => void refresh()}><RefreshCw size={16} aria-hidden="true" />Обновить</button></div>
      {models.map((model) => {
        const percent = model.total_bytes > 0 ? Math.min(100, Math.round((model.downloaded_bytes / model.total_bytes) * 100)) : 0;
        return <div className="settings-group" key={model.id}>
          <strong>{model.name} {model.version}</strong>
          <span>{model.installed ? "Установлена и проверена" : model.status === "downloading" ? `Загружаем: ${percent}%` : "Не установлена"}</span>
          {model.status === "failed" && <span className="notice">{model.error}</span>}
          {model.status === "downloading" && <progress value={percent} max="100">{percent}%</progress>}
          <div className="model-actions">
            {!model.installed && <button className="primary-button" onClick={() => void install(model.id)} disabled={model.status === "downloading"}>{model.status === "failed" ? "Повторить загрузку" : "Скачать"}</button>}
            {model.installed && <button className="secondary" onClick={() => void remove(model.id)}>Удалить</button>}
          </div>
          {model.restart_required && model.installed && <small>Перезапустите Iris, чтобы использовать модель.</small>}
        </div>;
      })}
      {message && <div className="notice">{message}</div>}
    </section>
  );
}

function BackupControls() {
  const [backups, setBackups] = useState<Array<{ name: string; size_bytes: number; created_at: string }>>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    try {
      setBackups(await getBackups());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Резервные копии недоступны.");
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  const create = async () => {
    setBusy(true);
    setMessage(null);
    try {
      await createBackup();
      await refresh();
      setMessage("Резервная копия создана. Ключи API в неё не попадают.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось создать резервную копию.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="system-card" aria-label="Резервные копии">
      <div className="panel-header"><div><h2>Резервные копии</h2><span>Память и настройки, срок хранения — 30 дней</span></div><button className="primary-button" onClick={() => void create()} disabled={busy}>{busy ? "Создаём…" : "Создать копию"}</button></div>
      {backups.length ? <div className="settings-grid">{backups.slice(0, 3).map((backup) => <InfoRow key={backup.name} label={backup.name} value={`${Math.ceil(backup.size_bytes / 1024)} КБ · ${formatTime(backup.created_at)}`} />)}</div> : <span className="card-empty">Резервных копий пока нет.</span>}
      <small>Удаление Iris не удаляет эти данные из профиля Windows.</small>
      {message && <div className="notice">{message}</div>}
    </section>
  );
}

function SystemMaintenance() {
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (confirmation: string, action: () => Promise<unknown>, success: string) => {
    if (!window.confirm(confirmation)) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await action();
      const restartRequired = typeof result === "object" && result !== null && "chroma_cleanup_pending" in result && Boolean(result.chroma_cleanup_pending);
      setMessage(restartRequired ? `${success} Перезапусти приложение: тогда папка ChromaDB будет удалена полностью.` : success);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось завершить обслуживание.");
    } finally {
      setBusy(false);
    }
  };

  return <section className="system-card maintenance-card" aria-label="Обслуживание данных">
    <div className="panel-header"><div><h2>Обслуживание данных</h2><span>Необратимые действия вынесены отдельно</span></div><Database size={20} aria-hidden="true" /></div>
    <div className="maintenance-actions">
      <button className="secondary" disabled={busy} onClick={() => void run("Перестроить индекс памяти? Сами записи не будут удалены.", reindexMemories, "Индекс памяти перестроен.")}>Перестроить индекс памяти</button>
      <button className="secondary danger-button" disabled={busy} onClick={() => void run("Удалить только долгосрочную память? История диалогов сохранится.", clearMemories, "Долгосрочная память очищена.")}>Очистить память</button>
      <button className="danger-button" disabled={busy} onClick={() => void run("Удалить всю историю, сводки и долгосрочную память? Это действие нельзя отменить.", resetAllCompanionData, "Все данные помощника удалены.")}>Сбросить все данные</button>
    </div>
    {message && <div className="notice" role="status">{message}</div>}
  </section>;
}

function AvatarControls({
  avatarStatus,
  onRefresh,
}: {
  avatarStatus: AvatarStatusResponse | null;
  onRefresh: () => Promise<void>;
}) {
  const [phrase, setPhrase] = useState("Проверка аватара.");
  const [emotion, setEmotion] = useState("happy");
  const [gesture, setGesture] = useState("greeting");
  const [motionIntensity, setMotionIntensity] = useState(0.8);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [overlay, setOverlay] = useState<AvatarOverlaySettings | null>(null);
  const enabled = Boolean(avatarStatus?.enabled);
  const client = avatarStatus?.clients[0];
  const engine = avatarStatus?.emotion_engine;

  useEffect(() => { void getAvatarOverlay().then(setOverlay).catch(() => setOverlay(null)); }, []);

  const run = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      setMessage(success);
      await onRefresh();
    } catch {
      setMessage("Не удалось выполнить действие с аватаром.");
    } finally {
      setBusy(false);
    }
  };

  const updateOverlay = async (patch: Partial<AvatarOverlaySettings>) => {
    setBusy(true); setMessage(null);
    try { setOverlay(await updateAvatarOverlay(patch)); setMessage("Настройки оверлея обновлены."); }
    catch { setMessage("Не удалось сохранить настройки оверлея."); }
    finally { setBusy(false); }
  };

  return (
    <details className="system-disclosure">
      <summary>
        <span><strong>Аватар</strong><small>{enabled ? `${avatarStatus?.client_count ?? 0} подключено` : "Интеграция отключена"}</small></span>
        <ChevronDown size={18} aria-hidden="true" />
      </summary>
      <section className="avatar-controls" aria-label="Управление аватаром">
      <div className="disclosure-toolbar">
        <span>{enabled ? "Управление оверлеем и тестовыми командами" : "Подключите Unity-аватар, чтобы отправлять команды"}</span>
        <button className="icon-button" onClick={() => void onRefresh()} disabled={busy} aria-label="Обновить статус аватара" title="Обновить статус аватара"><RefreshCw size={16} /></button>
      </div>
      <div className="avatar-summary-grid">
        <InfoRow label="Клиент" value={client?.client_name ?? "не подключён"} />
        <InfoRow label="Состояние" value={client?.state ?? "Отключён"} />
        <InfoRow label="Последний сигнал" value={client ? formatTime(client.last_heartbeat_at) : "—"} />
        <InfoRow label="Целевая эмоция" value={engine?.target_emotion ?? "нейтральная"} />
      </div>
      <details className="avatar-technical">
        <summary>Технические данные</summary>
        <div className="avatar-grid">
          <InfoRow label="Протокол" value={avatarStatus ? `v${avatarStatus.protocol_version}` : "недоступен"} />
          <InfoRow label="Профиль движения" value={client?.current_motion_profile ?? "нет данных"} />
          <InfoRow label="Текущий жест" value={client?.current_gesture ?? "нет"} />
          <InfoRow label="Связь с движком" value={engine ? (engine.mapping_valid ? "настроена" : "резервная") : "недоступна"} />
        </div>
      </details>
      <div className="avatar-options">
        <label>
          <input type="checkbox" checked={overlay?.visible ?? true} disabled={!enabled || busy} onChange={(event) => void updateOverlay({ visible: event.target.checked })} />
          Показывать оверлей
        </label>
        <label>
          <input type="checkbox" checked={overlay?.always_on_top ?? true} disabled={!enabled || busy} onChange={(event) => void updateOverlay({ always_on_top: event.target.checked })} />
          Поверх окон
        </label>
        <label>
          <input type="checkbox" checked={overlay?.locked ?? true} disabled={!enabled || busy} onChange={(event) => void updateOverlay({ locked: event.target.checked })} />
          Заблокировать клики
        </label>
      </div>
      <div className="avatar-test-grid">
        <label>
          Масштаб оверлея {overlay?.scale?.toFixed(1) ?? "1.0"}
          <input min="0.5" max="2" step="0.1" type="range" value={overlay?.scale ?? 1} disabled={!enabled || busy} onChange={(event) => void updateOverlay({ scale: Number(event.target.value) })} />
        </label>
        <label>
          Тестовая фраза
          <input value={phrase} onChange={(event) => setPhrase(event.target.value)} disabled={!enabled || busy} />
        </label>
        <label>
          Эмоция
          <select value={emotion} onChange={(event) => setEmotion(event.target.value)} disabled={!enabled || busy}>
            {Object.entries(AVATAR_EMOTION_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label>
          Тестовый жест
          <select value={gesture} onChange={(event) => setGesture(event.target.value)} disabled={!enabled || busy}>
            {Object.entries(AVATAR_GESTURE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label>
          Интенсивность движения {motionIntensity.toFixed(1)}
          <input min="0" max="1" step="0.1" type="range" value={motionIntensity} onChange={(event) => setMotionIntensity(Number(event.target.value))} disabled={!enabled || busy} />
        </label>
      </div>
      <div className="avatar-test-actions">
        <button className="primary-button" onClick={() => void run(() => sendAvatarTestPhrase({ text: phrase, emotion }), "Тестовая фраза отправлена.")} disabled={!enabled || busy || !phrase.trim()}>Отправить фразу</button>
        <button className="secondary" onClick={() => void run(() => sendAvatarTestEmotion({ emotion, intensity: 1 }), "Эмоция отправлена.")} disabled={!enabled || busy}>Отправить эмоцию</button>
        <button className="secondary" onClick={() => void run(() => sendAvatarTestGesture({ gesture, intensity: motionIntensity, interrupt: true }), "Тестовый жест отправлен.")} disabled={!enabled || busy}>Отправить жест</button>
        <button className="secondary" onClick={() => void run(stopAvatar, "Движение сброшено.")} disabled={!enabled || busy}>Сбросить движение</button>
      </div>
      {message && <div className="notice" role="status">{message}</div>}
      </section>
    </details>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="info-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
