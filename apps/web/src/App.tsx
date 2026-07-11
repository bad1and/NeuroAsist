import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getEvents,
  getSettings,
  getStatus,
  getVoiceTtsStatus,
  resolveApiUrl,
  sendChatMessage,
  sendVoiceMessage,
  updateRuntimeSettings,
  voiceWebSocketUrl,
  WS_EVENTS_URL,
} from "./api";
import type {
  BackendEvent,
  ChatMessage,
  EventLevel,
  PublicSettings,
  StatusResponse,
  VoiceChatResponse,
  VoiceTtsStatusResponse,
} from "./types";
import type { VoiceServerEvent } from "./types";
import { TTSStreamPlayer, VoiceSocketClient } from "./voice-live";

type Tab = "chat" | "events" | "settings";
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
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [events, setEvents] = useState<BackendEvent[]>([]);
  const [wsState, setWsState] = useState<WsState>("disconnected");
  const [statusError, setStatusError] = useState<string | null>(null);

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

      <main className="workspace">
        <nav className="tabs" aria-label="Primary">
          <button
            className={activeTab === "chat" ? "active" : ""}
            onClick={() => setActiveTab("chat")}
          >
            Chat
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
            onRefreshEvents={refreshEvents}
          />
        )}
        {activeTab === "events" && (
          <EventsPage events={events} onRefreshEvents={refreshEvents} />
        )}
        {activeTab === "settings" && (
          <SettingsPage
            settings={settings}
            onSettingsChanged={(nextSettings) => {
              setSettings(nextSettings);
              void refreshOverview();
              void refreshEvents();
            }}
          />
        )}
      </main>
    </div>
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
  onRefreshEvents,
}: {
  events: BackendEvent[];
  settings: PublicSettings | null;
  onRefreshEvents: () => Promise<void>;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const recordTimeoutRef = useRef<number | null>(null);
  const handledVoiceEventIdsRef = useRef<Set<string>>(new Set());
  const activeAudioRef = useRef<HTMLAudioElement | null>(null);
  const liveSocketRef = useRef<VoiceSocketClient | null>(null);
  const livePlayerRef = useRef<TTSStreamPlayer | null>(null);
  const liveAudioStartedRef = useRef(false);
  const liveMetadataRef = useRef({ emotion: "neutral", intent: "unknown" });

  const voiceSupported =
    typeof navigator !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia) &&
    typeof MediaRecorder !== "undefined";
  const browserSpeechSupported =
    typeof window !== "undefined" &&
    "speechSynthesis" in window &&
    "SpeechSynthesisUtterance" in window;

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
    [stopVoicePlayback],
  );

  const playMessageAudioTrack = useCallback(
    async (messageId: string, fallbackAudioUrl: string): Promise<boolean> => {
      const audio =
        document.querySelector<HTMLAudioElement>(
          `audio[data-message-id="${CSS.escape(messageId)}"]`,
        ) ?? new Audio(fallbackAudioUrl);

      stopVoicePlayback(audio);
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
    [stopVoicePlayback],
  );

  const speakTextInBrowser = useCallback(
    (text: string): boolean => {
      if (!browserSpeechSupported) {
        return false;
      }
      stopVoicePlayback();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = settings?.voice_language === "en" ? "en-US" : "ru-RU";
      window.speechSynthesis.speak(utterance);
      return true;
    },
    [browserSpeechSupported, settings?.voice_language, stopVoicePlayback],
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
          liveSocketRef.current?.clearActive();
          setLoading(false);
          setVoiceState("idle");
        },
        (playerError) => {
          livePlayerRef.current?.stop();
          liveSocketRef.current?.cancel();
          setError(playerError.message);
          setLoading(false);
          setVoiceState("error");
        },
        {
          prebufferSegments: settings?.voice_live_playback_prebuffer_segments ?? 2,
          prebufferMs: settings?.voice_live_playback_prebuffer_ms ?? 700,
        },
        (gapMs) => {
          liveSocketRef.current?.send("playback.underrun", { underrun_ms: gapMs });
        },
      );
    }
    return livePlayerRef.current;
  }, [settings?.voice_live_playback_prebuffer_ms, settings?.voice_live_playback_prebuffer_segments]);

  const ensureLiveVoice = useCallback(async () => {
    const player = ensureLivePlayer();
    if (!liveSocketRef.current) {
      const onEvent = (event: VoiceServerEvent) => {
        if (event.type === "voice.utterance.started") {
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
          livePlayerRef.current?.finish(event.utterance_id);
        } else if (event.type === "voice.utterance.cancelled") {
          liveSocketRef.current?.clearActive();
          setLoading(false);
          setVoiceState("idle");
        } else if (event.type === "voice.error") {
          livePlayerRef.current?.stop();
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
          if (segment.segment_id !== undefined) {
            void livePlayerRef.current?.enqueue(
              segment.utterance_id, segment.segment_id, audio,
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
        void playAudioUrl(resolvedAudioUrl);
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
  }, [browserSpeechSupported, events, messages, playAudioUrl, speakTextInBrowser]);

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
        },
      ]);
      await onRefreshEvents();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Chat failed");
    } finally {
      setLoading(false);
    }
  };

  const startRecording = async () => {
    if (!voiceSupported || loading || voiceState !== "idle") {
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
        void submitVoice(audio);
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
      return;
    }
    await startRecording();
  };

  const submitVoice = async (audio: Blob) => {
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

      {error && <div className="error-banner">{error}</div>}

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
        <span>
          {voiceSupported
            ? `voice: ${settings?.voice_language ?? "ru"}`
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
  onSettingsChanged,
}: {
  settings: PublicSettings | null;
  onSettingsChanged: (settings: PublicSettings) => void;
}) {
  const [model, setModel] = useState("");
  const [personality, setPersonality] = useState("");
  const [voiceLanguage, setVoiceLanguage] = useState("ru");
  const [voiceTtsVoice, setVoiceTtsVoice] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (settings) {
      setModel(settings.model);
      setPersonality(settings.personality);
      setVoiceLanguage(settings.voice_language);
      setVoiceTtsVoice(settings.voice_tts_voice);
    }
  }, [settings]);

  const saveSettings = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const nextSettings = await updateRuntimeSettings({
        model,
        personality,
        voice_language: voiceLanguage,
        voice_tts_voice: voiceTtsVoice,
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
        <InfoRow label="Chat history limit" value={String(settings.chat_history_limit)} />
        <InfoRow label="Log level" value={settings.log_level} />
        <InfoRow
          label="Voice"
          value={`${settings.voice_language} / STT ${settings.voice_stt_model} / TTS ${settings.voice_tts_enabled ? "on" : "off"}`}
        />
      </div>

      <div className="form-grid">
        <label>
          Model
          <select value={model} onChange={(event) => setModel(event.target.value)}>
            {settings.available_models.map((availableModel) => (
              <option key={availableModel} value={availableModel}>
                {availableModel}
              </option>
            ))}
          </select>
        </label>

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
          TTS voice
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

        <button onClick={saveSettings} disabled={saving}>
          {saving ? "Saving" : "Save runtime settings"}
        </button>
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
