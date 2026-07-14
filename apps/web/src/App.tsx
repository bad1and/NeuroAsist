import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getAvatarStatus,
  getAvatarOverlay,
  createBackup,
  getBackups,
  getEvents,
  getTimelineJournal,
  getTimelineMessages,
  getSettings,
  getStatus,
  getVoiceTtsStatus,
  getModels,
  installModel,
  isDesktopManaged,
  removeModel,
  resolveApiUrl,
  saveDesktopApiKey,
  sendChatMessage,
  searchTimeline,
  deleteTimelineRange,
  sendVoiceMessage,
  updateRuntimeSettings,
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
} from "./types";
import type { VoiceServerEvent } from "./types";
import { PlaybackCoordinator, TTSStreamPlayer, VoiceSocketClient } from "./voice-live";
import { BrowserVadRecorder, PcmInputClient, type VadState } from "./vad";
import { JournalPage } from "./journal";
import { MemoryPage } from "./memory";

type Tab = "chat" | "journal" | "memory" | "events" | "settings";
type WsState = "connected" | "disconnected" | "reconnecting";
type LevelFilter = "all" | EventLevel;
type VoiceState = "idle" | "recording" | "transcribing" | "thinking" | "speaking" | "stopping" | "error";

const SESSION_ID = "default";
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
  return date.toLocaleTimeString();
}

function boolLabel(value: boolean): string {
  return value ? "yes" : "no";
}

function isLiveVoiceTransportError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  return (
    error.message.includes("Live voice connection failed") ||
    error.message.includes("Voice WebSocket must be connected")
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>("chat");
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
      setStatusError(error instanceof Error ? error.message : "Backend unavailable");
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

  return (
    <div className="app-shell">
      <Header
        status={status}
        settings={settings}
        wsState={wsState}
        statusError={statusError}
      />

      {setupRequired ? (
        <SetupWizard onComplete={refreshOverview} />
      ) : (
      <main className="workspace">
        <nav className="tabs" aria-label="Primary">
          <button
            className={activeTab === "chat" ? "active" : ""}
            onClick={() => setActiveTab("chat")}
          >
            Chat
          </button>
          <button
            className={activeTab === "journal" ? "active" : ""}
            onClick={() => setActiveTab("journal")}
          >
            Journal
          </button>
          <button
            className={activeTab === "memory" ? "active" : ""}
            onClick={() => setActiveTab("memory")}
          >
            Memory
          </button>
          <button
            className={activeTab === "events" ? "active" : ""}
            onClick={() => setActiveTab("events")}
          >
            Events
          </button>
          <button
            className={activeTab === "settings" ? "active" : ""}
            onClick={() => setActiveTab("settings")}
          >
            Settings
          </button>
        </nav>

        {activeTab === "chat" && (
          <ChatPage
            events={events}
            settings={settings}
            avatarStatus={avatarStatus}
            onRefreshEvents={refreshEvents}
          />
        )}
        {activeTab === "events" && (
          <EventsPage events={events} onRefreshEvents={refreshEvents} />
        )}
        {activeTab === "journal" && <JournalPage />}
        {activeTab === "memory" && <MemoryPage />}
        {activeTab === "settings" && (
          <SettingsPage
            settings={settings}
            avatarStatus={avatarStatus}
            onRefreshAvatar={refreshOverview}
            onSettingsChanged={(nextSettings) => {
              setSettings(nextSettings);
              void refreshOverview();
              void refreshEvents();
            }}
          />
        )}
      </main>
      )}
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
      setMessage(error instanceof Error ? error.message : "Could not save API key.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="workspace">
      <section className="panel settings-panel">
        <div className="panel-header"><h2>Welcome to NeuroAsist</h2><span>Step 1 of 2</span></div>
        <p>Paste your DeepSeek API key once. It is saved in Windows Credential Manager, not in the project files or settings.</p>
        <form className="form-grid" onSubmit={submit}>
          <label>
            DeepSeek API key
            <input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="sk-…" required />
          </label>
          <button className="settings-save" type="submit" disabled={busy || !apiKey.trim()}>{busy ? "Saving and starting…" : "Save and continue"}</button>
        </form>
        <p>Then open Settings → Models and download Silero VAD for hands-free voice.</p>
        {message && <div className="notice">{message}</div>}
      </section>
    </main>
  );
}

function Header({
  status,
  settings,
  wsState,
  statusError,
}: {
  status: StatusResponse | null;
  settings: PublicSettings | null;
  wsState: WsState;
  statusError: string | null;
}) {
  const backendOk = status?.backend === "ok" && !statusError;

  return (
    <header className="topbar">
      <div>
        <h1>NeuroAsist</h1>
        <p>{status?.version ?? "v0.2.0"} local control panel</p>
      </div>

      <div className="status-grid">
        <StatusPill label="backend" state={backendOk ? "ok" : "bad"} />
        <StatusPill label={`ws ${wsState}`} state={wsState === "connected" ? "ok" : "warn"} />
        <StatusPill
          label={`key ${boolLabel(status?.api_key_configured ?? false)}`}
          state={status?.api_key_configured ? "ok" : "warn"}
        />
        <div className="model-chip">
          {settings?.provider ?? "deepseek"} / {settings?.model ?? status?.llm_model ?? "unknown"}
        </div>
      </div>
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
      <span aria-hidden="true" />
      {label}
    </span>
  );
}

function ChatPage({
  events,
  settings,
  avatarStatus,
  onRefreshEvents,
}: {
  events: BackendEvent[];
  settings: PublicSettings | null;
  avatarStatus: AvatarStatusResponse | null;
  onRefreshEvents: () => Promise<void>;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [retryText, setRetryText] = useState<string | null>(null);
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
          setError(playerError.message);
          setLoading(false);
          setVoiceState("error");
        },
        {
          prebufferSegments: settings?.voice_live_playback_prebuffer_segments ?? 2,
          prebufferMs: settings?.voice_live_playback_prebuffer_ms ?? 700,
          playbackRate: settings?.voice_playback_rate ?? 1,
        },
        (gapMs) => {
          liveSocketRef.current?.send("playback.underrun", { underrun_ms: gapMs });
        },
      );
    }
    livePlayerRef.current.updateOptions({
      prebufferSegments: settings?.voice_live_playback_prebuffer_segments ?? 2,
      prebufferMs: settings?.voice_live_playback_prebuffer_ms ?? 700,
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
          playbackCoordinatorRef.current.cancel();
          liveSocketRef.current?.clearActive();
          setLoading(false);
          setVoiceState("idle");
        } else if (event.type === "voice.error") {
          livePlayerRef.current?.stop();
          playbackCoordinatorRef.current.cancel();
          liveSocketRef.current?.clearActive();
          setError(event.message ?? event.code ?? "Live voice failed");
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
  }, [ensureLivePlayer, speakTextInBrowser]);

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
            status.status === "queued" ? "Audio is still generating" : message.ttsError,
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
                      : "Could not check audio status",
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
    [pollVoiceTtsStatus],
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
                    : "Voice synthesis failed",
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
      const response = await sendChatMessage(SESSION_ID, text);
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
      setError(requestError instanceof Error ? requestError.message : "Chat failed");
      setRetryText(text);
      setMessages((current) => current.filter((message) => message.id !== userMessage.id));
    } finally {
      setLoading(false);
    }
  };

  const startRecording = async (bargeIn = false) => {
    if (!voiceSupported || (!bargeIn && (loading || voiceState !== "idle"))) {
      return;
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
        recordError instanceof Error ? recordError.message : "Microphone is unavailable",
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
    if (voiceState === "thinking" || voiceState === "speaking") {
      setVoiceState("stopping");
      livePlayerRef.current?.stop();
      liveSocketRef.current?.cancel();
      liveSocketRef.current?.clearActive();
      playbackCoordinatorRef.current.cancel();
      setLoading(false);
      await startRecording(true);
      return;
    }
    await startRecording();
  };

  const submitVoice = async (audio: Blob, endOfSpeechUnixMs?: number) => {
    if (audio.size === 0) {
      setError("Recording is empty");
      setVoiceState("idle");
      return;
    }
    if (audio.size < 800) {
      setError("Recording is too short");
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
        setError("Live voice stream is unavailable; used legacy voice response.");
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
      setError(requestError instanceof Error ? requestError.message : "Voice chat failed");
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
          setError(event.message ?? "Live voice input failed");
        }
      });
      await input.connect(16000, settings?.voice_language ?? "ru");
      pcmInputRef.current = input;
      const recorder = new BrowserVadRecorder();
      vadRecorderRef.current = recorder;
      await recorder.start(
        (pcm16) => pcmInputRef.current?.sendPcm(pcm16),
        (nextState) => {
          setVadState(nextState);
          if (nextState === "speech" && liveSocketRef.current?.activeUtteranceId) {
            livePlayerRef.current?.stop();
            liveSocketRef.current.cancel();
            liveSocketRef.current.clearActive();
            playbackCoordinatorRef.current.cancel();
          }
        },
      );
      setHandsFree(true);
    } catch (vadError) {
      vadRecorderRef.current?.stop();
      vadRecorderRef.current = null;
      setError(vadError instanceof Error ? vadError.message : "Hands-free voice is unavailable");
      setHandsFree(false);
      setVadState("idle");
    }
  };

  return (
    <section className="panel chat-panel">
      <div className="panel-header">
        <h2>Chat</h2>
        <span>session: {SESSION_ID}</span>
      </div>

      <div className="message-list" ref={listRef}>
        {messages.length === 0 && (
          <div className="empty-state">Send a message to start the local session.</div>
        )}
        {messages.map((message) => (
          <article className={`message ${message.role}`} key={message.id}>
            <div className="message-role">{message.role}</div>
            <p>{message.content}</p>
            {message.role === "assistant" && (
              <div className="message-meta">
                <span>{message.emotion}</span>
                <span>{message.intent}</span>
                {message.ttsStatus && <span>tts {message.ttsStatus}</span>}
              </div>
            )}
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
                                ttsError: "Could not start audio playback",
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
                              ttsError: "Audio is not ready yet",
                            }
                          : currentMessage,
                      ),
                    );
                  }
                }}
                type="button"
              >
                {message.audioUrl || message.voiceRequestId || browserSpeechSupported
                  ? "Speak"
                  : "Audio pending"}
              </button>
            )}
          </article>
        ))}
      </div>

      {error && <div className="error-banner">{error}{retryText && <button type="button" onClick={() => { setDraft(retryText); setRetryText(null); }}>Retry</button>}</div>}

      <form className="chat-form" onSubmit={onSubmit}>
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Message NeuroAsist"
          rows={3}
        />
        <button type="submit" disabled={loading || draft.trim().length === 0}>
          {loading ? "Sending" : "Send"}
        </button>
      </form>

      <div className="voice-controls">
        <button
          className={voiceState === "recording" ? "recording" : ""}
          disabled={!voiceSupported || voiceState === "transcribing" || voiceState === "stopping"}
          onClick={() => void toggleRecording()}
          type="button"
        >
          {voiceButtonLabel(voiceState)}
        </button>
        <button
          className={handsFree ? "recording" : "secondary"}
          disabled={!handsFreeSupported || voiceState === "transcribing"}
          onClick={() => void toggleHandsFree()}
          type="button"
        >
          {handsFree ? "Hands-free on" : "Hands-free"}
        </button>
        <span>
          {voiceSupported
            ? `voice: ${settings?.voice_language ?? "ru"}${handsFree ? ` · ${vadState}` : ""}`
            : "voice unavailable"}
        </span>
      </div>
    </section>
  );
}

function voiceButtonLabel(voiceState: VoiceState): string {
  if (voiceState === "recording") {
    return "Stop and send";
  }
  if (voiceState === "transcribing") {
    return "Transcribing";
  }
  if (voiceState === "thinking") {
    return "Stop";
  }
  if (voiceState === "speaking") {
    return "Stop speaking";
  }
  if (voiceState === "stopping") {
    return "Stopping";
  }
  if (voiceState === "error") {
    return "Try again";
  }
  return "Start recording";
}

function getStringMetadata(event: BackendEvent, key: string): string | null {
  const value = event.metadata[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function EventsPage({
  events,
  onRefreshEvents,
}: {
  events: BackendEvent[];
  onRefreshEvents: () => Promise<void>;
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
      <div className="panel-header">
        <h2>Events</h2>
        <button className="secondary" onClick={() => void onRefreshEvents()}>
          Refresh
        </button>
      </div>

      <div className="filters">
        {(["all", "info", "warning", "error", "critical"] as LevelFilter[]).map(
          (level) => (
            <button
              key={level}
              className={levelFilter === level ? "active" : ""}
              onClick={() => setLevelFilter(level)}
            >
              {level}
            </button>
          ),
        )}
      </div>

      <div className="event-list">
        {filteredEvents.length === 0 && (
          <div className="empty-state">No events for this filter.</div>
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
              <pre>{JSON.stringify(event.metadata, null, 2)}</pre>
            </article>
          ))}
      </div>
    </section>
  );
}

function SettingsPage({
  settings,
  avatarStatus,
  onRefreshAvatar,
  onSettingsChanged,
}: {
  settings: PublicSettings | null;
  avatarStatus: AvatarStatusResponse | null;
  onRefreshAvatar: () => Promise<void>;
  onSettingsChanged: (settings: PublicSettings) => void;
}) {
  const [personality, setPersonality] = useState("");
  const [voiceLanguage, setVoiceLanguage] = useState("ru");
  const [voiceTtsVoice, setVoiceTtsVoice] = useState("");
  const [voicePlaybackRate, setVoicePlaybackRate] = useState(1);
  const [prebufferSegments, setPrebufferSegments] = useState(2);
  const [prebufferMs, setPrebufferMs] = useState(1000);
  const [memoryMode, setMemoryMode] = useState("ask");
  const [memoryIncognito, setMemoryIncognito] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (settings) {
      setPersonality(settings.personality);
      setVoiceLanguage(settings.voice_language);
      setVoiceTtsVoice(settings.voice_tts_voice);
      setVoicePlaybackRate(settings.voice_playback_rate);
      setPrebufferSegments(settings.voice_live_playback_prebuffer_segments);
      setPrebufferMs(settings.voice_live_playback_prebuffer_ms);
      setMemoryMode(settings.memory_mode);
      setMemoryIncognito(settings.memory_incognito);
    }
  }, [settings]);

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
      setMessage("Runtime settings saved.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to save settings.");
    } finally {
      setSaving(false);
    }
  };

  if (!settings) {
    return (
      <section className="panel">
        <div className="empty-state">Settings unavailable.</div>
      </section>
    );
  }

  return (
    <section className="panel settings-panel">
      <div className="panel-header">
        <h2>Settings</h2>
        <span>provider: {settings.provider}</span>
      </div>

      <div className="settings-grid">
        <InfoRow label="API key configured" value={boolLabel(settings.api_key_configured)} />
        <InfoRow label="Provider" value={settings.provider} />
        <InfoRow label="Fixed model" value={settings.model} />
        <InfoRow label="Chat history limit" value={String(settings.chat_history_limit)} />
        <InfoRow label="Log level" value={settings.log_level} />
        <InfoRow
          label="Voice"
          value={`${settings.voice_language} / ${settings.voice_tts_voice} / ${settings.voice_playback_rate.toFixed(2)}x`}
        />
      </div>

      <AvatarControls avatarStatus={avatarStatus} onRefresh={onRefreshAvatar} />
      <ModelManager />
      <BackupControls />

      <div className="form-grid">
        <fieldset className="settings-group">
          <legend>Assistant</legend>
          <label>
            Personality
            <select
              value={personality}
              onChange={(event) => setPersonality(event.target.value)}
            >
              {settings.available_personalities.map((availablePersonality) => (
                <option key={availablePersonality} value={availablePersonality}>
                  {availablePersonality}
                </option>
              ))}
            </select>
          </label>
        </fieldset>

        <fieldset className="settings-group">
          <legend>Voice</legend>
          <label>
            Voice language
            <select
              value={voiceLanguage}
              onChange={(event) => setVoiceLanguage(event.target.value)}
            >
              {settings.available_voice_languages.map((availableLanguage) => (
                <option key={availableLanguage} value={availableLanguage}>
                  {availableLanguage}
                </option>
              ))}
            </select>
          </label>

          <label>
            Silero speaker
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
            Playback speed <strong>{voicePlaybackRate.toFixed(2)}x</strong>
            <input
              min="0.75"
              max="1.25"
              step="0.05"
              type="range"
              value={voicePlaybackRate}
              onChange={(event) => setVoicePlaybackRate(Number(event.target.value))}
            />
          </label>

          <div className="readonly-setting">
            <span>Tone / pitch</span>
            <strong>Not supported by current Silero backend</strong>
          </div>
        </fieldset>

        <fieldset className="settings-group">
          <legend>Live playback</legend>
          <label>
            Prebuffer segments
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
            Prebuffer ms
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

        <fieldset className="settings-group">
          <legend>Memory</legend>
          <label>
            Saving mode
            <select value={memoryMode} onChange={(event) => setMemoryMode(event.target.value)}>
              <option value="off">Off</option>
              <option value="ask">Ask before saving</option>
              <option value="automatic">Automatic normal facts</option>
            </select>
          </label>
          <label>
            <input type="checkbox" checked={memoryIncognito} onChange={(event) => setMemoryIncognito(event.target.checked)} />
            Do not save this conversation (incognito)
          </label>
        </fieldset>

        <button className="settings-save" onClick={saveSettings} disabled={saving}>
          {saving ? "Saving" : "Save runtime settings"}
        </button>
      </div>

      {message && <div className="notice">{message}</div>}
    </section>
  );
}

function ModelManager() {
  const [models, setModels] = useState<ManagedModel[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setModels((await getModels()).models);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Models are unavailable.");
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
      setMessage(error instanceof Error ? error.message : "Model download could not be started.");
    }
  };

  const remove = async (modelId: string) => {
    setMessage(null);
    try {
      await removeModel(modelId);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Model could not be removed.");
    }
  };

  return (
    <section className="avatar-controls" aria-label="Model manager">
      <div className="panel-header"><div><h2>Models</h2><span>Stored outside the application folder</span></div><button className="secondary" onClick={() => void refresh()}>Refresh</button></div>
      {models.map((model) => {
        const percent = model.total_bytes > 0 ? Math.min(100, Math.round((model.downloaded_bytes / model.total_bytes) * 100)) : 0;
        return <div className="settings-group" key={model.id}>
          <strong>{model.name} {model.version}</strong>
          <span>{model.installed ? "Installed and checksum verified" : model.status === "downloading" ? `Downloading: ${percent}%` : "Not installed"}</span>
          {model.status === "failed" && <span className="notice">{model.error}</span>}
          {model.status === "downloading" && <progress value={percent} max="100">{percent}%</progress>}
          <div className="avatar-actions">
            {!model.installed && <button onClick={() => void install(model.id)} disabled={model.status === "downloading"}>{model.status === "failed" ? "Retry download" : "Download"}</button>}
            {model.installed && <button className="secondary" onClick={() => void remove(model.id)}>Remove</button>}
          </div>
          {model.restart_required && model.installed && <small>Restart NeuroAsist to use this model.</small>}
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
      setMessage(error instanceof Error ? error.message : "Backups are unavailable.");
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  const create = async () => {
    setBusy(true);
    setMessage(null);
    try {
      await createBackup();
      await refresh();
      setMessage("Backup created. API keys are never included.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Backup could not be created.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="avatar-controls" aria-label="Backups">
      <div className="panel-header"><div><h2>Backups</h2><span>Memory and settings; kept for 30 days</span></div><button onClick={() => void create()} disabled={busy}>{busy ? "Creating…" : "Create backup"}</button></div>
      {backups.length ? <div className="settings-grid">{backups.slice(0, 3).map((backup) => <InfoRow key={backup.name} label={backup.name} value={`${Math.ceil(backup.size_bytes / 1024)} KB · ${formatTime(backup.created_at)}`} />)}</div> : <span>No backups yet.</span>}
      <small>Uninstalling NeuroAsist leaves this data in your Windows profile. Delete it only if you explicitly choose to.</small>
      {message && <div className="notice">{message}</div>}
    </section>
  );
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
      setMessage("Avatar request could not be completed.");
    } finally {
      setBusy(false);
    }
  };

  const updateOverlay = async (patch: Partial<AvatarOverlaySettings>) => {
    setBusy(true); setMessage(null);
    try { setOverlay(await updateAvatarOverlay(patch)); setMessage("Overlay settings updated."); }
    catch { setMessage("Overlay settings could not be saved."); }
    finally { setBusy(false); }
  };

  return (
    <section className="avatar-controls" aria-label="Avatar controls">
      <div className="panel-header">
        <div>
          <h2>Avatar</h2>
          <span>{enabled ? `${avatarStatus?.client_count ?? 0} connected client(s)` : "Integration disabled"}</span>
        </div>
        <button className="secondary" onClick={() => void onRefresh()} disabled={busy}>Refresh status</button>
      </div>
      <div className="avatar-grid">
        <InfoRow label="Protocol" value={avatarStatus ? `v${avatarStatus.protocol_version}` : "unavailable"} />
        <InfoRow label="Client" value={client?.client_name ?? "disconnected"} />
        <InfoRow label="State" value={client?.state ?? "Disconnected"} />
        <InfoRow label="Heartbeat" value={client ? formatTime(client.last_heartbeat_at) : "—"} />
        <InfoRow label="Motion profile" value={client?.current_motion_profile ?? "unreported"} />
        <InfoRow label="Current gesture" value={client?.current_gesture ?? "none"} />
        <InfoRow label="Target emotion" value={engine?.target_emotion ?? "neutral"} />
        <InfoRow label="Engine mapping" value={engine ? (engine.mapping_valid ? "valid" : "fallback") : "unavailable"} />
      </div>
      <div className="avatar-actions">
        <label>
          <input type="checkbox" checked={overlay?.visible ?? true} disabled={!enabled || busy} onChange={(event) => void updateOverlay({ visible: event.target.checked })} />
          Show overlay
        </label>
        <label>
          <input type="checkbox" checked={overlay?.always_on_top ?? true} disabled={!enabled || busy} onChange={(event) => void updateOverlay({ always_on_top: event.target.checked })} />
          Always on top
        </label>
        <label>
          <input type="checkbox" checked={overlay?.locked ?? true} disabled={!enabled || busy} onChange={(event) => void updateOverlay({ locked: event.target.checked })} />
          Lock / click-through
        </label>
        <label>
          Overlay scale {overlay?.scale?.toFixed(1) ?? "1.0"}
          <input min="0.5" max="2" step="0.1" type="range" value={overlay?.scale ?? 1} disabled={!enabled || busy} onChange={(event) => void updateOverlay({ scale: Number(event.target.value) })} />
        </label>
        <label>
          Test phrase
          <input value={phrase} onChange={(event) => setPhrase(event.target.value)} disabled={!enabled || busy} />
        </label>
        <label>
          Emotion
          <select value={emotion} onChange={(event) => setEmotion(event.target.value)} disabled={!enabled || busy}>
            {["neutral", "happy", "sad", "angry", "annoyed", "smirk", "thinking", "surprised", "embarrassed", "concerned"].map((value) => <option key={value}>{value}</option>)}
          </select>
        </label>
        <label>
          Test gesture
          <select value={gesture} onChange={(event) => setGesture(event.target.value)} disabled={!enabled || busy}>
            {["greeting", "agreement", "disagreement", "question", "explanation", "thinking", "surprise", "frustration", "farewell", "shrug", "talk"].map((value) => <option key={value}>{value}</option>)}
          </select>
        </label>
        <label>
          Motion intensity {motionIntensity.toFixed(1)}
          <input min="0" max="1" step="0.1" type="range" value={motionIntensity} onChange={(event) => setMotionIntensity(Number(event.target.value))} disabled={!enabled || busy} />
        </label>
        <button onClick={() => void run(() => sendAvatarTestPhrase({ text: phrase, emotion }), "Test phrase queued.")} disabled={!enabled || busy || !phrase.trim()}>Send test phrase</button>
        <button onClick={() => void run(() => sendAvatarTestEmotion({ emotion, intensity: 1 }), "Emotion sent.")} disabled={!enabled || busy}>Send emotion</button>
        <button onClick={() => void run(() => sendAvatarTestGesture({ gesture, intensity: motionIntensity, interrupt: true }), "Gesture sent.")} disabled={!enabled || busy}>Send test gesture</button>
        <button className="secondary" onClick={() => void run(stopAvatar, "Motion reset sent.")} disabled={!enabled || busy}>Reset motion</button>
      </div>
      {message && <div className="notice">{message}</div>}
    </section>
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
