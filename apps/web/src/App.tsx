import { FormEvent, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  Brain,
  ChevronDown,
  CircleAlert,
  Database,
  History,
  LayoutDashboard,
  MessageCircle,
  Mic,
  MicOff,
  MonitorCog,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
  SendHorizontal,
  Settings,
  SlidersHorizontal,
  Volume2,
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
  getConversationSession,
  getSettings,
  getConversationDebug,
  getStatus,
  getVoiceTtsStatus,
  getModels,
  getPronunciations,
  getSttTerms,
  installModel,
  interruptVoiceSession,
  isDesktopManaged,
  removeModel,
  reindexMemories,
  resetConversationSession,
  resetAllCompanionData,
  resolveApiUrl,
  saveDesktopApiKey,
  sendChatMessage,
  sendLiveTextMessage,
  searchTimeline,
  deleteTimelineRange,
  updateRuntimeSettings,
  updatePronunciations,
  updateSttTerms,
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
  AvatarPlacement,
  ChatMessage,
  EventLevel,
  PublicSettings,
  ManagedModel,
  StatusResponse,
  TimelineJournalItem,
  TimelineMessage,
  VoiceTtsStatusResponse,
  MemoryUpdate,
  ConversationDebug,
} from "./types";
import type { VoiceServerEvent } from "./types";
import { PlaybackCoordinator, TTSStreamPlayer, VoiceSocketClient } from "./voice-live";
import {
  canSelectAudioOutput,
  getAudioDeviceCatalog,
  setAudioElementOutput,
  type AudioDeviceCatalog,
  type AudioDeviceOption,
} from "./audio-devices";
import {
  BrowserVadRecorder,
  LIVE_MUTE_HOTKEY,
  PcmInputClient,
  type MicrophoneProfile,
} from "./vad";
import { JournalPage } from "./journal";
import { MemoryPage } from "./memory";
import { StatePage } from "./state";
import { OverviewPage } from "./overview";
import { configureAvatarPlacement, getDesktopRuntime, initialCoreStatus, listenForAvatarVisibility, listenForCoreStatus, restartDesktopCore, type CoreStatus } from "./desktop";
import { StartupScreen } from "./components/StartupScreen";
import { WindowChrome } from "./components/WindowChrome";
import { AppDialog } from "./components/AppDialog";
import { GuidedSttCapture } from "./stt-capture";
import { InAppAvatarHost } from "./components/InAppAvatarHost";

type AppView = "overview" | "chat" | "journal" | "memory" | "state" | "settings";
const SIDEBAR_COLLAPSED_STORAGE_KEY = "iris.sidebar.collapsed";
const CHAT_ERROR_AUTO_DISMISS_MS = 8_000;
type SettingsSection =
  | "conversation"
  | "avatar"
  | "voice"
  | "voice-devices"
  | "voice-recognition"
  | "voice-advanced"
  | "memory"
  | "system-overview"
  | "models"
  | "backups"
  | "maintenance"
  | "events";
type RuntimeSettingsPatch = Parameters<typeof updateRuntimeSettings>[0];
type AutoSaveStatus = "idle" | "saving" | "saved" | "error";
type LiveConversationSettings = Pick<
  PublicSettings,
  | "live_conversation_enabled"
  | "live_conversation_participant_mode"
  | "live_conversation_engagement"
  | "live_conversation_initiative"
  | "live_conversation_address_strictness"
  | "live_conversation_interruption_sensitivity"
  | "live_conversation_pause_tolerance"
  | "live_conversation_emotion_expression"
  | "live_conversation_mood_recovery"
  | "live_conversation_recent_event_weight"
  | "live_conversation_echo_mode"
>;
type WsState = "connected" | "disconnected" | "reconnecting";
type LevelFilter = "all" | EventLevel;
type VoiceState = "idle" | "recording" | "transcribing" | "thinking" | "speaking" | "stopping" | "error";

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

function useRuntimeSettingsAutosave(onSettingsChanged: (settings: PublicSettings) => void) {
  const pendingPatchRef = useRef<RuntimeSettingsPatch>({});
  const failedPatchRef = useRef<RuntimeSettingsPatch | null>(null);
  const rollbackRef = useRef<Array<() => void>>([]);
  const runningRef = useRef(false);
  const [status, setStatus] = useState<AutoSaveStatus>("idle");

  const drain = useCallback(async () => {
    if (runningRef.current || Object.keys(pendingPatchRef.current).length === 0) {
      return;
    }

    runningRef.current = true;
    const patch = pendingPatchRef.current;
    const rollback = rollbackRef.current;
    pendingPatchRef.current = {};
    rollbackRef.current = [];
    setStatus("saving");

    try {
      const nextSettings = await updateRuntimeSettings(patch);
      failedPatchRef.current = null;
      onSettingsChanged(nextSettings);
      setStatus("saved");
    } catch {
      failedPatchRef.current = patch;
      rollback.forEach((restore) => restore());
      setStatus("error");
    } finally {
      runningRef.current = false;
      if (Object.keys(pendingPatchRef.current).length > 0) {
        void drain();
      }
    }
  }, [onSettingsChanged]);

  const save = useCallback((patch: RuntimeSettingsPatch, rollback?: () => void) => {
    pendingPatchRef.current = { ...pendingPatchRef.current, ...patch };
    if (rollback) {
      rollbackRef.current.push(rollback);
    }
    void drain();
  }, [drain]);

  const retry = useCallback(() => {
    if (!failedPatchRef.current) return;
    pendingPatchRef.current = { ...failedPatchRef.current, ...pendingPatchRef.current };
    failedPatchRef.current = null;
    void drain();
  }, [drain]);

  return { save, retry, status };
}

function AutoSaveStatus({ status, onRetry }: { status: AutoSaveStatus; onRetry: () => void }) {
  if (status === "saving") return <span className="settings-save-status is-saving" role="status">Сохраняем…</span>;
  if (status === "error") {
    return <span className="settings-save-status is-error" role="alert">Не удалось сохранить <button type="button" onClick={onRetry}>Повторить</button></span>;
  }
  if (status === "saved") return <span className="settings-save-status is-saved" role="status">Сохранено</span>;
  return null;
}

function SettingsSwitch({
  checked,
  label,
  description,
  disabled,
  onChange,
}: {
  checked: boolean;
  label: string;
  description?: string;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="settings-switch-row">
      <span className="settings-switch-copy">
        <strong>{label}</strong>
        {description && <small>{description}</small>}
      </span>
      <input
        className="settings-switch-input"
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="settings-switch" aria-hidden="true"><span /></span>
    </label>
  );
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

function isLiveVoiceTransportError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  return (
    error.message.includes("Live voice connection failed") ||
    error.message.includes("Voice WebSocket must be connected") ||
    error.message.includes("Live text requires backend TTS") ||
    // A closed HTTP body during /chat/live is a transport failure, not a
    // failed user message. Fall back to the ordinary /chat request so typing
    // remains reliable while the live socket/core reconnects.
    error.message.includes("incomplete chunked read") ||
    error.message.includes("peer closed connection") ||
    error.message.includes("Failed to fetch")
  );
}

function formatSttTerms(entries: Record<string, string[]>): string {
  return Object.entries(entries)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([canonical, aliases]) => `${canonical} = ${aliases.join(" | ")}`)
    .join("\n");
}

function parseSttTerms(value: string): Record<string, string[]> {
  return Object.fromEntries(
    value.split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const separator = line.indexOf("=");
        if (separator <= 0) throw new Error(`Некорректная строка словаря STT: ${line}`);
        const canonical = line.slice(0, separator).trim();
        const aliases = line.slice(separator + 1).split("|").map((item) => item.trim()).filter(Boolean);
        if (!canonical || aliases.length === 0) throw new Error(`Некорректная строка словаря STT: ${line}`);
        return [canonical, aliases];
      }),
  );
}

export default function App() {
  const desktopManaged = isDesktopManaged();
  const [coreStatus, setCoreStatus] = useState<CoreStatus>(initialCoreStatus);
  const [showStartup, setShowStartup] = useState(desktopManaged);
  const [retryingCore, setRetryingCore] = useState(false);
  const startupStartedAt = useRef(Date.now());
  const [activeView, setActiveView] = useState<AppView>("overview");
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === "true";
    } catch {
      return false;
    }
  });
  const menuToggleRef = useRef<HTMLButtonElement>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [avatarStatus, setAvatarStatus] = useState<AvatarStatusResponse | null>(null);
  const [avatarOverlay, setAvatarOverlay] = useState<AvatarOverlaySettings | null>(null);
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [events, setEvents] = useState<BackendEvent[]>([]);
  // A settings mutation is authoritative.  Do not allow an older polling
  // request to overwrite it after the user has switched avatar placement.
  const overviewRevision = useRef(0);
  const [wsState, setWsState] = useState<WsState>("disconnected");
  const [statusError, setStatusError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [startingSession, setStartingSession] = useState(false);
  const servicesReady = !desktopManaged || coreStatus === "ready";
  const setupRequired = Boolean(settings && !settings.api_key_configured && isDesktopManaged());

  useEffect(() => {
    let stop: (() => void) | undefined;
    void listenForCoreStatus((nextStatus) => {
      setCoreStatus(nextStatus);
      setRetryingCore(false);
      if (nextStatus !== "ready") setShowStartup(true);
    }).then((unlisten) => {
      stop = unlisten;
      if (desktopManaged) {
        void getDesktopRuntime().then((runtime) => {
          setCoreStatus(runtime.coreStatus);
          if (runtime.coreStatus !== "ready") setShowStartup(true);
        });
      }
    });
    return () => stop?.();
  }, [desktopManaged]);

  useEffect(() => {
    if (!desktopManaged || coreStatus !== "ready") return;
    const elapsed = Date.now() - startupStartedAt.current;
    const timer = window.setTimeout(() => setShowStartup(false), Math.max(0, 2000 - elapsed));
    return () => window.clearTimeout(timer);
  }, [coreStatus, desktopManaged]);

  const retryCore = async () => {
    setRetryingCore(true);
    setCoreStatus("starting");
    setShowStartup(true);
    startupStartedAt.current = Date.now();
    try {
      const runtime = await restartDesktopCore();
      setCoreStatus(runtime.coreStatus);
    } catch {
      setCoreStatus("failed");
      setRetryingCore(false);
    }
  };

  const refreshEvents = useCallback(async () => {
    try {
      const payload = await getEvents(100);
      setEvents((current) => dedupeEvents([...current, ...payload.events]));
    } catch {
      // The connection indicator already communicates backend availability.
    }
  }, []);

  const refreshOverview = useCallback(async () => {
    const revision = ++overviewRevision.current;
    try {
      const [nextStatus, nextSettings, nextAvatarStatus, nextAvatarOverlay] = await Promise.all([
        getStatus(),
        getSettings(),
        getAvatarStatus().catch(() => null),
        getAvatarOverlay().catch(() => null),
      ]);
      if (revision !== overviewRevision.current) return;
      setStatus(nextStatus);
      setSettings(nextSettings);
      setAvatarStatus(nextAvatarStatus);
      setAvatarOverlay(nextAvatarOverlay);
      setStatusError(null);
    } catch (error) {
      if (revision !== overviewRevision.current) return;
      setStatusError(error instanceof Error ? error.message : "Сервис недоступен");
    }
  }, []);

  useEffect(() => {
    if (!servicesReady) return;
    void refreshOverview();
    void refreshEvents();
    const timer = window.setInterval(() => {
      void refreshOverview();
    }, 10000);
    return () => window.clearInterval(timer);
  }, [refreshEvents, refreshOverview, servicesReady]);

  useEffect(() => {
    try {
      window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, String(sidebarCollapsed));
    } catch {
      // The sidebar remains usable when storage is unavailable.
    }
  }, [sidebarCollapsed]);

  useEffect(() => {
    if (!navigationOpen) return;
    const focusMenuButton = window.setTimeout(() => menuToggleRef.current?.focus(), 0);
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setNavigationOpen(false);
      window.setTimeout(() => menuToggleRef.current?.focus(), 0);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.clearTimeout(focusMenuButton);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [navigationOpen]);

  useEffect(() => {
    let stop: (() => void) | undefined;
    void listenForAvatarVisibility(() => {
      void refreshOverview();
    }).then((unlisten) => {
      stop = unlisten;
    });
    return () => stop?.();
  }, [refreshOverview]);

  useEffect(() => {
    if (!servicesReady || !settings) return;
    void configureAvatarPlacement(settings.avatar_placement).catch(() => {
      // Settings remain usable in a browser or when an optional avatar build
      // is unavailable. Avatar diagnostics show the connection state.
    });
  }, [servicesReady, settings?.avatar_placement]);

  const startFreshSession = useCallback(async () => {
    setStartingSession(true);
    try {
      const session = await resetConversationSession();
      setSessionId(session.session_id);
    } finally {
      setStartingSession(false);
    }
  }, []);

  const resumeSession = useCallback(async () => {
    setStartingSession(true);
    try {
      const session = await getConversationSession();
      setSessionId(session.session_id);
    } finally {
      setStartingSession(false);
    }
  }, []);

  useEffect(() => {
    if (!servicesReady || !settings || setupRequired || sessionId || startingSession) return;
    void resumeSession().catch((error) => {
      setStatusError(error instanceof Error ? error.message : "Не удалось восстановить сессию.");
    });
  }, [servicesReady, settings, setupRequired, sessionId, startingSession, resumeSession]);

  useEffect(() => {
    if (!servicesReady) return;
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
  }, [refreshEvents, servicesReady]);

  if (showStartup) {
    return <StartupScreen status={coreStatus} retrying={retryingCore} onRetry={() => void retryCore()} />;
  }

  if (setupRequired) {
    return <div className="app-shell setup-shell"><SetupWizard onComplete={refreshOverview} /></div>;
  }

  const closeNavigation = () => {
    setNavigationOpen((current) => {
      if (current) window.setTimeout(() => menuToggleRef.current?.focus(), 0);
      return false;
    });
  };

  const toggleNavigation = () => {
    setNavigationOpen((current) => {
      const next = !current;
      if (!next) window.setTimeout(() => menuToggleRef.current?.focus(), 0);
      return next;
    });
  };

  const switchView = (view: AppView) => {
    setActiveView(view);
    closeNavigation();
  };
  return (
    <div className={`app-shell${sidebarCollapsed ? " is-sidebar-collapsed" : ""}`}>
      <Sidebar
        activeView={activeView}
        isOpen={navigationOpen}
        isCollapsed={sidebarCollapsed}
        onNavigate={switchView}
        onToggleCollapsed={() => setSidebarCollapsed((value) => !value)}
      />
      {navigationOpen && <button className="navigation-scrim" type="button" aria-label="Закрыть меню" onClick={closeNavigation} />}
      <WindowChrome
        title=""
        navigationOpen={navigationOpen}
        navigationButtonRef={menuToggleRef}
        onOpenNavigation={toggleNavigation}
      />
      <section className="app-content">
        <main className={`workspace workspace-${activeView}`}>
          {activeView === "overview" && (
            <OverviewPage
              status={status}
              avatarStatus={avatarStatus}
              onOpenChat={() => switchView("chat")}
              onOpenHistory={() => switchView("journal")}
              onOpenMemory={() => switchView("memory")}
              onOpenSettings={() => switchView("settings")}
            />
          )}
          <div className="chat-view" hidden={activeView !== "chat"}>
            <ChatPage
              key={sessionId ?? "starting"}
              sessionId={sessionId}
              sessionStarting={startingSession}
              isActive={activeView === "chat"}
              events={events}
              settings={settings}
              avatarStatus={avatarStatus}
              showInAppAvatar={settings?.avatar_placement === "in_app" && (settings.avatar_in_app_visible ?? true)}
              onRefreshEvents={refreshEvents}
              onOpenMemory={() => switchView("memory")}
              onStartNewDialog={startFreshSession}
            />
          </div>
          {activeView === "journal" && <JournalPage />}
          {activeView === "memory" && <MemoryPage />}
          {activeView === "state" && <StatePage events={events} />}
          {activeView === "settings" && (
            <SettingsPage
              settings={settings}
              avatarStatus={avatarStatus}
              avatarOverlay={avatarOverlay}
              events={events}
              onRefreshEvents={refreshEvents}
              onRefreshAvatar={refreshOverview}
              onAvatarOverlayChanged={(nextOverlay) => {
                overviewRevision.current += 1;
                setAvatarOverlay(nextOverlay);
              }}
              onSettingsChanged={(nextSettings) => {
                overviewRevision.current += 1;
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
        <span className="eyebrow">Первичная настройка</span>
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
  { id: "overview", label: "Обзор", icon: LayoutDashboard },
  { id: "chat", label: "Диалог", icon: MessageCircle },
  { id: "journal", label: "История", icon: History },
  { id: "memory", label: "Память", icon: Brain },
  { id: "state", label: "Состояние", icon: SlidersHorizontal },
];

function Sidebar({
  activeView,
  isOpen,
  isCollapsed,
  onNavigate,
  onToggleCollapsed,
}: {
  activeView: AppView;
  isOpen: boolean;
  isCollapsed: boolean;
  onNavigate: (view: AppView) => void;
  onToggleCollapsed: () => void;
}) {
  return (
    <aside id="main-sidebar" className={`sidebar${isOpen ? " is-open" : ""}`} aria-label="Основная навигация">
      <div className="sidebar-brand" data-tauri-drag-region>
        <img className="brand-logo brand-logo-wordmark" src="/brand/iris-wordmark-light.svg" alt="Iris" />
        <img className="brand-logo brand-logo-mark" src="/brand/iris-mark-light.svg" alt="" aria-hidden="true" />
        <span className="brand-alias" data-tauri-drag-region aria-hidden="true">ириска<sup>*</sup></span>
      </div>
      <nav className="sidebar-nav" aria-label="Разделы приложения">
        {MAIN_NAVIGATION.map(({ id, label, icon: Icon }) => (
          <NavigationButton key={id} icon={Icon} label={label} active={activeView === id} compact={isCollapsed} onClick={() => onNavigate(id)} />
        ))}
      </nav>
      <div className="sidebar-footer">
        <div className="sidebar-footer-row">
          <NavigationButton icon={Settings} label="Настройки" active={activeView === "settings"} compact={isCollapsed} onClick={() => onNavigate("settings")} />
          <button
            className="icon-button sidebar-collapse-toggle"
            type="button"
            aria-label={isCollapsed ? "Развернуть меню" : "Свернуть меню"}
            aria-pressed={isCollapsed}
            title={isCollapsed ? "Развернуть меню" : "Свернуть меню"}
            onClick={onToggleCollapsed}
          >
            {isCollapsed ? <PanelLeftOpen size={18} aria-hidden="true" /> : <PanelLeftClose size={18} aria-hidden="true" />}
          </button>
        </div>
      </div>
    </aside>
  );
}

function NavigationButton({
  icon: Icon,
  label,
  active,
  compact = false,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  active: boolean;
  compact?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      className={`navigation-button${active ? " is-active" : ""}`}
      aria-label={label}
      aria-current={active ? "page" : undefined}
      data-tooltip={compact ? label : undefined}
      title={compact ? label : undefined}
      onClick={onClick}
    >
      <Icon size={19} aria-hidden="true" />
      <span>{label}</span>
    </button>
  );
}

function ChatPage({
  sessionId,
  sessionStarting,
  isActive,
  events,
  settings,
  avatarStatus,
  showInAppAvatar,
  onRefreshEvents,
  onOpenMemory,
  onStartNewDialog,
}: {
  sessionId: string | null;
  sessionStarting: boolean;
  isActive: boolean;
  events: BackendEvent[];
  settings: PublicSettings | null;
  avatarStatus: AvatarStatusResponse | null;
  showInAppAvatar: boolean;
  onRefreshEvents: () => Promise<void>;
  onOpenMemory: () => void;
  onStartNewDialog: () => Promise<void>;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [retryText, setRetryText] = useState<string | null>(null);
  const [memoryNotice, setMemoryNotice] = useState<string | null>(null);
  const [liveConversation, setLiveConversation] = useState(false);
  const [microphoneMuted, setMicrophoneMuted] = useState(false);
  const [conversationStatus, setConversationStatus] = useState("Микрофон включён");
  const [conversationDebug, setConversationDebug] = useState<ConversationDebug | null>(null);
  const [newDialogConfirmationOpen, setNewDialogConfirmationOpen] = useState(false);
  const [newDialogPending, setNewDialogPending] = useState(false);
  const listRef = useRef<HTMLDivElement | null>(null);
  const handledVoiceEventIdsRef = useRef<Set<string>>(new Set());
  const activeAudioRef = useRef<HTMLAudioElement | null>(null);
  const liveSocketRef = useRef<VoiceSocketClient | null>(null);
  const livePlayerRef = useRef<TTSStreamPlayer | null>(null);
  const vadRecorderRef = useRef<BrowserVadRecorder | null>(null);
  const pcmInputRef = useRef<PcmInputClient | null>(null);
  const playbackCoordinatorRef = useRef(new PlaybackCoordinator());
  const avatarOwnsAudioRef = useRef(false);
  const liveAudioStartedRef = useRef(false);
  const liveMetadataRef = useRef({ emotion: "neutral", intent: "unknown" });
  const pendingSpeakerLabelRef = useRef("Вы");
  const latestPlaybackSegmentRef = useRef("");
  const playbackSegmentTextsRef = useRef<string[]>([]);
  const activeVoiceGenerationRef = useRef<number | undefined>(undefined);
  const conversationStatusTimerRef = useRef<number | null>(null);

  const updateConversationStatus = useCallback((status: string, resetAfterMs?: number) => {
    if (conversationStatusTimerRef.current !== null) {
      window.clearTimeout(conversationStatusTimerRef.current);
      conversationStatusTimerRef.current = null;
    }
    setConversationStatus(status);
    if (resetAfterMs !== undefined) {
      conversationStatusTimerRef.current = window.setTimeout(() => {
        setConversationStatus("Микрофон включён");
        conversationStatusTimerRef.current = null;
      }, resetAfterMs);
    }
  }, []);

  useEffect(() => () => {
    if (conversationStatusTimerRef.current !== null) {
      window.clearTimeout(conversationStatusTimerRef.current);
    }
  }, []);

  useEffect(() => {
    if (!error) return;

    const visibleError = error;
    const visibleRetryText = retryText;
    const dismissTimer = window.setTimeout(() => {
      setError((currentError) => currentError === visibleError ? null : currentError);
      setRetryText((currentRetryText) => (
        currentRetryText === visibleRetryText ? null : currentRetryText
      ));
    }, CHAT_ERROR_AUTO_DISMISS_MS);

    return () => window.clearTimeout(dismissTimer);
  }, [error, retryText]);

  const showMemoryUpdates = useCallback((updates?: MemoryUpdate[]) => {
    const update = updates && updates.length ? updates[updates.length - 1] : undefined;
    if (!update || update.action !== "saved") return;
    setMemoryNotice(`Сохранено в памяти: ${update.predicate}.`);
  }, []);

  useEffect(() => {
      if (!sessionId) return;
      void getTimelineMessages(50, sessionId).then((payload) => {
      setMessages(payload.items
        .filter((message) => message.role === "user" || message.role === "assistant")
        .map((message) => ({ id: message.id, role: message.role as "user" | "assistant", content: message.content })));
    }).catch(() => {
      // The V0.4 compatibility backend may intentionally keep Timeline V2 disabled.
    });
  }, [sessionId]);

  useEffect(() => {
    if (!import.meta.env.DEV || !liveConversation || !settings?.conversation_diagnostics_enabled) {
      setConversationDebug(null);
      return;
    }
    let active = true;
    const refresh = () => {
      if (!sessionId) return;
      void getConversationDebug(sessionId)
        .then((snapshot) => { if (active) setConversationDebug(snapshot); })
        .catch(() => { if (active) setConversationDebug(null); });
    };
    refresh();
    const timer = window.setInterval(refresh, 2000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [liveConversation, sessionId, settings?.conversation_diagnostics_enabled]);

  const liveVoiceSupported =
    typeof navigator !== "undefined"
    && Boolean(navigator.mediaDevices?.getUserMedia)
    && typeof AudioWorkletNode !== "undefined";
  const browserSpeechSupported =
    typeof window !== "undefined" &&
    "speechSynthesis" in window &&
    "SpeechSynthesisUtterance" in window;
  const selectedInputDeviceId = settings?.voice_input_device_id ?? "";
  const selectedOutputDeviceId = settings?.voice_output_device_id ?? "";
  // A concrete output requires Web Audio/HTML audio routing. In that mode the
  // avatar remains visually in sync but its Unity AudioSource is muted by the
  // backend, so the browser is the only audible playback owner.
  const routeAvatarAudioThroughDesktop = Boolean(selectedOutputDeviceId && canSelectAudioOutput());
  const avatarOwnsAudio = Boolean(
    avatarStatus?.enabled
    && avatarStatus.client_count > 0
    && !routeAvatarAudioThroughDesktop,
  );

  useEffect(() => {
    avatarOwnsAudioRef.current = avatarOwnsAudio;
  }, [avatarOwnsAudio]);

  useEffect(() => {
    let cancelled = false;
    const applyOutput = async () => {
      try {
        if (activeAudioRef.current) {
          await setAudioElementOutput(activeAudioRef.current, selectedOutputDeviceId);
        }
        await livePlayerRef.current?.setOutputDevice(selectedOutputDeviceId);
      } catch (outputError) {
        if (!cancelled) {
          setError(outputError instanceof Error
            ? `Не удалось переключить вывод звука: ${outputError.message}`
            : "Не удалось переключить вывод звука");
        }
      }
    };
    void applyOutput();
    return () => { cancelled = true; };
  }, [selectedOutputDeviceId]);

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
    if (!sentOverLiveSocket && sessionId) {
      void interruptVoiceSession(sessionId, utteranceId).catch(() => undefined);
    }
  }, [sessionId, stopVoicePlayback]);

  const playMuteTone = useCallback((muted: boolean) => {
    try {
      const AudioContextConstructor = globalThis.AudioContext
        ?? (globalThis as typeof globalThis & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AudioContextConstructor) return;
      const context = new AudioContextConstructor();
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      const now = context.currentTime;
      oscillator.type = "sine";
      oscillator.frequency.setValueAtTime(muted ? 220 : 520, now);
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(0.025, now + 0.008);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.055);
      oscillator.connect(gain).connect(context.destination);
      oscillator.start(now);
      oscillator.stop(now + 0.06);
      oscillator.addEventListener("ended", () => { void context.close(); }, { once: true });
    } catch {
      // Audio feedback is optional and must never block microphone control.
    }
  }, []);

  const playAudioUrl = useCallback(
    async (audioUrl: string): Promise<boolean> => {
      stopVoicePlayback();
      const audio = new Audio(audioUrl);
      audio.playbackRate = 1;
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
        await setAudioElementOutput(audio, selectedOutputDeviceId);
        await audio.play();
        return true;
      } catch {
        if (activeAudioRef.current === audio) {
          activeAudioRef.current = null;
        }
        return false;
      }
    },
    [selectedOutputDeviceId, settings?.voice_playback_rate, stopVoicePlayback],
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
          playbackSegmentTextsRef.current = [];
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
          playbackRate: 1,
          startLeadMs: settings?.voice_live_playback_start_lead_ms ?? 30,
          outputDeviceId: selectedOutputDeviceId,
        },
        (gapMs) => {
          liveSocketRef.current?.send("playback.underrun", { underrun_ms: gapMs });
        },
        (text) => {
          liveSocketRef.current?.send("playback.segment.finished", {
            text,
            generation: activeVoiceGenerationRef.current,
          });
        },
        (segmentId, decodeMs) => {
          liveSocketRef.current?.send("playback.segment.decoded", {
            segment_id: segmentId,
            decode_ms: decodeMs,
          });
        },
      );
    }
    livePlayerRef.current.updateOptions({
      prebufferSegments: settings?.voice_live_playback_prebuffer_segments ?? 1,
      prebufferMs: settings?.voice_live_playback_prebuffer_ms ?? 0,
      playbackRate: 1,
      startLeadMs: settings?.voice_live_playback_start_lead_ms ?? 30,
      outputDeviceId: selectedOutputDeviceId,
    });
    return livePlayerRef.current;
  }, [
    settings?.voice_live_playback_prebuffer_ms,
    settings?.voice_live_playback_prebuffer_segments,
    settings?.voice_live_playback_start_lead_ms,
    selectedOutputDeviceId,
  ]);

  const ensureLiveVoice = useCallback(async () => {
    if (!sessionId) throw new Error("Сессия ещё создаётся");
    const player = ensureLivePlayer();
    if (!liveSocketRef.current) {
      const onEvent = (event: VoiceServerEvent) => {
        if (event.type === "voice.utterance.started") {
          playbackSegmentTextsRef.current = [];
          activeVoiceGenerationRef.current = event.generation;
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
          latestPlaybackSegmentRef.current = event.text ?? "";
          if (event.text) playbackSegmentTextsRef.current.push(event.text);
          liveSocketRef.current?.send("playback.segment.started", {
            text: event.text ?? "",
            generation: event.generation,
          });
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
        voiceWebSocketUrl(sessionId),
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
  }, [ensureLivePlayer, sessionId, showMemoryUpdates, speakTextInBrowser, stopVoicePlayback]);

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

  useLayoutEffect(() => {
    // ChatPage remains mounted while another section is open so the live
    // connection survives navigation.  Its list can therefore receive its
    // history while hidden; scroll only after it becomes visible and has a
    // measurable layout.
    if (!isActive || messages.length === 0) return;
    listRef.current?.scrollTo({
      top: listRef.current.scrollHeight,
      behavior: "auto",
    });
  }, [isActive, messages.length]);

  useEffect(() => {
    if (!isActive) return;
    listRef.current?.scrollTo({
      top: listRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [isActive, messages]);

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
    if (!text || !sessionId) {
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
        const response = await sendLiveTextMessage(sessionId, text, userMessage.id);
        if (response.message_id) {
          setMessages((current) => current.map((message) =>
            message.id === userMessage.id ? { ...message, id: response.message_id! } : message,
          ));
        }
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
      const response = await sendChatMessage(sessionId, text, userMessage.id);
      showMemoryUpdates(response.memory_updates);
      setMessages((current) => [
        ...current.map((message) => message.id === userMessage.id && response.message_id
          ? { ...message, id: response.message_id }
          : message),
        {
          id: response.assistant_message_id ?? crypto.randomUUID(),
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
      // A transport failure is ambiguous: the server may already have
      // accepted the client id.  Keep the optimistic user bubble so retry
      // cannot silently erase a durable turn.
    } finally {
      if (!liveSocketRef.current?.activeUtteranceId) {
        setLoading(false);
        setVoiceState("idle");
      }
    }
  };

  const toggleLive = async () => {
    if (!sessionId) return;
    if (liveConversation) {
      vadRecorderRef.current?.stop();
      pcmInputRef.current?.close();
      pcmInputRef.current = null;
      vadRecorderRef.current = null;
      setMicrophoneMuted(false);
      setLiveConversation(false);
      setVoiceState("idle");
      updateConversationStatus("Live выключен");
      return;
    }
    vadRecorderRef.current?.stop();
    pcmInputRef.current?.close();
    pcmInputRef.current = null;
    vadRecorderRef.current = null;
    setMicrophoneMuted(false);
    setLiveConversation(false);
    try {
      await ensureLiveVoice();
      const input = new PcmInputClient(voiceInputWebSocketUrl(sessionId, 3), (event) => {
        if (event.type === "voice.input.transcript" && event.transcript) {
          setMessages((current) => [...current, {
            id: crypto.randomUUID(),
            role: "user",
            content: event.transcript!,
            speakerLabel: pendingSpeakerLabelRef.current,
          }]);
          if (!event.observation_only) {
            setVoiceState("thinking");
            updateConversationStatus("Iris отвечает");
          }
        } else if (event.type === "voice.input.speech_started") {
          updateConversationStatus("Слышу вас");
        } else if (event.type === "voice.input.finalizing") {
          updateConversationStatus("Распознаю");
        } else if (event.type === "conversation.turn_candidate") {
          updateConversationStatus("Проверяю конец фразы");
        } else if (event.type === "conversation.turn_completed") {
          updateConversationStatus("Распознаю");
        } else if (event.type === "conversation.phase" && event.phase) {
          const labels: Record<string, string> = {
            listening: "Микрофон включён",
            endpoint_pending: "Жду продолжения",
            transcribing: "Распознаю",
            deciding: "Думаю, стоит ли отвечать",
            generating: "Iris отвечает",
            speaking: "Iris отвечает",
          };
          updateConversationStatus(labels[event.phase] ?? "Микрофон включён");
        } else if (event.type === "conversation.observation") {
          pendingSpeakerLabelRef.current = event.speaker_role === "other"
            ? "Собеседник"
            : event.speaker_role === "unknown"
              ? "Неизвестный голос"
              : "Вы";
        } else if (event.type === "conversation.decision") {
          updateConversationStatus(event.action === "respond" || event.action === "backchannel"
            ? "Iris отвечает"
            : "Iris решила промолчать");
        } else if (event.type === "conversation.silent") {
          updateConversationStatus("Iris решила промолчать", 1800);
        } else if (event.type === "conversation.echo_rejected") {
          updateConversationStatus("Микрофон включён");
        } else if (event.type === "conversation.noise_ignored") {
          updateConversationStatus("Короткий шум пропущен", 900);
        } else if (event.type === "conversation.reaction") {
          updateConversationStatus(event.initiative ? "Iris вступает в разговор" : "Iris реагирует");
        } else if (event.type === "conversation.deferred") {
          updateConversationStatus("Iris подождёт подходящую паузу");
        } else if (event.type === "conversation.cancelled") {
          updateConversationStatus("Микрофон включён");
        } else if (event.type === "voice.input.error") {
          setError(event.message ?? "Не удалось обработать голосовой ввод");
        }
      });
      pcmInputRef.current = input;
      const recorder = new BrowserVadRecorder();
      vadRecorderRef.current = recorder;
      const capture = await recorder.start(
        (pcm16) => pcmInputRef.current?.sendPcm(pcm16),
        (_nextState, event) => {
          if (event === "speech_started") {
            interruptAssistantSpeech();
            setVoiceState("recording");
            updateConversationStatus("Слышу вас");
          } else if (event === "speech_ended") {
            setVoiceState("transcribing");
          }
        },
        "live",
        selectedInputDeviceId,
      );
      await input.connect(
        capture.sampleRate,
        settings?.voice_language ?? "ru",
        capture,
      );
      setLiveConversation(true);
      setMicrophoneMuted(false);
      updateConversationStatus("Микрофон включён");
    } catch (vadError) {
      vadRecorderRef.current?.stop();
      pcmInputRef.current?.close();
      vadRecorderRef.current = null;
      pcmInputRef.current = null;
      setMicrophoneMuted(false);
      setError(vadError instanceof Error ? vadError.message : "Live-режим недоступен");
      setLiveConversation(false);
    }
  };

  const toggleMicrophoneMute = useCallback(() => {
    if (!liveConversation || !vadRecorderRef.current) return;
    const nextMuted = !microphoneMuted;
    vadRecorderRef.current.setMuted(nextMuted);
    setMicrophoneMuted(nextMuted);
    playMuteTone(nextMuted);
    updateConversationStatus(nextMuted ? "Микрофон выключен" : "Микрофон включён");
  }, [liveConversation, microphoneMuted, playMuteTone, updateConversationStatus]);

  useEffect(() => {
    const handleMuteHotkey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== LIVE_MUTE_HOTKEY || event.repeat || !liveConversation) return;
      const target = event.target as HTMLElement | null;
      if (target?.isContentEditable || (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))) return;
      event.preventDefault();
      toggleMicrophoneMute();
    };
    window.addEventListener("keydown", handleMuteHotkey);
    return () => window.removeEventListener("keydown", handleMuteHotkey);
  }, [liveConversation, toggleMicrophoneMute]);

  const startNewDialog = async () => {
    if (!sessionId || newDialogPending) return;
    setNewDialogPending(true);
    setError(null);
    try {
      // A new session must not inherit a live microphone stream or an answer
      // that was still playing in the previous dialog.
      vadRecorderRef.current?.stop();
      pcmInputRef.current?.close();
      pcmInputRef.current = null;
      vadRecorderRef.current = null;
      setLiveConversation(false);
      setMicrophoneMuted(false);
      interruptAssistantSpeech();
      await onStartNewDialog();
      setNewDialogConfirmationOpen(false);
    } catch (newDialogError) {
      setError(newDialogError instanceof Error ? newDialogError.message : "Не удалось начать новый диалог.");
    } finally {
      setNewDialogPending(false);
    }
  };

  return (
    <section className={`panel chat-panel${showInAppAvatar && isActive ? " has-in-app-avatar" : ""}`}>
      {showInAppAvatar && isActive && <InAppAvatarHost />}
      <div className="chat-content">
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
            <div className="message-role">{message.role === "user" ? message.speakerLabel ?? "Вы" : "Iris"}</div>
            <p>{message.content}</p>
            {message.ttsError && <div className="message-error">{message.ttsError}</div>}
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
            disabled={!sessionId || sessionStarting || loading || draft.trim().length === 0}
            aria-label={sessionStarting ? "Подготавливаем сессию" : loading ? "Отправка сообщения" : "Отправить сообщение"}
            title={sessionStarting ? "Подготавливаем сессию" : loading ? "Отправка сообщения" : "Отправить сообщение"}
          >
            <SendHorizontal size={18} aria-hidden="true" />
          </button>
        </form>

        <div className="voice-controls">
          <button
            className={liveConversation ? "voice-button recording" : "secondary voice-button"}
            disabled={!liveVoiceSupported || voiceState === "stopping"}
            onClick={() => void toggleLive()}
            title="Непрерывный live-диалог с автоматическими паузами и перебиваниями"
            type="button"
          >
            <Mic size={18} aria-hidden="true" />
            {liveConversation ? "Live: вкл." : "Live"}
          </button>
          {liveConversation && (
            <button
              className={microphoneMuted ? "secondary voice-button muted" : "secondary voice-button"}
              aria-label={microphoneMuted ? "Включить микрофон" : "Выключить микрофон"}
              aria-pressed={microphoneMuted}
              onClick={toggleMicrophoneMute}
              title={`Микрофон: ${microphoneMuted ? "включить" : "выключить"} · клавиша ${LIVE_MUTE_HOTKEY.toUpperCase()}`}
              type="button"
            >
              {microphoneMuted ? <MicOff size={18} aria-hidden="true" /> : <Mic size={18} aria-hidden="true" />}
            </button>
          )}
          <button
            className="secondary voice-button new-dialog-button"
            disabled={!sessionId || sessionStarting || newDialogPending || voiceState === "recording" || voiceState === "transcribing"}
            onClick={() => setNewDialogConfirmationOpen(true)}
            title="Очистить текущий чат и начать новый разговор"
            type="button"
          >
            Новый диалог
          </button>
          {(liveConversation || voiceState !== "idle" || !liveVoiceSupported) && <span>
            {liveVoiceSupported ? conversationStatus : "Live-аудио недоступно"}
          </span>}
        </div>
        {import.meta.env.DEV && liveConversation && conversationDebug && (
          <details className="conversation-debug">
            <summary>Диагностика живого разговора</summary>
            <dl>
              <div><dt>Phase / generation</dt><dd>{conversationDebug.phase} / {conversationDebug.generation}</dd></div>
              <div><dt>Decision</dt><dd>{conversationDebug.last_decision?.action ?? "—"} · {conversationDebug.last_decision?.reason ?? "—"} · {conversationDebug.last_decision_source ?? "—"}</dd></div>
              <div><dt>Speaker</dt><dd>{conversationDebug.last_speaker_estimate?.role ?? "—"} ({conversationDebug.last_speaker_estimate?.confidence?.toFixed(2) ?? "—"})</dd></div>
              <div><dt>Detector</dt><dd>{conversationDebug.turn_detector?.provider ?? "—"}{conversationDebug.turn_detector?.fallback ? " · fallback" : ""}</dd></div>
              <div><dt>Budget</dt><dd>{Math.round((conversationDebug.speech_budget?.iris_share_2m ?? 0) * 100)}% · {conversationDebug.speech_budget?.initiative_count_10m ?? 0}/2</dd></div>
              <div><dt>Deferred / tasks</dt><dd>{conversationDebug.deferred_reactions?.length ?? 0} / {conversationDebug.active_tasks?.length ?? 0}</dd></div>
            </dl>
          </details>
        )}
      </div>
      <AppDialog
        open={newDialogConfirmationOpen}
        title="Начать новый диалог?"
        description="Все сообщения и сводки текущего диалога будут удалены без возможности восстановления. Долгосрочная память Iris останется."
        onClose={() => !newDialogPending && setNewDialogConfirmationOpen(false)}
      >
        <div className="dialog-actions">
          <button className="secondary" type="button" disabled={newDialogPending} onClick={() => setNewDialogConfirmationOpen(false)}>
            Отмена
          </button>
          <button className="danger-button" type="button" disabled={newDialogPending} onClick={() => void startNewDialog()}>
            {newDialogPending ? "Создаю…" : "Начать новый диалог"}
          </button>
        </div>
      </AppDialog>
      </div>
    </section>
  );
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
  avatarOverlay,
  events,
  onRefreshEvents,
  onRefreshAvatar,
  onAvatarOverlayChanged,
  onSettingsChanged,
}: {
  settings: PublicSettings | null;
  avatarStatus: AvatarStatusResponse | null;
  avatarOverlay: AvatarOverlaySettings | null;
  events: BackendEvent[];
  onRefreshEvents: () => Promise<void>;
  onRefreshAvatar: () => Promise<void>;
  onAvatarOverlayChanged: (overlay: AvatarOverlaySettings | null) => void;
  onSettingsChanged: (settings: PublicSettings) => void;
}) {
  const [activeSection, setActiveSection] = useState<SettingsSection>("conversation");
  const [voiceLanguage, setVoiceLanguage] = useState("ru");
  const [voiceMicrophoneProfile, setVoiceMicrophoneProfile] = useState<MicrophoneProfile>("balanced");
  const [voiceInputDeviceId, setVoiceInputDeviceId] = useState("");
  const [voiceOutputDeviceId, setVoiceOutputDeviceId] = useState("");
  const [audioDevices, setAudioDevices] = useState<AudioDeviceCatalog>({
    inputs: [],
    outputs: [],
    canEnumerate: false,
    canSelectOutput: false,
  });
  const [audioDevicesLoading, setAudioDevicesLoading] = useState(false);
  const [audioDevicesMessage, setAudioDevicesMessage] = useState<string | null>(null);
  const [voiceTtsVoice, setVoiceTtsVoice] = useState("");
  const [voiceTtsStyle, setVoiceTtsStyle] = useState("auto");
  const [voiceExpressionLevel, setVoiceExpressionLevel] = useState("natural");
  const [pronunciationsText, setPronunciationsText] = useState("");
  const [sttTermsText, setSttTermsText] = useState("");
  const [voicePlaybackRate, setVoicePlaybackRate] = useState(1);
  const [prebufferSegments, setPrebufferSegments] = useState(1);
  const [prebufferMs, setPrebufferMs] = useState(0);
  const [memoryMode, setMemoryMode] = useState("balanced");
  const [memoryIncognito, setMemoryIncognito] = useState(false);
  const [liveSettings, setLiveSettings] = useState<LiveConversationSettings>({
    live_conversation_enabled: true,
    live_conversation_participant_mode: "one_to_one",
    live_conversation_engagement: "balanced",
    live_conversation_initiative: "rare",
    live_conversation_address_strictness: "balanced",
    live_conversation_interruption_sensitivity: "balanced",
    live_conversation_pause_tolerance: "natural",
    live_conversation_emotion_expression: "natural",
    live_conversation_mood_recovery: "natural",
    live_conversation_recent_event_weight: "balanced",
    live_conversation_echo_mode: "auto",
  });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [showSttCapture, setShowSttCapture] = useState(false);
  const autosaveTimersRef = useRef<Partial<Record<SettingsSection, number>>>({});
  // Settings are polled by the app shell.  Once this form is open, a polling
  // response must not replace a value the person has just selected before
  // they get a chance to press Save (most visibly the participant mode).
  const hasInitialSettings = useRef(false);
  const autosave = useRuntimeSettingsAutosave(onSettingsChanged);

  const applySettingsToForm = useCallback((nextSettings: PublicSettings) => {
    setVoiceLanguage(nextSettings.voice_language);
    setVoiceMicrophoneProfile(nextSettings.voice_microphone_profile ?? "balanced");
    setVoiceInputDeviceId(nextSettings.voice_input_device_id ?? "");
    setVoiceOutputDeviceId(nextSettings.voice_output_device_id ?? "");
    setVoiceTtsVoice(nextSettings.voice_tts_voice);
    setVoiceTtsStyle(nextSettings.voice_tts_style);
    setVoiceExpressionLevel(nextSettings.voice_tts_expression_level);
    setVoicePlaybackRate(nextSettings.voice_playback_rate);
    setPrebufferSegments(nextSettings.voice_live_playback_prebuffer_segments);
    setPrebufferMs(nextSettings.voice_live_playback_prebuffer_ms);
    setMemoryMode(nextSettings.memory_mode);
    setMemoryIncognito(nextSettings.memory_incognito);
    setLiveSettings({
      live_conversation_enabled: nextSettings.live_conversation_enabled,
      live_conversation_participant_mode: nextSettings.live_conversation_participant_mode,
      live_conversation_engagement: nextSettings.live_conversation_engagement,
      live_conversation_initiative: nextSettings.live_conversation_initiative,
      live_conversation_address_strictness: nextSettings.live_conversation_address_strictness,
      live_conversation_interruption_sensitivity: nextSettings.live_conversation_interruption_sensitivity,
      live_conversation_pause_tolerance: nextSettings.live_conversation_pause_tolerance,
      live_conversation_emotion_expression: nextSettings.live_conversation_emotion_expression,
      live_conversation_mood_recovery: nextSettings.live_conversation_mood_recovery,
      live_conversation_recent_event_weight: nextSettings.live_conversation_recent_event_weight,
      live_conversation_echo_mode: nextSettings.live_conversation_echo_mode,
    });
  }, []);

  useEffect(() => {
    if (!settings || hasInitialSettings.current) return;
    applySettingsToForm(settings);
    hasInitialSettings.current = true;
  }, [applySettingsToForm, settings]);

  useEffect(() => {
    void getPronunciations()
      .then((result) => setPronunciationsText(formatPronunciations(result.pronunciations)))
      .catch(() => setPronunciationsText(""));
    void getSttTerms()
      .then((result) => setSttTermsText(formatSttTerms(result.terms)))
      .catch(() => setSttTermsText(""));
  }, []);

  const saveRuntimeSetting = useCallback((patch: RuntimeSettingsPatch, rollback?: () => void) => {
    autosave.save(patch, rollback);
  }, [autosave]);

  const updateLiveSetting = <K extends keyof LiveConversationSettings>(
    key: K,
    value: LiveConversationSettings[K],
  ) => {
    const previousValue = liveSettings[key];
    setLiveSettings((current) => ({ ...current, [key]: value }));
    saveRuntimeSetting(
      { [key]: value } as RuntimeSettingsPatch,
      () => setLiveSettings((current) => ({ ...current, [key]: previousValue })),
    );
  };

  const scheduleRuntimeSetting = useCallback((section: SettingsSection, patch: RuntimeSettingsPatch, rollback?: () => void) => {
    const currentTimer = autosaveTimersRef.current[section];
    if (currentTimer !== undefined) window.clearTimeout(currentTimer);
    autosaveTimersRef.current[section] = window.setTimeout(() => {
      delete autosaveTimersRef.current[section];
      saveRuntimeSetting(patch, rollback);
    }, 300);
  }, [saveRuntimeSetting]);

  useEffect(() => () => {
    Object.values(autosaveTimersRef.current).forEach((timer) => {
      if (timer !== undefined) window.clearTimeout(timer);
    });
  }, []);

  const refreshAudioDevices = useCallback(async (requestMicrophoneAccess = false) => {
    setAudioDevicesLoading(true);
    setAudioDevicesMessage(null);
    try {
      const nextDevices = await getAudioDeviceCatalog(requestMicrophoneAccess);
      setAudioDevices(nextDevices);
      if (!nextDevices.canEnumerate) {
        setAudioDevicesMessage("Этот WebView не даёт получить список аудиоустройств.");
      } else if (requestMicrophoneAccess && nextDevices.inputs.length === 0) {
        setAudioDevicesMessage("Микрофоны не найдены. Проверьте доступ к микрофону в Windows.");
      }
    } catch (error) {
      setAudioDevicesMessage(
        error instanceof Error ? `Не удалось получить список устройств: ${error.message}` : "Не удалось получить список устройств.",
      );
    } finally {
      setAudioDevicesLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshAudioDevices();
    const mediaDevices = typeof navigator === "undefined" ? undefined : navigator.mediaDevices;
    if (!mediaDevices?.addEventListener) return undefined;
    const handleDeviceChange = () => void refreshAudioDevices();
    mediaDevices.addEventListener("devicechange", handleDeviceChange);
    return () => mediaDevices.removeEventListener("devicechange", handleDeviceChange);
  }, [refreshAudioDevices]);

  const changeVoiceStyle = async (value: string) => {
    const previousValue = voiceTtsStyle;
    setVoiceTtsStyle(value);
    setSaving(true);
    setMessage(null);
    try {
      const nextSettings = await updateVoiceStyle(value);
      onSettingsChanged(nextSettings);
      setVoiceTtsStyle(nextSettings.voice_tts_style);
      setMessage("Подача голоса изменена до перезапуска.");
    } catch (error) {
      setVoiceTtsStyle(previousValue);
      setMessage(error instanceof Error ? error.message : "Не удалось изменить подачу голоса.");
    } finally {
      setSaving(false);
    }
  };

  const changeVoiceExpression = async (value: string) => {
    const previousValue = voiceExpressionLevel;
    setVoiceExpressionLevel(value);
    setSaving(true);
    setMessage(null);
    try {
      const nextSettings = await updateVoiceExpression(value);
      onSettingsChanged(nextSettings);
      setVoiceExpressionLevel(nextSettings.voice_tts_expression_level);
      setMessage("Выразительность изменена до перезапуска.");
    } catch (error) {
      setVoiceExpressionLevel(previousValue);
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
  const settingsSectionMeta: Record<SettingsSection, { title: string; description: string }> = {
    conversation: { title: "Живой разговор", description: "Когда Iris слушает, вступает в разговор и выражает эмоции." },
    avatar: { title: "Аватар", description: "Размещение, внешний вид и тестовые команды Iris." },
    voice: { title: "Голос", description: "Звучание, темп и подача речи." },
    "voice-devices": { title: "Устройства", description: "Микрофон, наушники и профиль записи." },
    "voice-recognition": { title: "Распознавание", description: "Словари и параметры распознавания речи." },
    "voice-advanced": { title: "Дополнительно", description: "Буфер воспроизведения и приватный сбор тестовых записей." },
    memory: { title: "Память", description: "Какие сведения Iris может сохранять между разговорами." },
    "system-overview": { title: "Система", description: "Состояние подключения и компонентов Iris." },
    models: { title: "Модели", description: "Загрузка и обслуживание локальных моделей." },
    backups: { title: "Резервные копии", description: "Копии памяти и настроек профиля." },
    maintenance: { title: "Обслуживание данных", description: "Индексы, очистка и необратимые действия." },
    events: { title: "Журнал событий", description: "Технические события и диагностика." },
  };

  const saveSttTerms = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const result = await updateSttTerms(parseSttTerms(sttTermsText));
      setSttTermsText(formatSttTerms(result.terms));
      setMessage("Словарь распознавания сохранён и применён.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось сохранить словарь распознавания.");
    } finally {
      setSaving(false);
    }
  };

  const includeSelectedAudioDevice = (
    options: AudioDeviceOption[],
    deviceId: string,
    unavailableLabel: string,
  ): AudioDeviceOption[] => (
    deviceId && !options.some((option) => option.deviceId === deviceId)
      ? [{ deviceId, label: unavailableLabel }, ...options]
      : options
  );
  const inputDeviceOptions = includeSelectedAudioDevice(
    audioDevices.inputs,
    voiceInputDeviceId,
    "Выбранный микрофон сейчас недоступен",
  );
  const outputDeviceOptions = includeSelectedAudioDevice(
    audioDevices.outputs,
    voiceOutputDeviceId,
    "Выбранное устройство вывода сейчас недоступно",
  );

  const activeSettingsMeta = settingsSectionMeta[activeSection];

  return (
    <section className="panel settings-panel">
      <SettingsNavigation current={activeSection} onChange={setActiveSection} />

      <div className="settings-content">
        <header className="settings-heading">
          <div className="settings-heading-row">
            <div>
              <h2>{activeSettingsMeta.title}</h2>
              <p>{activeSettingsMeta.description}</p>
            </div>
            <AutoSaveStatus status={autosave.status} onRetry={autosave.retry} />
          </div>
        </header>

        <div className="settings-grid system-status-grid" hidden={activeSection !== "system-overview"}>
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

        <div className="system-stack" hidden={!(["models", "backups", "maintenance", "events"] as SettingsSection[]).includes(activeSection)}>
          <div hidden={activeSection !== "models"}><ModelManager /></div>
          <div hidden={activeSection !== "backups"}><BackupControls /></div>
          <div hidden={activeSection !== "maintenance"}><SystemMaintenance /></div>
          <div hidden={activeSection !== "events"}>
            <EventsPage events={events} onRefreshEvents={onRefreshEvents} compact />
          </div>
        </div>

        <div hidden={activeSection !== "avatar"}>
          <AvatarControls
            avatarStatus={avatarStatus}
            overlay={avatarOverlay}
            placement={settings.avatar_placement}
            inAppVisible={settings.avatar_in_app_visible}
            onRefresh={onRefreshAvatar}
            onOverlayChanged={onAvatarOverlayChanged}
            onSettingsChanged={onSettingsChanged}
          />
        </div>

        <div className="form-grid settings-form" hidden={activeSection === "avatar" || activeSection === "system-overview" || ["models", "backups", "maintenance", "events"].includes(activeSection)}>
        <fieldset className="settings-group" hidden={activeSection !== "voice"}>
          <legend>Основное</legend>
          <label>
            Язык голосового ввода
            <select
              value={voiceLanguage}
              onChange={(event) => {
                const nextValue = event.target.value;
                const previousValue = voiceLanguage;
                setVoiceLanguage(nextValue);
                saveRuntimeSetting({ voice_language: nextValue }, () => setVoiceLanguage(previousValue));
              }}
            >
              {settings.available_voice_languages.map((availableLanguage) => (
                <option key={availableLanguage} value={availableLanguage}>
                  {availableLanguage === "ru" ? "Русский" : availableLanguage === "en" ? "Английский" : availableLanguage}
                </option>
              ))}
            </select>
          </label>
        </fieldset>

        <fieldset className="settings-group" hidden={activeSection !== "voice-devices"}>
          <legend>Устройства</legend>
          <label>
            Профиль микрофона
            <select
              value={voiceMicrophoneProfile}
              onChange={(event) => {
                const nextValue = event.target.value as MicrophoneProfile;
                const previousValue = voiceMicrophoneProfile;
                setVoiceMicrophoneProfile(nextValue);
                saveRuntimeSetting({ voice_microphone_profile: nextValue }, () => setVoiceMicrophoneProfile(previousValue));
              }}
            >
              <option value="balanced">Сбалансированный — рекомендуется</option>
              <option value="headset">Гарнитура</option>
              <option value="speakers">Колонки</option>
            </select>
            <small>Управляет эхоподавлением и шумоподавлением браузера для записи и живого режима.</small>
          </label>

          <label>
            Источник входа (микрофон)
            <select
              value={voiceInputDeviceId}
              onChange={(event) => {
                const nextValue = event.target.value;
                const previousValue = voiceInputDeviceId;
                setVoiceInputDeviceId(nextValue);
                saveRuntimeSetting({ voice_input_device_id: nextValue }, () => setVoiceInputDeviceId(previousValue));
              }}
              disabled={saving}
            >
              <option value="">Системный по умолчанию</option>
              {inputDeviceOptions.map((device) => (
                <option key={device.deviceId} value={device.deviceId} disabled={!audioDevices.canEnumerate}>
                  {device.label}
                </option>
              ))}
            </select>
            <small>Используется для единственного голосового режима Live.</small>
          </label>

          <label>
            Источник вывода (наушники или колонки)
            <select
              value={voiceOutputDeviceId}
              onChange={(event) => {
                const nextValue = event.target.value;
                const previousValue = voiceOutputDeviceId;
                setVoiceOutputDeviceId(nextValue);
                saveRuntimeSetting({ voice_output_device_id: nextValue }, () => setVoiceOutputDeviceId(previousValue));
              }}
              disabled={saving}
            >
              <option value="">Системный по умолчанию</option>
              {outputDeviceOptions.map((device) => (
                <option key={device.deviceId} value={device.deviceId} disabled={!audioDevices.canSelectOutput}>
                  {device.label}
                </option>
              ))}
            </select>
            <small>
              {audioDevices.canSelectOutput
                ? "Выбранное устройство используется для синтезированных аудиофайлов и воспроизведения сообщений; запасной системный голос браузера следует настройке Windows."
                : "Этот WebView не поддерживает выбор устройства вывода."}
            </small>
          </label>

          <div className="readonly-setting audio-device-refresh">
            <span>Аудиоустройства</span>
            <button
              className="secondary"
              type="button"
              onClick={() => void refreshAudioDevices(true)}
              disabled={saving || audioDevicesLoading}
            >
              {audioDevicesLoading ? "Обновляем…" : "Разрешить доступ и обновить"}
            </button>
            {audioDevicesMessage && <small role="status">{audioDevicesMessage}</small>}
          </div>
        </fieldset>

        <fieldset className="settings-group" hidden={activeSection !== "voice"}>
          <legend>Синтез речи</legend>
          <label>
            Голос {ttsProviderLabel}
            <select
              value={voiceTtsVoice}
              onChange={(event) => {
                const nextValue = event.target.value;
                const previousValue = voiceTtsVoice;
                setVoiceTtsVoice(nextValue);
                saveRuntimeSetting({ voice_tts_voice: nextValue }, () => setVoiceTtsVoice(previousValue));
              }}
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
              min="0.70"
              max="1.30"
              step="0.05"
              type="range"
              value={voicePlaybackRate}
              onChange={(event) => {
                const nextValue = Number(event.target.value);
                const previousValue = voicePlaybackRate;
                setVoicePlaybackRate(nextValue);
                scheduleRuntimeSetting("voice", { voice_playback_rate: nextValue }, () => setVoicePlaybackRate(previousValue));
              }}
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

        <fieldset className="settings-group" hidden={activeSection !== "voice-recognition"}>
          <legend>Детектор речи</legend>
          <div className="readonly-setting">
            <span>Детектор речи</span>
            <strong>
              {settings.voice_vad?.active_provider ?? "energy"}
              {settings.voice_vad?.model ? ` · ${settings.voice_vad.model}` : ""}
              {settings.voice_vad?.ready ? " · готов" : " · fallback"}
            </strong>
            {settings.voice_vad?.fallback_reason && <small>{settings.voice_vad.fallback_reason}</small>}
          </div>
        </fieldset>

        <fieldset className="settings-group" hidden={activeSection !== "voice-recognition"}>
          <legend>Словарь распознавания</legend>
          <label>
            Канонический термин = точный вариант | точный вариант
            <textarea
              rows={9}
              value={sttTermsText}
              onChange={(event) => setSttTermsText(event.target.value)}
              placeholder={"NeuroAsist = Нейро Асист | нейроасист\nGigaAM = Гига АМ | гигаэм"}
              disabled={saving}
            />
            <small>Исправляются только перечисленные варианты. Нечёткий поиск и LLM не используются.</small>
          </label>
          <button className="secondary" type="button" onClick={() => void saveSttTerms()} disabled={saving}>
            Сохранить словарь распознавания
          </button>
        </fieldset>

        <fieldset className="settings-group" hidden={activeSection !== "voice-recognition"}>
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

        <fieldset className="settings-group" hidden={activeSection !== "voice-advanced"}>
          <legend>Дополнительно</legend>
          <label>
            Сегментов в буфере
            <input
              min="1"
              max="4"
              step="1"
              type="number"
              value={prebufferSegments}
              onChange={(event) => {
                const nextValue = Number(event.target.value);
                const previousValue = prebufferSegments;
                setPrebufferSegments(nextValue);
                scheduleRuntimeSetting("voice-advanced", { voice_live_playback_prebuffer_segments: nextValue }, () => setPrebufferSegments(previousValue));
              }}
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
              onChange={(event) => {
                const nextValue = Number(event.target.value);
                const previousValue = prebufferMs;
                setPrebufferMs(nextValue);
                scheduleRuntimeSetting("voice-advanced", { voice_live_playback_prebuffer_ms: nextValue }, () => setPrebufferMs(previousValue));
              }}
            />
          </label>
          <button
            className="secondary"
            type="button"
            aria-expanded={showSttCapture}
            aria-controls="stt-guided-capture"
            onClick={() => setShowSttCapture((value) => !value)}
          >
            {showSttCapture ? "Скрыть сбор тестовых записей" : "Собрать приватный STT-корпус"}
          </button>
        </fieldset>

        {showSttCapture && activeSection === "voice-advanced" && (
          <GuidedSttCapture profile={voiceMicrophoneProfile} inputDeviceId={voiceInputDeviceId} />
        )}

        <fieldset className="settings-group live-conversation-settings" hidden={activeSection !== "conversation"}>
          <legend>Живой разговор</legend>
          <small>
            Live — единственный голосовой режим. Реплики распознаются автоматически, без кнопки записи.
          </small>

          <label>
            Участники
            <select
              value={liveSettings.live_conversation_participant_mode}
              onChange={(event) => updateLiveSetting(
                "live_conversation_participant_mode",
                event.target.value as LiveConversationSettings["live_conversation_participant_mode"],
              )}
            >
              <option value="one_to_one">Один на один</option>
              <option value="group">Несколько собеседников</option>
            </select>
          </label>

          <label>
            Охотность вступать
            <select
              value={liveSettings.live_conversation_engagement}
              onChange={(event) => updateLiveSetting(
                "live_conversation_engagement",
                event.target.value as LiveConversationSettings["live_conversation_engagement"],
              )}
            >
              <option value="low">Сдержанная</option>
              <option value="balanced">Сбалансированная</option>
              <option value="high">Разговорчивая</option>
            </select>
          </label>

          <label>
            Инициативность
            <select
              value={liveSettings.live_conversation_initiative}
              onChange={(event) => updateLiveSetting(
                "live_conversation_initiative",
                event.target.value as LiveConversationSettings["live_conversation_initiative"],
              )}
            >
              <option value="off">Выключена</option>
              <option value="rare">Редкая</option>
              <option value="balanced">Сбалансированная</option>
            </select>
          </label>

          <label>
            Прямое обращение
            <select
              value={liveSettings.live_conversation_address_strictness}
              onChange={(event) => updateLiveSetting(
                "live_conversation_address_strictness",
                event.target.value as LiveConversationSettings["live_conversation_address_strictness"],
              )}
            >
              <option value="relaxed">Свободное</option>
              <option value="balanced">Сбалансированное</option>
              <option value="strict">Строгое</option>
            </select>
          </label>

          <label>
            Чувствительность к перебиванию
            <select
              value={liveSettings.live_conversation_interruption_sensitivity}
              onChange={(event) => updateLiveSetting(
                "live_conversation_interruption_sensitivity",
                event.target.value as LiveConversationSettings["live_conversation_interruption_sensitivity"],
              )}
            >
              <option value="low">Низкая</option>
              <option value="balanced">Сбалансированная</option>
              <option value="high">Высокая</option>
            </select>
          </label>

          <label>
            Терпимость к паузам
            <select
              value={liveSettings.live_conversation_pause_tolerance}
              onChange={(event) => updateLiveSetting(
                "live_conversation_pause_tolerance",
                event.target.value as LiveConversationSettings["live_conversation_pause_tolerance"],
              )}
            >
              <option value="short">Короткая</option>
              <option value="natural">Естественная</option>
              <option value="patient">Терпеливая</option>
            </select>
          </label>

          <label>
            Выраженность эмоций
            <select
              value={liveSettings.live_conversation_emotion_expression}
              onChange={(event) => updateLiveSetting(
                "live_conversation_emotion_expression",
                event.target.value as LiveConversationSettings["live_conversation_emotion_expression"],
              )}
            >
              <option value="subtle">Тонкая</option>
              <option value="natural">Естественная</option>
              <option value="strong">Яркая</option>
            </select>
          </label>

          <label>
            Восстановление настроения
            <select
              value={liveSettings.live_conversation_mood_recovery}
              onChange={(event) => updateLiveSetting(
                "live_conversation_mood_recovery",
                event.target.value as LiveConversationSettings["live_conversation_mood_recovery"],
              )}
            >
              <option value="slow">Медленное</option>
              <option value="natural">Естественное</option>
              <option value="fast">Быстрое</option>
            </select>
          </label>

          <label>
            Влияние недавних событий
            <select
              value={liveSettings.live_conversation_recent_event_weight}
              onChange={(event) => updateLiveSetting(
                "live_conversation_recent_event_weight",
                event.target.value as LiveConversationSettings["live_conversation_recent_event_weight"],
              )}
            >
              <option value="light">Слабое</option>
              <option value="balanced">Сбалансированное</option>
              <option value="strong">Сильное</option>
            </select>
          </label>

          <label>
            Защита от собственного голоса
            <select
              value={liveSettings.live_conversation_echo_mode}
              onChange={(event) => updateLiveSetting(
                "live_conversation_echo_mode",
                event.target.value as LiveConversationSettings["live_conversation_echo_mode"],
              )}
            >
              <option value="auto">Автоматически</option>
              <option value="half_duplex">Не слушать во время ответа</option>
            </select>
          </label>
        </fieldset>

        <fieldset className="settings-group" hidden={activeSection !== "memory"}>
          <legend>Память</legend>
          <label>
            Режим сохранения
            <select
              value={memoryMode}
              onChange={(event) => {
                const nextValue = event.target.value;
                const previousValue = memoryMode;
                setMemoryMode(nextValue);
                saveRuntimeSetting({ memory_mode: nextValue }, () => setMemoryMode(previousValue));
              }}
            >
              <option value="off">Не сохранять</option>
              <option value="balanced">Умный — только важные устойчивые факты</option>
              <option value="automatic">Автоматический — все обычные факты</option>
            </select>
          </label>
          <SettingsSwitch
            checked={memoryIncognito}
            label="Не сохранять текущий разговор"
            description="Режим инкогнито не добавляет новые данные в долгосрочную память."
            onChange={(checked) => {
              const previousValue = memoryIncognito;
              setMemoryIncognito(checked);
              saveRuntimeSetting({ memory_incognito: checked }, () => setMemoryIncognito(previousValue));
            }}
          />
        </fieldset>
        </div>

        {message && <div className="notice" role="status">{message}</div>}
      </div>
    </section>
  );
}

const SETTINGS_NAVIGATION: Array<{
  id: string;
  label: string;
  icon: LucideIcon;
  directSection?: SettingsSection;
  items: Array<{ section: SettingsSection; label: string }>;
}> = [
  {
    id: "behavior",
    label: "Поведение",
    icon: SlidersHorizontal,
    items: [{ section: "conversation", label: "Живой разговор" }],
  },
  {
    id: "avatar",
    label: "Аватар",
    icon: Settings,
    directSection: "avatar",
    items: [],
  },
  {
    id: "voice",
    label: "Голос",
    icon: Volume2,
    items: [
      { section: "voice", label: "Основное" },
      { section: "voice-devices", label: "Устройства" },
      { section: "voice-recognition", label: "Распознавание" },
      { section: "voice-advanced", label: "Дополнительно" },
    ],
  },
  {
    id: "memory",
    label: "Память",
    icon: Brain,
    directSection: "memory",
    items: [],
  },
  {
    id: "system",
    label: "Система",
    icon: MonitorCog,
    items: [
      { section: "system-overview", label: "Обзор" },
      { section: "models", label: "Модели" },
      { section: "backups", label: "Резервные копии" },
      { section: "maintenance", label: "Обслуживание данных" },
      { section: "events", label: "Журнал событий" },
    ],
  },
];

function SettingsNavigation({ current, onChange }: { current: SettingsSection; onChange: (section: SettingsSection) => void }) {
  const activeGroup = SETTINGS_NAVIGATION.find((group) => group.directSection === current || group.items.some((item) => item.section === current))?.id ?? "behavior";
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() => ({
    behavior: true,
    voice: true,
    system: false,
  }));

  useEffect(() => {
    setExpanded((value) => ({ ...value, [activeGroup]: true }));
  }, [activeGroup]);

  return (
    <nav className="settings-navigation" aria-label="Разделы настроек">
      {SETTINGS_NAVIGATION.map((group) => {
        if (group.directSection) {
          return (
            <button
              key={group.id}
              type="button"
              className={`settings-nav-direct${current === group.directSection ? " is-active" : ""}`}
              aria-current={current === group.directSection ? "page" : undefined}
              onClick={() => onChange(group.directSection!)}
            >
              <group.icon size={17} aria-hidden="true" />
              <span>{group.label}</span>
            </button>
          );
        }
        const isExpanded = expanded[group.id] ?? false;
        const isActive = group.id === activeGroup;
        const childrenId = `settings-nav-children-${group.id}`;
        return (
          <div className={`settings-nav-group${isActive ? " is-active" : ""}`} key={group.id}>
            <button
              type="button"
              className="settings-nav-group-button"
              aria-expanded={isExpanded}
              aria-controls={childrenId}
              onClick={() => {
                setExpanded((value) => ({ ...value, [group.id]: !isExpanded }));
              }}
            >
              <group.icon size={17} aria-hidden="true" />
              <span>{group.label}</span>
              <ChevronDown className="settings-nav-chevron" size={15} aria-hidden="true" />
            </button>
            <div id={childrenId} className="settings-nav-children" hidden={!isExpanded}>
              {group.items.map((item) => (
                <SettingsSectionButton key={item.section} section={item.section} current={current} label={item.label} onClick={onChange} />
              ))}
            </div>
          </div>
        );
      })}
    </nav>
  );
}

function SettingsSectionButton({
  section,
  current,
  label,
  onClick,
}: {
  section: SettingsSection;
  current: SettingsSection;
  label: string;
  onClick: (section: SettingsSection) => void;
}) {
  return (
    <button
      type="button"
      className={`settings-nav-button${section === current ? " is-active" : ""}`}
      aria-current={section === current ? "page" : undefined}
      onClick={() => onClick(section)}
    >
      <span>{label}</span>
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
  const [pendingAction, setPendingAction] = useState<{
    title: string;
    description: string;
    action: () => Promise<unknown>;
    success: string;
  } | null>(null);

  const run = async (action: () => Promise<unknown>, success: string) => {
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
      setPendingAction(null);
    }
  };

  return <section className="system-card maintenance-card" aria-label="Обслуживание данных">
    <div className="panel-header"><div><h2>Обслуживание данных</h2><span>Необратимые действия вынесены отдельно</span></div><Database size={20} aria-hidden="true" /></div>
    <div className="maintenance-actions">
      <button className="secondary" disabled={busy} onClick={() => setPendingAction({ title: "Перестроить индекс памяти?", description: "Сами записи останутся на месте. Iris заново подготовит их для поиска.", action: reindexMemories, success: "Индекс памяти перестроен." })}>Перестроить индекс памяти</button>
      <button className="secondary danger-button" disabled={busy} onClick={() => setPendingAction({ title: "Очистить долгосрочную память?", description: "История диалогов сохранится, но восстановить записи памяти будет нельзя.", action: clearMemories, success: "Долгосрочная память очищена." })}>Очистить память</button>
      <button className="danger-button" disabled={busy} onClick={() => setPendingAction({ title: "Сбросить все данные Iris?", description: "История, сводки и долгосрочная память будут удалены без возможности восстановления.", action: resetAllCompanionData, success: "Все данные помощника удалены." })}>Сбросить все данные</button>
    </div>
    {message && <div className="notice" role="status">{message}</div>}
    <AppDialog open={Boolean(pendingAction)} title={pendingAction?.title ?? ""} description={pendingAction?.description} onClose={() => !busy && setPendingAction(null)}>
      <div className="dialog-actions">
        <button className="secondary" type="button" disabled={busy} onClick={() => setPendingAction(null)}>Отмена</button>
        <button className="danger-button" type="button" disabled={busy} onClick={() => pendingAction && void run(pendingAction.action, pendingAction.success)}>{busy ? "Выполняю…" : "Подтвердить"}</button>
      </div>
    </AppDialog>
  </section>;
}

function AvatarControls({
  avatarStatus,
  overlay: initialOverlay,
  placement,
  inAppVisible,
  onRefresh,
  onOverlayChanged,
  onSettingsChanged,
}: {
  avatarStatus: AvatarStatusResponse | null;
  overlay: AvatarOverlaySettings | null;
  placement: AvatarPlacement;
  inAppVisible: boolean;
  onRefresh: () => Promise<void>;
  onOverlayChanged: (overlay: AvatarOverlaySettings | null) => void;
  onSettingsChanged: (settings: PublicSettings) => void;
}) {
  const [phrase, setPhrase] = useState("Проверка аватара.");
  const [emotion, setEmotion] = useState("happy");
  const [gesture, setGesture] = useState("greeting");
  const [motionIntensity, setMotionIntensity] = useState(0.8);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [overlay, setOverlay] = useState<AvatarOverlaySettings | null>(initialOverlay);
  const enabled = Boolean(avatarStatus?.enabled);
  const client = avatarStatus?.clients[0];
  const engine = avatarStatus?.emotion_engine;

  useEffect(() => { setOverlay(initialOverlay); }, [initialOverlay]);
  useEffect(() => {
    if (initialOverlay) return;
    void getAvatarOverlay().then((nextOverlay) => {
      setOverlay(nextOverlay);
      onOverlayChanged(nextOverlay);
    }).catch(() => setOverlay(null));
  }, [initialOverlay, onOverlayChanged]);

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
    try {
      const nextOverlay = await updateAvatarOverlay(patch);
      setOverlay(nextOverlay);
      onOverlayChanged(nextOverlay);
      setMessage(placement === "in_app" ? "Отображение аватара в диалоге обновлено." : "Настройки оверлея обновлены.");
    }
    catch { setMessage("Не удалось сохранить настройки оверлея."); }
    finally { setBusy(false); }
  };

  const updateInAppVisibility = async (visible: boolean) => {
    setBusy(true); setMessage(null);
    try {
      const nextSettings = await updateRuntimeSettings({ avatar_in_app_visible: visible });
      onSettingsChanged(nextSettings);
      setMessage(visible ? "Аватар будет показан в диалоге." : "Аватар скрыт в диалоге.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось сохранить отображение аватара.");
    } finally { setBusy(false); }
  };

  const changePlacement = async (nextPlacement: AvatarPlacement) => {
    if (nextPlacement === placement) return;
    setBusy(true);
    setMessage(null);
    try {
      const nextSettings = await updateRuntimeSettings({ avatar_placement: nextPlacement });
      onSettingsChanged(nextSettings);
      // The app-level effect owns the native transition. Keeping a single
      // caller avoids two concurrent Unity launches when this state update
      // re-renders the app.
      setMessage(nextPlacement === "in_app"
        ? "Режим сохранён. Аватар появится внутри Iris на экране диалога."
        : "Режим сохранён. Аватар снова будет отдельным оверлеем на рабочем столе.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось переключить размещение аватара.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="avatar-controls" aria-label="Управление аватаром">
      <div className="avatar-toolbar">
        <span>{enabled ? `${avatarStatus?.client_count ?? 0} подключено` : "Интеграция отключена"}</span>
        <button className="icon-button" onClick={() => void onRefresh()} disabled={busy} aria-label="Обновить статус аватара" title="Обновить статус аватара"><RefreshCw size={16} /></button>
      </div>
      <fieldset className="avatar-placement" disabled={busy}>
        <legend>Где показывать аватар</legend>
        <label>
          <input type="radio" name="avatar-placement" aria-label="Внутри Iris" checked={placement === "in_app"} onChange={() => void changePlacement("in_app")} />
          <span><strong>Внутри Iris</strong><small>Внизу слева на экране диалога, без второго окна.</small></span>
        </label>
        <label>
          <input type="radio" name="avatar-placement" aria-label="Отдельным оверлеем" checked={placement === "desktop_overlay"} onChange={() => void changePlacement("desktop_overlay")} />
          <span><strong>Отдельным оверлеем</strong><small>Поверх рабочего стола, как сейчас.</small></span>
        </label>
      </fieldset>
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
        <SettingsSwitch
          checked={placement === "in_app" ? inAppVisible : (overlay?.visible ?? true)}
          label={placement === "in_app" ? "Показывать в диалоге" : "Показывать оверлей"}
          disabled={!enabled || busy}
          onChange={(checked) => void (placement === "in_app" ? updateInAppVisibility(checked) : updateOverlay({ visible: checked }))}
        />
        {placement === "desktop_overlay" && <>
          <SettingsSwitch checked={overlay?.always_on_top ?? true} label="Поверх окон" disabled={!enabled || busy} onChange={(checked) => void updateOverlay({ always_on_top: checked })} />
          <SettingsSwitch checked={overlay?.locked ?? true} label="Заблокировать клики" disabled={!enabled || busy} onChange={(checked) => void updateOverlay({ locked: checked })} />
        </>}
      </div>
      <details className="avatar-test-disclosure">
        <summary>Тест эмоций и жестов <ChevronDown size={16} aria-hidden="true" /></summary>
        <div className="avatar-test-grid">
        {placement === "desktop_overlay" && <label>
          Масштаб оверлея {overlay?.scale?.toFixed(1) ?? "1.0"}
          <input min="0.5" max="2" step="0.1" type="range" value={overlay?.scale ?? 1} disabled={!enabled || busy} onChange={(event) => void updateOverlay({ scale: Number(event.target.value) })} />
        </label>}
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
      </details>
      {message && <div className="notice" role="status">{message}</div>}
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
