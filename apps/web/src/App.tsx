import { CustomSelect } from "./components/CustomSelect";
import {
  IconInterfaceHome2,
  IconMailChatBubbleTextSquare,
  IconInterfaceTimeStopWatchCircle,
  IconComputerRobotCyborg1,
  IconInterfacePageControllerSettings,
  IconProgrammingScript2,
  IconInterfaceSettingPieChartCogSettingGraphCog,
  IconEntertainmentVolumeLevelHigh,
  IconComputerScreenCurve,
  IconInterfaceCursorArrow2,
  IconInterfaceContentArchive,
  IconInterfaceAlertAlarmBell2,
  IconComputerDatabase,
  IconInterfaceSpirals,
  IconInterfaceUserQueenCrown,
} from "./CustomIcons";
import { FormEvent, KeyboardEvent as ReactKeyboardEvent, lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, SendHorizontal } from "lucide-react";
import {
  FigmaStartFlowerIcon,
  FigmaMicIcon,
  FigmaHeadphonesIcon,
  FigmaSettingsIcon,
  FigmaExitIcon,
  FigmaNewChatIcon,
  FigmaSquareButtonBg,
  FigmaFinishButtonBg,
  FigmaNewChatButtonBg,
  FigmaDockBg,
  FigmaDualMediaButtonBg,
  FigmaStartButtonBg,
  FigmaInputPlateFullBg,
} from "./FigmaIcons";

function IrisPetalsIcon({ size = 20, className = "" }: { size?: number; className?: string }) {
  return (
    <FigmaStartFlowerIcon width={size} height={size} className={className} />
  );
}

import {
  getAvatarStatus,
  getAvatarOverlay,
  clearMemories,
  createBackup,
  getBackups,
  getEvents,
  closeCurrentEpisode,
  getTimelineJournal,
  getTimelineMessages,
  getConversationSession,
  getSettings,
  getConversationDebug,
  getStatus,
  getReadiness,
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
  ReadinessResponse,
  StatusResponse,
  TimelineJournalItem,
  TimelineMessage,
  VoiceTtsStatusResponse,
  MemoryUpdate,
  ConversationDebug,
  InterfaceLocale,
  VoiceState,
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
import { OverviewPage } from "./overview";
import { configureAvatarPlacement, getDesktopRuntime, initialCoreStatus, listenForAvatarVisibility, listenForCoreStatus, restartDesktopCore, setDesktopInterfaceLocale, type CoreStatus } from "./desktop";
import { StartupScreen } from "./components/StartupScreen";
import { WindowChrome } from "./components/WindowChrome";
import { AppDialog } from "./components/AppDialog";
import { GuidedSttCapture } from "./stt-capture";
import { InAppAvatarHost } from "./components/InAppAvatarHost";
import { IrisPortalBackground } from "./components/IrisPortalBackground";
import { IrisSubtitles } from "./components/IrisSubtitles";
import { audioAnalyzer } from "./audio-analyzer";
import {
  initialInterfaceLocale,
  interfaceIntlLocale,
  INTERFACE_LOCALE_CHANGED_EVENT,
  setInterfaceLocalePreference,
  useInterfaceLocale,
} from "./i18n";
import {
  animate,
  animateButtonPress,
  animateLivePulse,
  animateLiveRadar,
  animateMessageEnter,
  animateMessagePop,
  animateNoticeEnter,
  animatePageEnter,
  animateStaggerCards,
  animateTabSwitch,
  animateThinkingWave,
  prefersReducedMotion,
  stagger,
  useAnimeScope,
} from "./animations";

type AppView = "overview" | "chat" | "journal" | "memory" | "state" | "coding" | "settings";

const JournalPage = lazy(() => import("./journal").then(({ JournalPage }) => ({ default: JournalPage })));
const MemoryPage = lazy(() => import("./memory").then(({ MemoryPage }) => ({ default: MemoryPage })));
const StatePage = lazy(() => import("./state").then(({ StatePage }) => ({ default: StatePage })));
const CodingAgentPage = lazy(() => import("./coding").then(({ CodingAgentPage }) => ({ default: CodingAgentPage })));
const LazyChatPage = lazy(() => Promise.resolve({ default: ChatPage }));
const LazySettingsPage = lazy(() => Promise.resolve({ default: SettingsPage }));

function LazyPageFallback() {
  return <div className="panel page-loading" role="status">Загружаю раздел…</div>;
}
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
  | "system-interface"
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
  const elRef = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    if (elRef.current) {
      animate(elRef.current, {
        opacity: [0, 1],
        translateY: prefersReducedMotion() ? 0 : [-3, 0],
        duration: 180,
        ease: "outQuad",
        onComplete: () => {
          if (elRef.current) elRef.current.style.transform = "";
        },
      });
    }
  }, [status]);

  if (status === "saving") return <span ref={elRef} className="settings-save-status is-saving" role="status">Сохраняем…</span>;
  if (status === "error") {
    return <span ref={elRef} className="settings-save-status is-error" role="alert">Не удалось сохранить <button type="button" onClick={(e) => { animateButtonPress(e.currentTarget); onRetry(); }}>Повторить</button></span>;
  }
  if (status === "saved") return <span ref={elRef} className="settings-save-status is-saved" role="status">Сохранено</span>;
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
  return date.toLocaleTimeString(interfaceIntlLocale(), { hour: "2-digit", minute: "2-digit" });
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
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [avatarStatus, setAvatarStatus] = useState<AvatarStatusResponse | null>(null);
  const [avatarOverlay, setAvatarOverlay] = useState<AvatarOverlaySettings | null>(null);
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [interfaceLocale, setInterfaceLocale] = useState<InterfaceLocale>(initialInterfaceLocale);
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

  useInterfaceLocale(interfaceLocale);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      performance.mark("iris:first-ui-paint");
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    if (!servicesReady || !status || !settings) return;
    performance.mark("iris:first-interactive");
  }, [servicesReady, settings, status]);

  useEffect(() => {
    const handleLocaleChange = (event: Event) => {
      const locale = (event as CustomEvent<InterfaceLocale>).detail;
      if (locale === "ru" || locale === "en") setInterfaceLocale(locale);
    };
    window.addEventListener(INTERFACE_LOCALE_CHANGED_EVENT, handleLocaleChange);
    return () => window.removeEventListener(INTERFACE_LOCALE_CHANGED_EVENT, handleLocaleChange);
  }, []);

  useEffect(() => {
    if (!settings || !["ru", "en"].includes(settings.interface_locale)) return;
    setInterfaceLocale(settings.interface_locale);
    setInterfaceLocalePreference(settings.interface_locale);
  }, [settings?.interface_locale]);

  useEffect(() => {
    void setDesktopInterfaceLocale(interfaceLocale).catch(() => {
      // The browser build has no tray, and an older desktop shell can still
      // show the app safely even if it does not expose this optional command.
    });
  }, [interfaceLocale]);

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

  const refreshReadiness = useCallback(async () => {
    try {
      setReadiness(await getReadiness());
    } catch {
      // The core status indicator remains authoritative while the readiness
      // endpoint is unavailable during an older or restarting backend.
    }
  }, []);

  const refreshOverview = useCallback(async () => {
    const revision = ++overviewRevision.current;
    try {
      const [nextStatus, nextSettings] = await Promise.all([
        getStatus(),
        getSettings(),
      ]);
      if (revision !== overviewRevision.current) return;
      setStatus(nextStatus);
      setSettings(nextSettings);
      setStatusError(null);
      // Avatar diagnostics are useful after the first paint but do not belong
      // to the critical request waterfall.
      window.requestAnimationFrame(() => {
        void Promise.all([
          getAvatarStatus().catch(() => null),
          getAvatarOverlay().catch(() => null),
        ]).then(([nextAvatarStatus, nextAvatarOverlay]) => {
          if (revision !== overviewRevision.current) return;
          setAvatarStatus(nextAvatarStatus);
          setAvatarOverlay(nextAvatarOverlay);
        });
      });
    } catch (error) {
      if (revision !== overviewRevision.current) return;
      setStatusError(error instanceof Error ? error.message : "Сервис недоступен");
    }
  }, []);

  useEffect(() => {
    if (!servicesReady) return;
    void refreshOverview();
    void refreshReadiness();
    const firstFrame = window.requestAnimationFrame(() => { void refreshEvents(); });
    const timer = window.setInterval(() => {
      void refreshOverview();
    }, 10000);
    const readinessTimer = window.setInterval(() => { void refreshReadiness(); }, 1200);
    return () => {
      window.cancelAnimationFrame(firstFrame);
      window.clearInterval(timer);
      window.clearInterval(readinessTimer);
    };
  }, [refreshEvents, refreshOverview, refreshReadiness, servicesReady]);

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
    const frame = window.requestAnimationFrame(() => {
      void resumeSession().catch((error) => {
        setStatusError(error instanceof Error ? error.message : "Не удалось восстановить сессию.");
      });
    });
    return () => window.cancelAnimationFrame(frame);
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

    const firstFrame = window.requestAnimationFrame(connect);

    return () => {
      closed = true;
      window.cancelAnimationFrame(firstFrame);
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
            <Suspense fallback={<LazyPageFallback />}>
              <LazyChatPage
                sessionId={sessionId}
                sessionStarting={startingSession}
                isActive={activeView === "chat"}
                events={events}
                settings={settings}
                readiness={readiness}
                avatarStatus={avatarStatus}
                showInAppAvatar={settings?.avatar_placement === "in_app" && (settings.avatar_in_app_visible ?? true)}
                onRefreshEvents={refreshEvents}
                onOpenMemory={() => switchView("memory")}
                onOpenSettings={() => switchView("settings")}
                onStartNewDialog={startFreshSession}
              />
            </Suspense>
          </div>
          <Suspense fallback={<LazyPageFallback />}>
            {activeView === "journal" && <JournalPage onOpenChat={() => switchView("chat")} />}
            {activeView === "memory" && <MemoryPage />}
            {activeView === "state" && <StatePage events={events} />}
          </Suspense>
          {activeView === "coding" && (
            <Suspense fallback={<LazyPageFallback />}>
              <CodingAgentPage
                settings={settings}
                events={events}
                sessionId={sessionId}
                onSettingsChanged={(nextSettings) => {
                  overviewRevision.current += 1;
                  setSettings(nextSettings);
                }}
              />
            </Suspense>
          )}
          {activeView === "settings" && (
            <Suspense fallback={<LazyPageFallback />}>
              <LazySettingsPage
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
                onInterfaceLocaleChange={(locale) => {
                  setInterfaceLocale(locale);
                  setInterfaceLocalePreference(locale);
                }}
                onSettingsChanged={(nextSettings) => {
                  overviewRevision.current += 1;
                  setSettings(nextSettings);
                  void refreshOverview();
                  void refreshEvents();
                }}
              />
            </Suspense>
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

const MAIN_NAVIGATION: Array<{ id: Exclude<AppView, "settings">; label: string; icon: any }> = [
  { id: "overview", label: "Обзор", icon: IconInterfaceHome2 },
  { id: "chat", label: "Диалог", icon: IconMailChatBubbleTextSquare },
  { id: "journal", label: "История", icon: IconInterfaceTimeStopWatchCircle },
  { id: "memory", label: "Память", icon: IconComputerRobotCyborg1 },
  { id: "state", label: "Состояние", icon: IconInterfacePageControllerSettings },
  { id: "coding", label: "Coding Agent", icon: IconProgrammingScript2 },
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
  const sidebarRef = useAnimeScope<HTMLElement>((scope, root) => {
    const reduced = prefersReducedMotion();
    const navButtons = root.querySelectorAll(".navigation-button");
    if (navButtons.length) {
      animate(navButtons, {
        opacity: [0, 1],
        translateX: reduced ? 0 : [-6, 0],
        duration: reduced ? 100 : 200,
        delay: reduced ? 0 : stagger(30),
        ease: "outQuad",
        onComplete: () => {
          navButtons.forEach((btn) => {
            (btn as HTMLElement).style.transform = "";
          });
        },
      });
    }
  }, []);

  return (
    <aside id="main-sidebar" ref={sidebarRef} className={`sidebar${isOpen ? " is-open" : ""}`} aria-label="Основная навигация">
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
          <NavigationButton icon={FigmaSettingsIcon} label="Настройки" active={activeView === "settings"} compact={isCollapsed} iconSize={24} onClick={() => onNavigate("settings")} />
          <button
            className="icon-button sidebar-collapse-toggle"
            type="button"
            aria-label={isCollapsed ? "Развернуть меню" : "Свернуть меню"}
            aria-pressed={isCollapsed}
            title={isCollapsed ? "Развернуть меню" : "Свернуть меню"}
            onClick={(e) => {
              animateButtonPress(e.currentTarget);
              onToggleCollapsed();
            }}
          >
            {isCollapsed ? <IconInterfaceCursorArrow2 size={19} aria-hidden="true" /> : <IconInterfaceCursorArrow2 size={19} aria-hidden="true" />}
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
  iconSize = 21,
  onClick,
}: {
  icon: any;
  label: string;
  active: boolean;
  compact?: boolean;
  iconSize?: number;
  onClick: () => void;
}) {
  return (
    <button
      className={`navigation-button${active ? " is-active" : ""}`}
      aria-label={label}
      aria-current={active ? "page" : undefined}
      data-tooltip={compact ? label : undefined}
      title={compact ? label : undefined}
      onClick={(e) => {
        animateTabSwitch(e.currentTarget);
        onClick();
      }}
    >
      <Icon size={iconSize} aria-hidden="true" />
      <span>{label}</span>
    </button>
  );
}

export function ChatPage({
  sessionId,
  sessionStarting,
  isActive,
  events,
  settings,
  readiness,
  avatarStatus,
  showInAppAvatar,
  onRefreshEvents,
  onOpenMemory,
  onOpenSettings,
  onStartNewDialog,
}: {
  sessionId: string | null;
  sessionStarting: boolean;
  isActive: boolean;
  events: BackendEvent[];
  settings: PublicSettings | null;
  readiness: ReadinessResponse | null;
  avatarStatus: AvatarStatusResponse | null;
  showInAppAvatar: boolean;
  onRefreshEvents: () => Promise<void>;
  onOpenMemory: () => void;
  onOpenSettings?: () => void;
  onStartNewDialog: () => Promise<void>;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [liveSttTranscript, setLiveSttTranscript] = useState("");
  const [loading, setLoading] = useState(false);
  const [isStarted, setIsStarted] = useState(false);
  const [soundMuted, setSoundMuted] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [retryText, setRetryText] = useState<string | null>(null);
  const [memoryNotice, setMemoryNotice] = useState<string | null>(null);
  const [liveConversation, setLiveConversation] = useState(false);
  const [microphoneMuted, setMicrophoneMuted] = useState(false);
  const [activeAudioElement, setActiveAudioElement] = useState<HTMLAudioElement | null>(null);
  const [livePlaybackSegment, setLivePlaybackSegment] = useState("");
  const [conversationStatus, setConversationStatus] = useState("Микрофон включён");
  const [conversationDebug, setConversationDebug] = useState<ConversationDebug | null>(null);
  const [newDialogConfirmationOpen, setNewDialogConfirmationOpen] = useState(false);
  const [newDialogPending, setNewDialogPending] = useState(false);
  const listRef = useRef<HTMLDivElement | null>(null);
  const handledVoiceEventIdsRef = useRef<Set<string>>(new Set());
  const activeAudioRef = useRef<HTMLAudioElement | null>(null);
  const liveSocketRef = useRef<VoiceSocketClient | null>(null);
  const liveSocketSessionIdRef = useRef<string | null>(null);
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
  const bargeInTimerRef = useRef<number | null>(null);
  const sttClearTimerRef = useRef<number | null>(null);
  const pendingTextDeltasRef = useRef(new Map<string, string>());
  const pendingTextDeltaTimerRef = useRef<number | null>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  const handledCodingReviewEventIdsRef = useRef<Set<string>>(new Set());
  const handledCodingSpeechRequestIdsRef = useRef<Set<string>>(new Set());
  messagesRef.current = messages;

  const clearLiveSttTranscript = useCallback(() => {
    if (sttClearTimerRef.current !== null) {
      window.clearTimeout(sttClearTimerRef.current);
      sttClearTimerRef.current = null;
    }
    setLiveSttTranscript("");
  }, []);

  const updateLiveSttTranscript = useCallback((text: string, autoClearMs = 5000) => {
    if (sttClearTimerRef.current !== null) {
      window.clearTimeout(sttClearTimerRef.current);
      sttClearTimerRef.current = null;
    }
    setLiveSttTranscript(text);
    if (text && autoClearMs > 0) {
      sttClearTimerRef.current = window.setTimeout(() => {
        sttClearTimerRef.current = null;
        setLiveSttTranscript("");
      }, autoClearMs);
    }
  }, []);

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

  const cancelPendingBargeIn = useCallback(() => {
    if (bargeInTimerRef.current !== null) {
      window.clearTimeout(bargeInTimerRef.current);
      bargeInTimerRef.current = null;
    }
  }, []);

  useEffect(() => () => {
    if (conversationStatusTimerRef.current !== null) {
      window.clearTimeout(conversationStatusTimerRef.current);
    }
    if (sttClearTimerRef.current !== null) {
      window.clearTimeout(sttClearTimerRef.current);
    }
    cancelPendingBargeIn();
  }, [cancelPendingBargeIn]);

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

  const flushPendingTextDeltas = useCallback(() => {
    pendingTextDeltaTimerRef.current = null;
    const pending = pendingTextDeltasRef.current;
    if (pending.size === 0) return;
    pendingTextDeltasRef.current = new Map();
    setMessages((current) => {
      let next = current;
      for (const [utteranceId, delta] of pending) {
        const index = next.findIndex((message) => message.utteranceId === utteranceId);
        if (index < 0) {
          next = [...next, {
            id: crypto.randomUUID(),
            role: "assistant",
            content: delta,
            utteranceId,
            emotion: liveMetadataRef.current.emotion,
            intent: liveMetadataRef.current.intent,
          }];
          continue;
        }
        next = next.map((message, messageIndex) => messageIndex === index
          // Coding Agent notifications are already present as durable chat
          // messages when their live reply starts. Their single live delta is
          // intentionally the complete text, so do not render it twice.
          ? { ...message, content: message.content === delta ? message.content : message.content + delta }
          : message);
      }
      return next;
    });
  }, []);

  const queueTextDelta = useCallback((utteranceId: string, delta: string) => {
    pendingTextDeltasRef.current.set(
      utteranceId,
      `${pendingTextDeltasRef.current.get(utteranceId) ?? ""}${delta}`,
    );
    if (pendingTextDeltaTimerRef.current !== null) return;
    pendingTextDeltaTimerRef.current = window.setTimeout(flushPendingTextDeltas, 16);
  }, [flushPendingTextDeltas]);

  const refreshTimelineMessages = useCallback(() => {
    if (!sessionId) return Promise.resolve();
    return getTimelineMessages(50, sessionId).then((payload) => {
      setMessages(payload.items
        .filter((message) => message.role === "user" || message.role === "assistant")
        .map((message) => ({ id: message.id, role: message.role as "user" | "assistant", content: message.content })));
    }).catch(() => {
      // The V0.4 compatibility backend may intentionally keep Timeline V2 disabled.
    });
  }, [sessionId]);

  useEffect(() => { void refreshTimelineMessages(); }, [refreshTimelineMessages]);

  useEffect(() => {
    if (!sessionId) return;
    for (const event of events) {
      if (
        (event.type !== "coding.review_notification" && event.type !== "coding.attention_notification")
        || handledCodingReviewEventIdsRef.current.has(event.id)
      ) {
        continue;
      }
      handledCodingReviewEventIdsRef.current.add(event.id);
      if (getStringMetadata(event, "session_id") !== sessionId) continue;
      const messageId = getStringMetadata(event, "message_id");
      const content = getStringMetadata(event, "notification");
      const voiceUtteranceId = getStringMetadata(event, "voice_utterance_id");
      const voiceRequestId = getStringMetadata(event, "voice_request_id");
      if (!messageId || !content) continue;
      setMessages((current) => {
        if (
          current.some((message) => message.id === messageId)
          || (voiceUtteranceId && current.some((message) => message.utteranceId === voiceUtteranceId))
        ) {
          return current;
        }
        return [...current, {
          id: messageId,
          role: "assistant",
          content,
          utteranceId: voiceUtteranceId ?? undefined,
          voiceRequestId: voiceRequestId ?? undefined,
          ttsStatus: voiceRequestId ? "queued" : undefined,
        }];
      });
    }
  }, [events, sessionId]);

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
  const liveReady = Boolean(readiness?.live_ready);
  const liveStatusLabel = readiness?.stt === "failed" || readiness?.tts === "failed"
    ? "Голос недоступен"
    : liveReady
      ? "Голос готов"
      : "Голос загружается";
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
    setActiveAudioElement(except ?? null);
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
      if (soundMuted) return false;
      stopVoicePlayback();
      const audio = new Audio(audioUrl);
      audio.playbackRate = 1;
      activeAudioRef.current = audio;
      setActiveAudioElement(audio);
      audio.onended = () => {
        if (activeAudioRef.current === audio) {
          activeAudioRef.current = null;
          setActiveAudioElement(null);
          setVoiceState("idle");
        }
      };
      audio.onerror = () => {
        if (activeAudioRef.current === audio) {
          activeAudioRef.current = null;
          setActiveAudioElement(null);
          setVoiceState("idle");
        }
      };

      try {
        await setAudioElementOutput(audio, selectedOutputDeviceId);
        try {
          audioAnalyzer.attachAudioElement(audio);
        } catch {
          // Analyzer connection optional
        }
        await audio.play();
        setVoiceState("speaking");
        return true;
      } catch {
        if (activeAudioRef.current === audio) {
          activeAudioRef.current = null;
          setActiveAudioElement(null);
        }
        return false;
      }
    },
    [selectedOutputDeviceId, settings?.voice_playback_rate, soundMuted, stopVoicePlayback],
  );

  const speakTextInBrowser = useCallback(
    (text: string): boolean => {
      if (soundMuted || !browserSpeechSupported) {
        return false;
      }
      stopVoicePlayback();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = settings?.voice_language === "en" ? "en-US" : "ru-RU";
      utterance.rate = settings?.voice_playback_rate ?? 1;
      utterance.onstart = () => { setVoiceState("speaking"); };
      utterance.onend = () => { setVoiceState("idle"); };
      utterance.onerror = () => { setVoiceState("idle"); };
      window.speechSynthesis.speak(utterance);
      return true;
    },
    [browserSpeechSupported, settings?.voice_language, settings?.voice_playback_rate, soundMuted, stopVoicePlayback],
  );

  const toggleSoundMute = useCallback(() => {
    setSoundMuted((current) => {
      const next = !current;
      if (next) {
        stopVoicePlayback();
        interruptAssistantSpeech();
      }
      return next;
    });
  }, [interruptAssistantSpeech, stopVoicePlayback]);

  const ensureLivePlayer = useCallback(() => {
    if (!livePlayerRef.current) {
      livePlayerRef.current = new TTSStreamPlayer(
        () => {
          clearLiveSttTranscript();
          liveAudioStartedRef.current = true;
          liveSocketRef.current?.send("playback.started");
          setVoiceState("speaking");
        },
        () => {
          clearLiveSttTranscript();
          setLivePlaybackSegment("");
          liveSocketRef.current?.send("playback.finished");
          playbackSegmentTextsRef.current = [];
          playbackCoordinatorRef.current.release(playbackCoordinatorRef.current.snapshot());
          liveSocketRef.current?.clearActive();
          setLoading(false);
          setVoiceState("idle");
        },
        (playerError) => {
          clearLiveSttTranscript();
          setLivePlaybackSegment("");
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
        (text) => {
          setLivePlaybackSegment(text);
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
    clearLiveSttTranscript,
    selectedOutputDeviceId,
    settings?.voice_live_playback_prebuffer_ms,
    settings?.voice_live_playback_prebuffer_segments,
    settings?.voice_live_playback_start_lead_ms,
  ]);

  const ensureLiveVoice = useCallback(async () => {
    if (!sessionId) throw new Error("Сессия ещё создаётся");
    const player = ensureLivePlayer();
    // A conversation reset gives the microphone a new session URL. Reusing an
    // output socket from the previous session leaves STT working but gives the
    // backend no matching channel on which to stream its answer.
    if (liveSocketSessionIdRef.current !== sessionId) {
      liveSocketRef.current?.close();
      liveSocketRef.current = null;
      liveSocketSessionIdRef.current = null;
    }
    if (!liveSocketRef.current) {
      const onEvent = (event: VoiceServerEvent) => {
        if (event.type === "voice.utterance.started") {
          clearLiveSttTranscript();
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
          clearLiveSttTranscript();
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
          clearLiveSttTranscript();
          queueTextDelta(event.utterance_id, event.delta);
        } else if (event.type === "voice.text.completed") {
          clearLiveSttTranscript();
          flushPendingTextDeltas();
          showMemoryUpdates(event.memory_updates);
        } else if (event.type === "tts.segment.started") {
          clearLiveSttTranscript();
          latestPlaybackSegmentRef.current = event.text ?? "";
          if (avatarOwnsAudioRef.current) {
            setLivePlaybackSegment(event.text ?? "");
          }
          if (event.text) playbackSegmentTextsRef.current.push(event.text);
          liveSocketRef.current?.send("playback.segment.started", {
            text: event.text ?? "",
            generation: event.generation,
          });
          setVoiceState("speaking");
        } else if (event.type === "voice.utterance.finished") {
          clearLiveSttTranscript();
          setLivePlaybackSegment("");
          if (avatarOwnsAudioRef.current) {
            playbackCoordinatorRef.current.release(playbackCoordinatorRef.current.snapshot());
            liveSocketRef.current?.clearActive();
            setLoading(false);
            setVoiceState("idle");
          } else {
            livePlayerRef.current?.finish(event.utterance_id);
          }
        } else if (event.type === "voice.utterance.cancelled") {
          clearLiveSttTranscript();
          setLivePlaybackSegment("");
          flushPendingTextDeltas();
          livePlayerRef.current?.stop();
          stopVoicePlayback();
          playbackCoordinatorRef.current.cancel();
          liveSocketRef.current?.clearActive();
          setLoading(false);
          setVoiceState("idle");
        } else if (event.type === "voice.error") {
          clearLiveSttTranscript();
          flushPendingTextDeltas();
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
      liveSocketSessionIdRef.current = sessionId;
    }
    await player.unlock();
    await liveSocketRef.current.connect();
  }, [clearLiveSttTranscript, ensureLivePlayer, flushPendingTextDeltas, queueTextDelta, sessionId, showMemoryUpdates, speakTextInBrowser, stopVoicePlayback]);

  useEffect(() => () => {
    livePlayerRef.current?.stop();
    liveSocketRef.current?.close();
    liveSocketRef.current = null;
    liveSocketSessionIdRef.current = null;
    vadRecorderRef.current?.stop();
    pcmInputRef.current?.close();
    if (pendingTextDeltaTimerRef.current !== null) {
      window.clearTimeout(pendingTextDeltaTimerRef.current);
    }
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
    async (voiceRequestId: string): Promise<VoiceTtsStatusResponse | null> => {
      const started = Date.now();
      while (Date.now() - started < 30000) {
        const status = await syncVoiceTtsStatus(voiceRequestId);
        if (status?.status === "ready" || status?.status === "failed") {
          return status;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 500));
      }
      return null;
    },
    [syncVoiceTtsStatus],
  );

  useEffect(() => {
    if (!sessionId) return;
    for (const event of events) {
      if (event.type !== "coding.review_notification" && event.type !== "coding.attention_notification") {
        continue;
      }
      const voiceRequestId = getStringMetadata(event, "voice_request_id");
      const content = getStringMetadata(event, "notification");
      if (!voiceRequestId || !content || handledCodingSpeechRequestIdsRef.current.has(voiceRequestId)) {
        continue;
      }
      handledCodingSpeechRequestIdsRef.current.add(voiceRequestId);
      void pollVoiceTtsStatus(voiceRequestId).then((status) => {
        if (status?.status === "ready" && status.audio_url) {
          if (!avatarOwnsAudio) {
            void playAudioUrl(resolveApiUrl(status.audio_url));
          }
        } else if (status?.status === "failed" && browserSpeechSupported) {
          speakTextInBrowser(content);
        }
      });
    }
  }, [avatarOwnsAudio, browserSpeechSupported, events, playAudioUrl, pollVoiceTtsStatus, sessionId, speakTextInBrowser]);

  const scrollTimerRef = useRef<number | null>(null);
  useEffect(() => {
    if (!isActive || messages.length === 0 || scrollTimerRef.current !== null) return;
    // Streaming text can arrive many times per frame. Coalesce layout reads
    // and writes so a long answer does not enqueue a smooth scroll animation
    // for every token.
    scrollTimerRef.current = window.setTimeout(() => {
      scrollTimerRef.current = null;
      listRef.current?.scrollTo({
        top: listRef.current.scrollHeight,
        behavior: "auto",
      });
    }, 32);
  }, [isActive, messages]);

  const lastMessageCountRef = useRef(0);
  useEffect(() => {
    if (messages.length > lastMessageCountRef.current && listRef.current) {
      const messageElements = listRef.current.querySelectorAll<HTMLElement>(".message");
      if (messageElements.length > 0) {
        const newest = messageElements[messageElements.length - 1];
        if (newest) {
          animateMessagePop(newest);
        }
      }
    }
    lastMessageCountRef.current = messages.length;
  }, [messages]);

  const thinkingRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (loading && thinkingRef.current) {
      const dots = thinkingRef.current.querySelectorAll<HTMLElement>("span");
      const anim = animateThinkingWave(dots);
      return () => {
        anim?.cancel();
      };
    }
  }, [loading]);

  useEffect(() => () => {
    if (scrollTimerRef.current !== null) {
      window.clearTimeout(scrollTimerRef.current);
    }
  }, []);

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
      const isCodingNotificationSpeech = handledCodingSpeechRequestIdsRef.current.has(voiceRequestId);

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
        if (!avatarOwnsAudio && !isCodingNotificationSpeech) {
          void playAudioUrl(resolvedAudioUrl);
        }
      } else {
        const fallbackMessage = messagesRef.current.find(
          (message) => message.voiceRequestId === voiceRequestId,
        );
        const fallbackAlreadyStarted = fallbackMessage?.ttsStatus === "browser_fallback";
        const fallbackStarted = isCodingNotificationSpeech
          ? false
          : browserSpeechSupported && fallbackAlreadyStarted
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
  }, [avatarOwnsAudio, browserSpeechSupported, events, playAudioUrl, speakTextInBrowser]);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    clearLiveSttTranscript();
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

  const submitOnEnter = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    // Chat uses Enter for the common one-line send action.  Keep multiline
    // prompts available through Shift+Enter and never interrupt IME text
    // composition (important for Russian and other non-Latin input methods).
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing === true) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  };

  const toggleLive = async () => {
    if (!sessionId || !liveReady) return;
    if (liveConversation) {
      cancelPendingBargeIn();
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
    cancelPendingBargeIn();
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
          updateLiveSttTranscript(event.transcript, event.observation_only ? 3000 : 5000);
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
          clearLiveSttTranscript();
          updateConversationStatus("Слышу вас");
        } else if (event.type === "voice.input.finalizing") {
          updateConversationStatus("Распознаю");
        } else if (event.type === "conversation.turn_candidate") {
          updateConversationStatus("Проверяю конец фразы");
        } else if (event.type === "conversation.turn_completed") {
          updateConversationStatus("Распознаю");
        } else if (event.type === "conversation.phase" && event.phase) {
          if (event.phase === "speaking" || event.phase === "generating" || event.phase === "listening") {
            clearLiveSttTranscript();
          }
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
          if (event.action !== "respond" && event.action !== "backchannel") {
            clearLiveSttTranscript();
          }
          updateConversationStatus(event.action === "respond" || event.action === "backchannel"
            ? "Iris отвечает"
            : "Iris решила промолчать");
        } else if (event.type === "conversation.silent") {
          clearLiveSttTranscript();
          updateConversationStatus("Iris решила промолчать", 1800);
        } else if (event.type === "conversation.echo_rejected") {
          clearLiveSttTranscript();
          updateConversationStatus("Микрофон включён");
        } else if (event.type === "conversation.noise_ignored") {
          clearLiveSttTranscript();
          updateConversationStatus("Короткий шум пропущен", 900);
        } else if (event.type === "conversation.reaction") {
          updateConversationStatus(event.initiative ? "Iris вступает в разговор" : "Iris реагирует");
        } else if (event.type === "conversation.deferred") {
          clearLiveSttTranscript();
          updateConversationStatus("Iris подождёт подходящую паузу");
        } else if (event.type === "conversation.cancelled") {
          clearLiveSttTranscript();
          updateConversationStatus("Микрофон включён");
        } else if (event.type === "voice.input.error") {
          clearLiveSttTranscript();
          setError(event.message ?? "Не удалось обработать голосовой ввод");
        }
      });
      pcmInputRef.current = input;
      const recorder = new BrowserVadRecorder();
      vadRecorderRef.current = recorder;
      const capture = await recorder.start(
        (pcm16) => pcmInputRef.current?.sendPcm(pcm16),
        (nextState, event) => {
          // A transient sound must not interrupt the answer.  Cancel the
          // pending barge-in as soon as VAD drops out of confirmed speech.
          if (nextState !== "speech") cancelPendingBargeIn();
          if (event === "speech_started") {
            setVoiceState("recording");
            updateConversationStatus("Слышу вас");
            const utteranceId = liveSocketRef.current?.activeUtteranceId;
            if (utteranceId) {
              const confirmationMs = {
                // A short, loud cough can pass VAD. Require sustained audio
                // before interrupting a response, even at high sensitivity.
                low: 650,
                balanced: 450,
                high: 300,
              }[settings?.live_conversation_interruption_sensitivity ?? "balanced"];
              bargeInTimerRef.current = window.setTimeout(() => {
                bargeInTimerRef.current = null;
                // Do not let a delayed signal cancel a newer response.
                if (liveSocketRef.current?.activeUtteranceId === utteranceId) {
                  interruptAssistantSpeech();
                }
              }, confirmationMs);
            }
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
      cancelPendingBargeIn();
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
    if (nextMuted) cancelPendingBargeIn();
    vadRecorderRef.current.setMuted(nextMuted);
    setMicrophoneMuted(nextMuted);
    playMuteTone(nextMuted);
    updateConversationStatus(nextMuted ? "Микрофон выключен" : "Микрофон включён");
  }, [cancelPendingBargeIn, liveConversation, microphoneMuted, playMuteTone, updateConversationStatus]);

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

  const isDialogActive = isStarted || messages.length > 0 || liveConversation;

  const handleStart = async (event?: React.MouseEvent<HTMLElement>) => {
    if (event) animateButtonPress(event.currentTarget);
    clearLiveSttTranscript();
    setIsStarted(true);
    if (liveReady && liveVoiceSupported && !liveConversation) {
      await toggleLive();
    }
  };

  const handleFinish = async () => {
    clearLiveSttTranscript();
    cancelPendingBargeIn();
    vadRecorderRef.current?.stop();
    pcmInputRef.current?.close();
    pcmInputRef.current = null;
    vadRecorderRef.current = null;
    setLiveConversation(false);
    setMicrophoneMuted(false);
    interruptAssistantSpeech();
    stopVoicePlayback();
    setVoiceState("idle");
    try {
      await closeCurrentEpisode();
      await onStartNewDialog();
    } catch {
      // Ignore if session reset fails
    }
    setMessages([]);
    setIsStarted(false);
  };

  const startNewDialog = async () => {
    if (!sessionId || newDialogPending) return;
    setNewDialogPending(true);
    setError(null);
    clearLiveSttTranscript();
    try {
      // A new session must not inherit a live microphone stream or an answer
      // that was still playing in the previous dialog.
      cancelPendingBargeIn();
      vadRecorderRef.current?.stop();
      pcmInputRef.current?.close();
      pcmInputRef.current = null;
      vadRecorderRef.current = null;
      setLiveConversation(false);
      setMicrophoneMuted(false);
      interruptAssistantSpeech();
      await onStartNewDialog();
      setMessages([]);
      setIsStarted(false);
      setNewDialogConfirmationOpen(false);
    } catch (newDialogError) {
      setError(newDialogError instanceof Error ? newDialogError.message : "Не удалось начать новый диалог.");
    } finally {
      setNewDialogPending(false);
    }
  };

  const statusBadge = useMemo(() => {
    if (!isDialogActive) {
      return { text: "Ирис ждёт вас)", dotClass: "purple" };
    }
    if (voiceState === "speaking") {
      return { text: "Ирис говорит", dotClass: "green" };
    }
    if (voiceState === "thinking" || loading) {
      return { text: "Ирис думает", dotClass: "amber" };
    }
    if (voiceState === "recording") {
      return { text: "Ирис слушает", dotClass: "green" };
    }
    if (voiceState === "transcribing") {
      return { text: "Ирис распознаёт", dotClass: "amber" };
    }
    const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
    if (lastAssistant?.emotion === "joy" || liveMetadataRef.current.emotion === "joy") {
      return { text: "Ирис радуется", dotClass: "green" };
    }
    return { text: "Ирис радуется", dotClass: "green" };
  }, [isDialogActive, loading, messages, voiceState]);

  const currentEmotion = useMemo(() => {
    if (liveMetadataRef.current.emotion && liveMetadataRef.current.emotion !== "neutral") {
      return liveMetadataRef.current.emotion;
    }
    const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
    if (lastAssistant?.emotion) {
      return lastAssistant.emotion;
    }
    if (avatarStatus?.emotion_engine?.current_emotion) {
      return avatarStatus.emotion_engine.current_emotion;
    }
    return "neutral";
  }, [avatarStatus?.emotion_engine?.current_emotion, messages]);

  let lastAssistantIndex = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "assistant") {
      lastAssistantIndex = i;
      break;
    }
  }

  if (!isDialogActive) {
    return (
      <section className={`panel chat-panel is-idle${showInAppAvatar && isActive ? " has-in-app-avatar" : ""}`}>
        <IrisPortalBackground
          emotion={currentEmotion}
          voiceState={voiceState}
          loading={loading}
          isDialogActive={false}
          showInAppAvatar={showInAppAvatar && isActive}
        />
        <div className="chat-status-pill">
          <span>{statusBadge.text}</span>
          <span className={`status-pill-dot ${statusBadge.dotClass}`} />
        </div>
        <div className="chat-idle-stage">
          {showInAppAvatar && isActive && <InAppAvatarHost />}
          <div className="chat-start-banner">
            <svg className="banner-bg-svg" width="829" height="121" viewBox="0 0 829 121" fill="none" preserveAspectRatio="none">
              <defs>
                <clipPath id="banner-squircle-clip">
                  <path d="M0 60.5C0 31.8824 0 17.5736 8.7868 8.7868C17.5736 0 31.7157 0 60 0H769C797.284 0 811.426 0 820.213 8.7868C829 17.5736 829 31.8824 829 60.5C829 89.1176 829 103.426 820.213 112.213C811.426 121 797.284 121 769 121H60C31.7157 121 17.5736 121 8.7868 112.213C0 103.426 0 89.1176 0 60.5Z" />
                </clipPath>
              </defs>
              <image href="/figma/До активации диалога/baner.png" width="829" height="121" preserveAspectRatio="xMidYMid slice" clipPath="url(#banner-squircle-clip)" />
            </svg>
            <button
              className="chat-start-button"
              type="button"
              onClick={handleStart}
              title="Начать"
              aria-label="Начать"
            >
              <FigmaStartButtonBg className="btn-shape-bg" preserveAspectRatio="none" />
              <span className="btn-content">
                <IrisPetalsIcon size={28} />
                <span>НАЧАТЬ</span>
              </span>
            </button>
          </div>
        </div>
        <AppDialog
          open={newDialogConfirmationOpen}
          title="Начать новый диалог?"
          description="Текущий диалог будет завершён и сохранён в истории. Начнётся новый разговор с Iris."
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
      </section>
    );
  }

  return (
    <section className={`panel chat-panel is-active${showInAppAvatar && isActive ? " has-in-app-avatar" : ""}`}>
      <IrisPortalBackground
        emotion={currentEmotion}
        voiceState={voiceState}
        loading={loading}
        isDialogActive={true}
        showInAppAvatar={showInAppAvatar && isActive}
      />
      <div className="chat-status-pill">
        <span>{statusBadge.text}</span>
        <span className={`status-pill-dot ${statusBadge.dotClass}`} />
      </div>
      {showInAppAvatar && isActive && <InAppAvatarHost />}
      <div className="chat-content">
        {memoryNotice && (
          <div className="notice" role="status">
            {memoryNotice}
            <button className="text-button" onClick={onOpenMemory}>Открыть память</button>
          </div>
        )}
        <IrisSubtitles
          messages={messages}
          loading={loading}
          voiceState={voiceState}
          activeAudio={activeAudioElement}
          livePlaybackSegment={livePlaybackSegment}
          containerRef={listRef}
          onOpenMemory={onOpenMemory}
        />

        {error && (
          <div className="error-banner" role="alert">
            <IconInterfaceAlertAlarmBell2 size={18} aria-hidden="true" />
            {error}
            {retryText && (
              <button className="text-button" type="button" onClick={() => { setDraft(retryText); setRetryText(null); }}>
                Повторить
              </button>
            )}
          </div>
        )}

        <div className="chat-composer-container">
          <form className="chat-form" onSubmit={onSubmit}>
            <div className="chat-composer">
              <FigmaInputPlateFullBg className="chat-composer-bg" preserveAspectRatio="none" />
              <div className="chat-composer-inner">
                <textarea
                  value={liveSttTranscript || draft}
                  onFocus={() => {
                    if (liveSttTranscript) clearLiveSttTranscript();
                  }}
                  onClick={() => {
                    if (liveSttTranscript) clearLiveSttTranscript();
                  }}
                  onChange={(event) => {
                    if (liveSttTranscript) clearLiveSttTranscript();
                    setDraft(event.target.value);
                  }}
                  onKeyDown={(event) => {
                    if (liveSttTranscript && event.key !== "Enter") {
                      clearLiveSttTranscript();
                    }
                    submitOnEnter(event);
                  }}
                  placeholder={liveSttTranscript ? "" : "Ввод сообщения..."}
                  rows={1}
                  title="Enter — отправить сообщение; Shift+Enter — новая строка"
                />
                <button
                  className="primary-button send-button"
                  type="submit"
                  disabled={!sessionId || sessionStarting || loading || !draft.trim().length}
                  onClick={(e) => animateButtonPress(e.currentTarget)}
                  aria-label={sessionStarting ? "Подготавливаем сессию" : loading ? "Отправка сообщения" : "Отправить сообщение"}
                  title={sessionStarting ? "Подготавливаем сессию" : loading ? "Отправка сообщения" : "Отправить сообщение"}
                >
                  <SendHorizontal size={18} aria-hidden="true" />
                </button>
              </div>
            </div>

            <div className="chat-dock-toolbar voice-controls">
              <FigmaDockBg className="dock-bg-svg" preserveAspectRatio="none" />
              <div className="dock-left-actions">
                <div className="dock-dual-pill">
                  <FigmaDualMediaButtonBg className="dual-pill-bg" preserveAspectRatio="none" />
                  <button
                    className={`dock-dual-btn ${microphoneMuted ? "is-muted" : ""}`}
                    disabled={!liveVoiceSupported || !liveReady || voiceState === "stopping"}
                    onClick={(e) => {
                      animateButtonPress(e.currentTarget);
                      if (!liveConversation) {
                        void toggleLive();
                      } else {
                        toggleMicrophoneMute();
                      }
                    }}
                    title={
                      microphoneMuted
                        ? "Микрофон выключен (нажмите, чтобы включить)"
                        : "Микрофон включён (нажмите, чтобы выключить)"
                    }
                    aria-label="Live"
                    type="button"
                  >
                    <FigmaMicIcon width={24} height={26} />
                  </button>
                  <button
                    className={`dock-dual-btn ${soundMuted ? "is-muted" : ""}`}
                    onClick={(e) => {
                      animateButtonPress(e.currentTarget);
                      toggleSoundMute();
                    }}
                    title={soundMuted ? "Звук выключен (нажмите, чтобы включить)" : "Звук включён (нажмите, чтобы выключить)"}
                    aria-label={soundMuted ? "Звук выключен" : "Звук включён"}
                    type="button"
                  >
                    <FigmaHeadphonesIcon width={26} height={25} />
                  </button>
                </div>

                <button
                  className="dock-icon-btn"
                  onClick={(e) => {
                    animateButtonPress(e.currentTarget);
                    onOpenSettings?.();
                  }}
                  title="Настройки"
                  aria-label="Параметры"
                  type="button"
                >
                  <FigmaSquareButtonBg className="btn-shape-bg" preserveAspectRatio="none" />
                  <span className="btn-content"><FigmaSettingsIcon width={26} height={26} /></span>
                </button>
              </div>

              <button
                className="dock-finish-btn"
                type="button"
                onClick={(e) => {
                  animateButtonPress(e.currentTarget);
                  handleFinish();
                }}
                title="Завершить"
                aria-label="Завершить"
              >
                <FigmaFinishButtonBg className="btn-shape-bg" preserveAspectRatio="none" />
                <span className="btn-content">
                  <FigmaExitIcon />
                  <span>Завершить</span>
                </span>
              </button>

              <button
                className="dock-new-dialog-btn new-dialog-button"
                disabled={!sessionId || sessionStarting || newDialogPending || voiceState === "recording" || voiceState === "transcribing"}
                onClick={(e) => {
                  animateButtonPress(e.currentTarget);
                  setNewDialogConfirmationOpen(true);
                }}
                title="Новый диалог"
                aria-label="Новый диалог"
                type="button"
              >
                <FigmaNewChatButtonBg className="btn-shape-bg" preserveAspectRatio="none" />
                <span className="btn-content">
                  <FigmaNewChatIcon />
                  <span>Новый диалог</span>
                </span>
              </button>
            </div>
          </form>
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
        description="Текущий диалог будет завершён и сохранён в истории. Начнётся новый разговор с Iris."
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

  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (listRef.current && filteredEvents.length > 0) {
      animateStaggerCards(listRef.current, ".event-row", 30);
    }
  }, [filteredEvents, levelFilter]);

  return (
    <section className="panel events-panel">
      {compact ? <div className="events-toolbar"><button className="icon-button" onClick={(e) => { animateButtonPress(e.currentTarget); void onRefreshEvents(); }} aria-label="Обновить журнал событий" title="Обновить журнал событий">
          <IconInterfaceSpirals size={16} />
        </button></div> : <div className="panel-header">
        <div><h2>Журнал системы</h2><span>Технические события и диагностика</span></div>
        <button className="secondary" onClick={(e) => { animateButtonPress(e.currentTarget); void onRefreshEvents(); }}>
          <IconInterfaceSpirals size={16} aria-hidden="true" />
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
              onClick={(e) => {
                animateTabSwitch(e.currentTarget);
                setLevelFilter(level);
              }}
            >
              {labels[level]}
            </button>
          );
          },
        )}
      </div>

      <div className="event-list" ref={listRef}>
        {filteredEvents.length === 0 && (
          <div className="empty-state"><IconInterfaceContentArchive size={28} aria-hidden="true" /><strong>Событий нет</strong><span>Для этого фильтра пока ничего не найдено.</span></div>
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
                <strong data-i18n-skip>{event.message}</strong>
              </div>
              <details className="event-details"><summary>Технические данные</summary><pre>{JSON.stringify(event.metadata, null, 2)}</pre></details>
            </article>
          ))}
      </div>
    </section>
  );
}

export function SettingsPage({
  settings,
  avatarStatus,
  avatarOverlay,
  events,
  onRefreshEvents,
  onRefreshAvatar,
  onAvatarOverlayChanged,
  onInterfaceLocaleChange,
  onSettingsChanged,
}: {
  settings: PublicSettings | null;
  avatarStatus: AvatarStatusResponse | null;
  avatarOverlay: AvatarOverlaySettings | null;
  events: BackendEvent[];
  onRefreshEvents: () => Promise<void>;
  onRefreshAvatar: () => Promise<void>;
  onAvatarOverlayChanged: (overlay: AvatarOverlaySettings | null) => void;
  onInterfaceLocaleChange: (locale: InterfaceLocale) => void;
  onSettingsChanged: (settings: PublicSettings) => void;
}) {
  const [activeSection, setActiveSection] = useState<SettingsSection>("conversation");
  const [interfaceLocale, setInterfaceLocale] = useState<InterfaceLocale>("ru");
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
    setInterfaceLocale(nextSettings.interface_locale === "en" ? "en" : "ru");
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
        <div className="empty-state"><IconInterfaceAlertAlarmBell2 size={28} aria-hidden="true" /><strong>Настройки недоступны</strong><span>Подключитесь к сервису и попробуйте ещё раз.</span></div>
      </section>
    );
  }

  const ttsProviderLabel = settings.voice_tts_provider === "teratts" ? "TeraTTSv2" : settings.voice_tts_provider;
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
    "system-interface": { title: "Интерфейс", description: "Общие настройки интерфейса." },
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
  const settingsContentRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (settingsContentRef.current) {
      animatePageEnter(settingsContentRef.current);
      animateStaggerCards(
        settingsContentRef.current,
        "fieldset:not([hidden]), .settings-group:not([hidden]), .settings-grid > *, .system-card, .avatar-placement, .avatar-summary-grid, .avatar-options > *",
        30,
      );
    }
  }, [activeSection]);

  return (
    <section className="panel settings-panel">
      <SettingsNavigation current={activeSection} onChange={setActiveSection} />

      <div className="settings-content" ref={settingsContentRef}>
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

        <div className="form-grid settings-form" hidden={activeSection !== "system-interface"}>
          <fieldset className="settings-group">
            <legend>Интерфейс</legend>
            <label>
              Язык приложения
              <CustomSelect
                value={interfaceLocale}
                onChange={(event) => {
                  const nextValue = event.target.value as InterfaceLocale;
                  const previousValue = interfaceLocale;
                  setInterfaceLocale(nextValue);
                  onInterfaceLocaleChange(nextValue);
                  saveRuntimeSetting(
                    { interface_locale: nextValue },
                    () => {
                      setInterfaceLocale(previousValue);
                      onInterfaceLocaleChange(previousValue);
                    },
                  );
                }}
              >
                <option value="ru">Русский</option>
                <option value="en">Английский</option>
              </CustomSelect>
              <small>Выберите язык кнопок, меню и системных подсказок.</small>
            </label>
          </fieldset>
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
            interfaceLocale={interfaceLocale}
            onRefresh={onRefreshAvatar}
            onOverlayChanged={onAvatarOverlayChanged}
            onSettingsChanged={onSettingsChanged}
          />
        </div>

        <div className="form-grid settings-form" hidden={activeSection === "avatar" || activeSection === "system-interface" || activeSection === "system-overview" || ["models", "backups", "maintenance", "events"].includes(activeSection)}>
        <fieldset className="settings-group" hidden={activeSection !== "voice"}>
          <legend>Основное</legend>
          <label>
            Язык голосового ввода
            <CustomSelect
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
            </CustomSelect>
          </label>
        </fieldset>

        <fieldset className="settings-group" hidden={activeSection !== "voice-devices"}>
          <legend>Устройства</legend>
          <label>
            Профиль микрофона
            <CustomSelect
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
            </CustomSelect>
            <small>Управляет эхоподавлением и шумоподавлением браузера для записи и живого режима.</small>
          </label>

          <label>
            Источник входа (микрофон)
            <CustomSelect
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
            </CustomSelect>
            <small>Используется для единственного голосового режима Live.</small>
          </label>

          <label>
            Источник вывода (наушники или колонки)
            <CustomSelect
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
            </CustomSelect>
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
            <CustomSelect
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
            </CustomSelect>
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
            <CustomSelect value={voiceTtsStyle} onChange={(event) => void changeVoiceStyle(event.target.value)} disabled={saving}>
              <option value="auto">Авто — по эмоции нейросети</option>
              <option value="calm">Спокойно</option>
              <option value="normal">Обычно</option>
              <option value="energetic">Энергично</option>
              <option value="thoughtful">Задумчиво</option>
              <option value="assertive">Напористо</option>
            </CustomSelect>
            <small>Действует до перезапуска приложения.</small>
          </label>

          <label>
            Выразительность
            <CustomSelect value={voiceExpressionLevel} onChange={(event) => void changeVoiceExpression(event.target.value)} disabled={saving}>
              <option value="minimal">Минимальная — почти нейтрально</option>
              <option value="natural">Естественная — рекомендовано</option>
              <option value="noticeable">Заметная — сильнее эмоции</option>
            </CustomSelect>
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
            <CustomSelect
              value={liveSettings.live_conversation_participant_mode}
              onChange={(event) => updateLiveSetting(
                "live_conversation_participant_mode",
                event.target.value as LiveConversationSettings["live_conversation_participant_mode"],
              )}
            >
              <option value="one_to_one">Один на один</option>
              <option value="group">Несколько собеседников</option>
            </CustomSelect>
          </label>

          <label>
            Охотность вступать
            <CustomSelect
              value={liveSettings.live_conversation_engagement}
              onChange={(event) => updateLiveSetting(
                "live_conversation_engagement",
                event.target.value as LiveConversationSettings["live_conversation_engagement"],
              )}
            >
              <option value="low">Сдержанная</option>
              <option value="balanced">Сбалансированная</option>
              <option value="high">Разговорчивая</option>
            </CustomSelect>
          </label>

          <label>
            Инициативность
            <CustomSelect
              value={liveSettings.live_conversation_initiative}
              onChange={(event) => updateLiveSetting(
                "live_conversation_initiative",
                event.target.value as LiveConversationSettings["live_conversation_initiative"],
              )}
            >
              <option value="off">Выключена</option>
              <option value="rare">Редкая</option>
              <option value="balanced">Сбалансированная</option>
            </CustomSelect>
          </label>

          <label>
            Прямое обращение
            <CustomSelect
              value={liveSettings.live_conversation_address_strictness}
              onChange={(event) => updateLiveSetting(
                "live_conversation_address_strictness",
                event.target.value as LiveConversationSettings["live_conversation_address_strictness"],
              )}
            >
              <option value="relaxed">Свободное</option>
              <option value="balanced">Сбалансированное</option>
              <option value="strict">Строгое</option>
            </CustomSelect>
          </label>

          <label>
            Чувствительность к перебиванию
            <CustomSelect
              value={liveSettings.live_conversation_interruption_sensitivity}
              onChange={(event) => updateLiveSetting(
                "live_conversation_interruption_sensitivity",
                event.target.value as LiveConversationSettings["live_conversation_interruption_sensitivity"],
              )}
            >
              <option value="low">Низкая</option>
              <option value="balanced">Сбалансированная</option>
              <option value="high">Высокая</option>
            </CustomSelect>
          </label>

          <label>
            Терпимость к паузам
            <CustomSelect
              value={liveSettings.live_conversation_pause_tolerance}
              onChange={(event) => updateLiveSetting(
                "live_conversation_pause_tolerance",
                event.target.value as LiveConversationSettings["live_conversation_pause_tolerance"],
              )}
            >
              <option value="short">Короткая</option>
              <option value="natural">Естественная</option>
              <option value="patient">Терпеливая</option>
            </CustomSelect>
          </label>

          <label>
            Выраженность эмоций
            <CustomSelect
              value={liveSettings.live_conversation_emotion_expression}
              onChange={(event) => updateLiveSetting(
                "live_conversation_emotion_expression",
                event.target.value as LiveConversationSettings["live_conversation_emotion_expression"],
              )}
            >
              <option value="subtle">Тонкая</option>
              <option value="natural">Естественная</option>
              <option value="strong">Яркая</option>
            </CustomSelect>
          </label>

          <label>
            Восстановление настроения
            <CustomSelect
              value={liveSettings.live_conversation_mood_recovery}
              onChange={(event) => updateLiveSetting(
                "live_conversation_mood_recovery",
                event.target.value as LiveConversationSettings["live_conversation_mood_recovery"],
              )}
            >
              <option value="slow">Медленное</option>
              <option value="natural">Естественное</option>
              <option value="fast">Быстрое</option>
            </CustomSelect>
          </label>

          <label>
            Влияние недавних событий
            <CustomSelect
              value={liveSettings.live_conversation_recent_event_weight}
              onChange={(event) => updateLiveSetting(
                "live_conversation_recent_event_weight",
                event.target.value as LiveConversationSettings["live_conversation_recent_event_weight"],
              )}
            >
              <option value="light">Слабое</option>
              <option value="balanced">Сбалансированное</option>
              <option value="strong">Сильное</option>
            </CustomSelect>
          </label>

          <label>
            Защита от собственного голоса
            <CustomSelect
              value={liveSettings.live_conversation_echo_mode}
              onChange={(event) => updateLiveSetting(
                "live_conversation_echo_mode",
                event.target.value as LiveConversationSettings["live_conversation_echo_mode"],
              )}
            >
              <option value="auto">Автоматически</option>
              <option value="half_duplex">Не слушать во время ответа</option>
            </CustomSelect>
          </label>
        </fieldset>

        <fieldset className="settings-group" hidden={activeSection !== "memory"}>
          <legend>Память</legend>
          <label>
            Режим сохранения
            <CustomSelect
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
            </CustomSelect>
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
  icon: any;
  directSection?: SettingsSection;
  items: Array<{ section: SettingsSection; label: string }>;
}> = [
  {
    id: "behavior",
    label: "Поведение",
    icon: IconInterfacePageControllerSettings,
    items: [{ section: "conversation", label: "Живой разговор" }],
  },
  {
    id: "avatar",
    label: "Аватар",
    icon: IconInterfaceUserQueenCrown,
    directSection: "avatar",
    items: [],
  },
  {
    id: "voice",
    label: "Голос",
    icon: IconEntertainmentVolumeLevelHigh,
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
    icon: IconComputerRobotCyborg1,
    directSection: "memory",
    items: [],
  },
  {
    id: "system",
    label: "Система",
    icon: IconComputerScreenCurve,
    items: [
      { section: "system-interface", label: "Интерфейс" },
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
              onClick={(e) => {
                animateButtonPress(e.currentTarget);
                onChange(group.directSection!);
              }}
            >
              <group.icon size={20} aria-hidden="true" />
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
              onClick={(e) => {
                animateButtonPress(e.currentTarget);
                setExpanded((value) => ({ ...value, [group.id]: !isExpanded }));
              }}
            >
              <group.icon size={20} aria-hidden="true" />
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
      onClick={(e) => {
        animateTabSwitch(e.currentTarget);
        onClick(section);
      }}
    >
      <span>{label}</span>
    </button>
  );
}

function ModelManager() {
  const [models, setModels] = useState<ManagedModel[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

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

  useEffect(() => {
    if (listRef.current && models.length > 0) {
      animateStaggerCards(listRef.current, ".settings-group", 40);
    }
  }, [models.length]);

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
    <section className="system-card" aria-label="Управление моделями" ref={listRef}>
      <div className="panel-header"><div><h2>Модели</h2><span>Хранятся вне папки приложения</span></div><button className="secondary" onClick={(e) => { animateButtonPress(e.currentTarget); void refresh(); }}><IconInterfaceSpirals size={16} aria-hidden="true" />Обновить</button></div>
      {models.map((model) => {
        const percent = model.total_bytes > 0 ? Math.min(100, Math.round((model.downloaded_bytes / model.total_bytes) * 100)) : 0;
        return <div className="settings-group" key={model.id}>
          <strong>{model.name} {model.version}</strong>
          <span>{model.installed ? "Установлена и проверена" : model.status === "downloading" ? `Загружаем: ${percent}%` : "Не установлена"}</span>
          {model.status === "failed" && <span className="notice">{model.error}</span>}
          {model.status === "downloading" && <progress value={percent} max="100">{percent}%</progress>}
          <div className="model-actions">
            {!model.installed && <button className="primary-button" onClick={(e) => { animateButtonPress(e.currentTarget); void install(model.id); }} disabled={model.status === "downloading"}>{model.status === "failed" ? "Повторить загрузку" : "Скачать"}</button>}
            {model.installed && <button className="secondary" onClick={(e) => { animateButtonPress(e.currentTarget); void remove(model.id); }}>Удалить</button>}
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
  const listRef = useRef<HTMLDivElement | null>(null);

  const refresh = useCallback(async () => {
    try {
      setBackups(await getBackups());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Резервные копии недоступны.");
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    if (listRef.current && backups.length > 0) {
      animateStaggerCards(listRef.current, ".info-row", 35);
    }
  }, [backups.length]);

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
      <div className="panel-header"><div><h2>Резервные копии</h2><span>Память и настройки, срок хранения — 30 дней</span></div><button className="primary-button" onClick={(e) => { animateButtonPress(e.currentTarget); void create(); }} disabled={busy}>{busy ? "Создаём…" : "Создать копию"}</button></div>
      {backups.length ? <div className="settings-grid" ref={listRef}>{backups.slice(0, 3).map((backup) => <InfoRow key={backup.name} label={backup.name} value={`${Math.ceil(backup.size_bytes / 1024)} КБ · ${formatTime(backup.created_at)}`} />)}</div> : <span className="card-empty">Резервных копий пока нет.</span>}
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
    <div className="panel-header"><div><h2>Обслуживание данных</h2><span>Необратимые действия вынесены отдельно</span></div><IconComputerDatabase size={20} aria-hidden="true" /></div>
    <div className="maintenance-actions">
      <button className="secondary" disabled={busy} onClick={(e) => { animateButtonPress(e.currentTarget); setPendingAction({ title: "Перестроить индекс памяти?", description: "Сами записи останутся на месте. Iris заново подготовит их для поиска.", action: reindexMemories, success: "Индекс памяти перестроен." }); }}>Перестроить индекс памяти</button>
      <button className="secondary danger-button" disabled={busy} onClick={(e) => { animateButtonPress(e.currentTarget); setPendingAction({ title: "Очистить долгосрочную память?", description: "История диалогов сохранится, но восстановить записи памяти будет нельзя.", action: clearMemories, success: "Долгосрочная память очищена." }); }}>Очистить память</button>
      <button className="danger-button" disabled={busy} onClick={(e) => { animateButtonPress(e.currentTarget); setPendingAction({ title: "Сбросить все данные Iris?", description: "История, сводки и долгосрочная память будут удалены без возможности восстановления.", action: resetAllCompanionData, success: "Все данные помощника удалены." }); }}>Сбросить все данные</button>
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
  interfaceLocale,
  onRefresh,
  onOverlayChanged,
  onSettingsChanged,
}: {
  avatarStatus: AvatarStatusResponse | null;
  overlay: AvatarOverlaySettings | null;
  placement: AvatarPlacement;
  inAppVisible: boolean;
  interfaceLocale: InterfaceLocale;
  onRefresh: () => Promise<void>;
  onOverlayChanged: (overlay: AvatarOverlaySettings | null) => void;
  onSettingsChanged: (settings: PublicSettings) => void;
}) {
  const defaultTestPhrase = interfaceLocale === "en" ? "Avatar test." : "Проверка аватара.";
  const [phrase, setPhrase] = useState(defaultTestPhrase);
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
    setPhrase((current) => current === "Проверка аватара." || current === "Avatar test."
      ? defaultTestPhrase
      : current);
  }, [defaultTestPhrase]);
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
        <button className="icon-button" onClick={() => void onRefresh()} disabled={busy} aria-label="Обновить статус аватара" title="Обновить статус аватара"><IconInterfaceSpirals size={16} /></button>
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
          <CustomSelect value={emotion} onChange={(event) => setEmotion(event.target.value)} disabled={!enabled || busy}>
            {Object.entries(AVATAR_EMOTION_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </CustomSelect>
        </label>
        <label>
          Тестовый жест
          <CustomSelect value={gesture} onChange={(event) => setGesture(event.target.value)} disabled={!enabled || busy}>
            {Object.entries(AVATAR_GESTURE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </CustomSelect>
        </label>
        <label>
          Интенсивность движения {motionIntensity.toFixed(1)}
          <input min="0" max="1" step="0.1" type="range" value={motionIntensity} onChange={(event) => setMotionIntensity(Number(event.target.value))} disabled={!enabled || busy} />
        </label>
        </div>
      <div className="avatar-test-actions">
        <button className="primary-button" onClick={(e) => { animateButtonPress(e.currentTarget); void run(() => sendAvatarTestPhrase({ text: phrase, emotion }), "Тестовая фраза отправлена."); }} disabled={!enabled || busy || !phrase.trim()}>Отправить фразу</button>
        <button className="secondary" onClick={(e) => { animateButtonPress(e.currentTarget); void run(() => sendAvatarTestEmotion({ emotion, intensity: 1 }), "Эмоция отправлена."); }} disabled={!enabled || busy}>Отправить эмоцию</button>
        <button className="secondary" onClick={(e) => { animateButtonPress(e.currentTarget); void run(() => sendAvatarTestGesture({ gesture, intensity: motionIntensity, interrupt: true }), "Тестовый жест отправлен."); }} disabled={!enabled || busy}>Отправить жест</button>
        <button className="secondary" onClick={(e) => { animateButtonPress(e.currentTarget); void run(stopAvatar, "Движение сброшено."); }} disabled={!enabled || busy}>Сбросить движение</button>
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
