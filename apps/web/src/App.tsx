import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getEvents,
  getSettings,
  getStatus,
  sendChatMessage,
  updateRuntimeSettings,
  WS_EVENTS_URL,
} from "./api";
import type {
  BackendEvent,
  ChatMessage,
  EventLevel,
  PublicSettings,
  StatusResponse,
} from "./types";

type Tab = "chat" | "events" | "settings";
type WsState = "connected" | "disconnected" | "reconnecting";
type LevelFilter = "all" | EventLevel;

const SESSION_ID = "default";

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

        {activeTab === "chat" && <ChatPage onRefreshEvents={refreshEvents} />}
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

function ChatPage({ onRefreshEvents }: { onRefreshEvents: () => Promise<void> }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    listRef.current?.scrollTo({
      top: listRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

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
              </div>
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
    </section>
  );
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
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (settings) {
      setModel(settings.model);
      setPersonality(settings.personality);
    }
  }, [settings]);

  const saveSettings = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const nextSettings = await updateRuntimeSettings({ model, personality });
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
