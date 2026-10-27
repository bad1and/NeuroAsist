import { Disclosure } from "./components/Disclosure";
export { SettingsPage } from "./settings/SettingsPage";
import type { SettingsSection, SettingsNavigationRequest } from "./settings/registry";
import { MaterialButton, MaterialButtonGroup } from "./components/MaterialButton";


import { BackgroundConversationControls, BackgroundConversationExpandButton } from "./components/BackgroundConversationControls";


import { CorpusSurface } from "./components/CorpusSurface";
import { useDockScale } from "./components/useDockScale";
import { ChatWelcomeScenery } from "./components/ChatWelcomeScenery";
import { useAvatarPresentation } from "./components/useAvatarPresentation";
import { IconInterfaceHome2, IconMailChatBubbleTextSquare, IconInterfaceTimeStopWatchCircle, IconComputerRobotCyborg1, IconInterfacePageControllerSettings, IconProgrammingScript2, IconInterfaceCursorArrow2 } from "./CustomIcons";
import { FormEvent, KeyboardEvent as ReactKeyboardEvent, lazy, memo, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { IconInterfaceCursorArrow2 as SendHorizontal, IconMailChatBubblePlus as MessageSquarePlus } from "./CustomIcons";
const AvatarDevStudioStandalonePage = lazy(() => import("./components/AvatarDevPanel").then(module => ({ default: module.AvatarDevStudioStandalonePage })));





import { FigmaStartFlowerIcon, FigmaMicIcon, FigmaHeadphonesIcon, FigmaSettingsIcon, FigmaExitIcon, FigmaNewChatIcon, FigmaDockBg, FigmaInputPlateFullBg } from "./FigmaIcons";

function IrisPetalsIcon({ size = 20, className = "" }: { size?: number; className?: string }) {
  return (
    <FigmaStartFlowerIcon width={size} height={size} className={className} />
  );
}

import { getAvatarStatus, getAvatarOverlay, getEvents, getTimelineMessages, getConversationSession, getCharacterState, getSettings, getConversationDebug, getStatus, getReadiness, getVoiceTtsStatus, interruptVoiceSession, isDesktopManaged, resetConversationSession, resolveApiUrl, sendChatMessage, sendLiveTextMessage, voiceWebSocketUrl, voiceInputWebSocketUrl, WS_EVENTS_URL, type ConversationBoundaryReason } from "./api";
import type { BackendEvent, AvatarStatusResponse, AvatarOverlaySettings, ChatMessage, EventLevel, PublicSettings, ReadinessResponse, StatusResponse, TimelineJournalItem, VoiceTtsStatusResponse, MemoryUpdate, ConversationDebug, InterfaceLocale, VoiceState } from "./types";
import type { VoiceServerEvent } from "./types";
import { PlaybackCoordinator, TTSStreamPlayer, VoiceSocketClient } from "./voice-live";
import { canSelectAudioOutput, setAudioElementOutput } from "./audio-devices";
import { BrowserVadRecorder, PcmInputClient } from "./vad";
import { LoadingRing } from "./components/LoadingRing";
import { WorkspaceView } from "./components/WorkspaceView";
import { OverviewPage } from "./overview";
import { GlobalSearch } from "./components/GlobalSearch";
import { ChangelogController } from "./components/Changelog";


import { useShortcutCommands, useShortcutBindings, formatBinding } from "./shortcuts";
import type { SearchFocus } from "./search-navigation";
import { FirstConversationSetup } from "./components/FirstConversationSetup";
import { ReminderDelivery } from "./components/ReminderDelivery";



import { DocumentAttachment } from "./components/DocumentAttachment";
import { configureAvatarPlacement, getAvatarHostStatus, getDesktopRuntime, initialCoreStatus, isDesktopApp, listenForAppCloseRequest, listenForAvatarStatus, listenForAvatarVisibility, listenForCoreStatus, restartDesktopCore, importDesktopBackup, restoreDesktopBackup, restartAvatar, setDesktopInterfaceLocale, shouldWaitForInAppAvatar, startGracefulShutdown, type CoreStatus, type AvatarHostStatus, openQaStudioWindow, closeQaStudioWindow, isQaStudioWindowOpen, listenForQaStudioState } from "./desktop";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { StartupScreen } from "./components/StartupScreen";
import { getStartupStage } from "./startup";
import { useIndicatorAnimations } from "./animations/indicators";
import { WindowChrome } from "./components/WindowChrome";

import { AppDialog } from "./components/AppDialog";



import { InAppAvatarHost } from "./components/InAppAvatarHost";
import { IrisPortalBackground } from "./components/IrisPortalBackground";
import { IrisSubtitles } from "./components/IrisSubtitles";
import { ConversationSurface } from "./components/ConversationSurface";
import { RetrievalNotifications } from "./retrievalNotifications";
import { NotificationHost } from "./components/NotificationHost";

import { notify, notifyBackendEvent } from "./notifications";
import { audioAnalyzer } from "./audio-analyzer";
import { initialInterfaceLocale, interfaceIntlLocale, INTERFACE_LOCALE_CHANGED_EVENT, setInterfaceLocalePreference, useInterfaceLocale } from "./i18n";
import { animateButtonPress, animateMessagePop, animateTabSwitch, animateThinkingWave, useInterfaceMotion, useDrawerMotion, usePresence } from "./animations";

type AppView = "overview" | "chat" | "journal" | "memory" | "state" | "coding" | "settings";

const JournalPage = lazy(() => import("./journal").then(({ JournalPage }) => ({ default: JournalPage })));
const MemoryPage = lazy(() => import("./memory").then(({ MemoryPage }) => ({ default: memo(MemoryPage) })));
const StatePage = lazy(() => import("./state").then(({ StatePage }) => ({ default: StatePage })));
const CodingAgentPage = lazy(() => import("./coding").then(({ CodingAgentPage }) => ({ default: CodingAgentPage })));
const LazyChatPage = lazy(() => Promise.resolve({ default: ChatPage }));
const LazySettingsPage = lazy(() => import("./settings/SettingsPage").then(module => ({ default: module.SettingsPage })));

const SIDEBAR_COLLAPSED_STORAGE_KEY = "iris.sidebar.collapsed";
const CHAT_ERROR_AUTO_DISMISS_MS = 8_000;
type WsState = "connected" | "disconnected" | "reconnecting";
type LevelFilter = "all" | EventLevel;

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

function voiceReadinessProgress(readiness: ReadinessResponse | null): number {
  if (!readiness) return 0.08;
  if (readiness.live_ready) return 0.72;
  const readyParts = [
    readiness.text_chat === "ready",
    readiness.stt === "ready",
    readiness.tts === "ready",
    readiness.vad === "ready" || readiness.vad === "fallback",
  ].filter(Boolean).length;
  return 0.08 + readyParts * 0.14;
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

function isQaStudioWindow(): boolean {
  if (typeof window === "undefined") return false;
  if ((window as unknown as { __IRIS_VIEW__?: string }).__IRIS_VIEW__ === "qa-studio") {
    return true;
  }
  if (isDesktopApp()) {
    try {
      if (getCurrentWindow().label === "qa_studio") {
        return true;
      }
    } catch {
      // Ignore
    }
  }
  try {
    if (window.location) {
      const params = new URLSearchParams(window.location.search);
      if (params.get("view") === "qa-studio" || window.location.hash === "#qa-studio") {
        return true;
      }
    }
  } catch {
    // Ignore
  }
  return false;
}

export default function App() {
  useIndicatorAnimations();
  if (isQaStudioWindow()) {
    return <Suspense fallback={<p role="status">Загрузка студии…</p>}><AvatarDevStudioStandalonePage /></Suspense>;
  }
  return <MainApp />;
}

function MainApp() {
  const [recoveryBackup, setRecoveryBackup] = useState<string | null>(null);
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [recoveryError, setRecoveryError] = useState<string | null>(null);
  const desktopManaged = isDesktopManaged();
  const [coreStatus, setCoreStatus] = useState<CoreStatus>(initialCoreStatus);
  const [coreError, setCoreError] = useState<string | null>(window.__NEUROASIST_DESKTOP_CONFIG__?.coreError ?? null);
  const [showStartup, setShowStartup] = useState(desktopManaged);
  const [startupRevealRequested, setStartupRevealRequested] = useState(false);
  const [avatarHostStatus, setAvatarHostStatus] = useState<AvatarHostStatus | null>(null);
  const [isClosing, setIsClosing] = useState(false);
  const [retryingCore, setRetryingCore] = useState(false);
  const [startupAttempt, setStartupAttempt] = useState(0);
  const appShellRef = useRef<HTMLDivElement>(null);
  const readinessEpoch = useRef(0);
  const [activeView, setActiveView] = useState<AppView>("overview");
  useInterfaceMotion(appShellRef, activeView, !showStartup);
  const [globalSearchOpen, setGlobalSearchOpen] = useState(false);
  const [changelogOpen, setChangelogOpen] = useState(false);
  const handleOpenChangelog = useCallback(() => { setGlobalSearchOpen(false); setChangelogOpen(true); }, []);
  const [historyFocus, setHistoryFocus] = useState<SearchFocus>();
  const [historyEpisodeRequest, setHistoryEpisodeRequest] = useState<{ episode: TimelineJournalItem; requestId: string }>();
  const [memoryFocus, setMemoryFocus] = useState<SearchFocus>();
  const [visitedViews, setVisitedViews] = useState<Set<AppView>>(() => new Set<AppView>(["overview", "chat"]));
  const [settingsNavigationRequest, setSettingsNavigationRequest] = useState<SettingsNavigationRequest>();
  const [navigationOpen, setNavigationOpen] = useState(false);
  const navigationScrim = usePresence<HTMLButtonElement>(navigationOpen, 0);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === "true";
    } catch {
      return false;
    }
  });
  const menuToggleRef = useRef<HTMLButtonElement>(null);
  const backgroundConversationRef = useRef<HTMLDivElement>(null);
  const settingsDraftRef = useRef(false);
  const [hasSettingsDraft, setHasSettingsDraft] = useState(false);
  const [confirmDiscardSettings, setConfirmDiscardSettings] = useState(false);
  const handleSettingsDraft = useCallback((dirty: boolean) => {
    settingsDraftRef.current = dirty;
    setHasSettingsDraft(dirty);
  }, []);
  useEffect(() => {
    if (!hasSettingsDraft) return;
    const preventLoss = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", preventLoss);
    return () => window.removeEventListener("beforeunload", preventLoss);
  }, [hasSettingsDraft]);

  const handleAppClose = useCallback(() => {
    if (settingsDraftRef.current) { setConfirmDiscardSettings(true); return; }
    setIsClosing(true);
    void startGracefulShutdown();
  }, []);

  useEffect(() => {
    let stop: (() => void) | undefined;
    void listenForAppCloseRequest(() => {
      handleAppClose();
    }).then((unlisten) => {
      stop = unlisten;
    });
    return () => stop?.();
  }, [handleAppClose]);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [readinessUnavailable, setReadinessUnavailable] = useState(false);
  const [avatarStatus, setAvatarStatus] = useState<AvatarStatusResponse | null>(null);
  const [avatarOverlay, setAvatarOverlay] = useState<AvatarOverlaySettings | null>(null);
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [setupOpen, setSetupOpen] = useState(false);
  const retrievalNotifications = useRef(new RetrievalNotifications());
  useEffect(() => {
    retrievalNotifications.current.setEnabled(settings?.web_search_notifications_enabled ?? false);
  }, [settings?.web_search_notifications_enabled]);
  useEffect(() => () => retrievalNotifications.current.disconnect(), []);
  const [qaStudioOpen, setQaStudioOpen] = useState(false);

  useEffect(() => {
    void isQaStudioWindowOpen().then((open) => {
      setQaStudioOpen(open);
    });
    let stop: (() => void) | undefined;
    void listenForQaStudioState((open) => {
      setQaStudioOpen(open);
    }).then((unlisten) => {
      stop = unlisten;
    });
    return () => stop?.();
  }, []);

  const handleToggleQaStudio = useCallback(async (open: boolean) => {
    setQaStudioOpen(open);
    try {
      if (open) {
        await openQaStudioWindow();
      } else {
        await closeQaStudioWindow();
      }
    } catch (err) {
      console.error("Failed to toggle QA Studio window:", err);
      const actualOpen = await isQaStudioWindowOpen();
      setQaStudioOpen(actualOpen);
    }
  }, []);
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

  useEffect(() => {
    if (!setupRequired) return;
    setSettingsNavigationRequest(current => ({ section: "api-keys", target: "deepseek", id: (current?.id ?? 0) + 1 }));
    setActiveView("settings");
  }, [setupRequired]);

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
    if (!desktopManaged) return;
    let stop: (() => void) | undefined;
    void listenForAvatarStatus((status) => {
      setAvatarHostStatus(status);
    }).then((unlisten) => {
      stop = unlisten;
      void getAvatarHostStatus().then((status) => {
        if (status) setAvatarHostStatus(status);
      });
    });
    return () => stop?.();
  }, [desktopManaged]);

  const isWaitingForAvatar = shouldWaitForInAppAvatar(desktopManaged, avatarHostStatus);
  const modelNoticeShown = useRef(false);
  useEffect(() => {
    if (!desktopManaged || !readiness?.models?.length) return;
    if (readiness.models.every(model => model.installed)) {
      notify.dismiss("models.readiness");
      modelNoticeShown.current = false;
    } else if (!modelNoticeShown.current && coreStatus === "ready" && !showStartup) {
      modelNoticeShown.current = true;
      notify.warning("Голос пока недоступен", "Скачайте недостающие модели в настройках, чтобы включить голос.", {
        id: "models.readiness", duration: "persistent", accent: "danger",
        actions: [{ label: "Открыть модели", onClick: () => {
          setSettingsNavigationRequest(current => ({ section: "models", id: (current?.id ?? 0) + 1 }));
          switchView("settings");
          notify.dismiss("models.readiness");
        } }],
      });
    }
  }, [desktopManaged, readiness, coreStatus, showStartup]);

  const startupStage = getStartupStage(coreStatus, readiness, isWaitingForAvatar, readinessUnavailable);
  const startupReady = coreStatus === "ready" && startupStage === 3;

  const startupSubdetail = useMemo(() => {
    if (coreStatus === "failed" || coreStatus === "crashed") return undefined;
    if (coreStatus !== "ready") {
      return "Подключаю сервисы Iris";
    }
    if (startupStage === 1) return "Подготавливаю модель диалога";
    if (startupStage === 2 && isWaitingForAvatar) {
      return avatarHostStatus?.phase === "warming"
        ? "Подготавливаю первый кадр аватара"
        : "Запускаю 3D-аватар";
    }
    if (startupStage === 2) return "Подготавливаю голосовые сервисы";
    if (readiness?.phase === "degraded") return "Iris готова · часть сервисов недоступна";
    return "Всё готово к разговору";
  }, [avatarHostStatus?.phase, coreStatus, isWaitingForAvatar, readiness?.phase, startupStage]);

  useEffect(() => {
    let stop: (() => void) | undefined;
    let disposed = false;
    let revision = 0;
    const syncRuntime = () => {
      const request = ++revision;
      void getDesktopRuntime().then(runtime => {
        if (disposed || request !== revision) return;
        setCoreError(runtime.coreError ?? null);
        setCoreStatus(runtime.coreStatus);
        if (runtime.coreStatus !== "ready") setShowStartup(true);
      }).catch(() => { /* Preserve the status delivered by the shell. */ });
    };
    void listenForCoreStatus((nextStatus) => {
      revision++;
      setCoreStatus(nextStatus);
      setRetryingCore(false);
      if (nextStatus !== "ready") setShowStartup(true);
      if (nextStatus === "starting") {
        setCoreError(null);
        setStartupRevealRequested(false);
        readinessEpoch.current += 1;
        setReadiness(null);
        setReadinessUnavailable(false);
        setStartupAttempt((value) => value + 1);
      }
      if (nextStatus === "failed" && desktopManaged) syncRuntime();
    }).then((unlisten) => {
      if (disposed) { unlisten(); return; }
      stop = unlisten;
      if (desktopManaged) {
        syncRuntime();
      }
    });
    return () => { disposed = true; revision++; stop?.(); };
  }, [desktopManaged]);

  const retryCore = async () => {
    setCoreError(null);
    setRetryingCore(true);
    setCoreStatus("starting");
    setShowStartup(true);
    setStartupRevealRequested(false);
    setAvatarHostStatus(null);
    readinessEpoch.current += 1;
    setReadiness(null);
    setReadinessUnavailable(false);
    setStartupAttempt((value) => value + 1);
    try {
      const runtime = await restartDesktopCore();
      setCoreStatus(runtime.coreStatus);
      const nextAvatarStatus = await restartAvatar();
      if (nextAvatarStatus) setAvatarHostStatus(nextAvatarStatus);
    } catch (cause) {
      setCoreError(cause instanceof Error ? cause.message : String(cause));
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
    const epoch = readinessEpoch.current;
    try {
      const next = await getReadiness();
      if (epoch !== readinessEpoch.current) return null;
      setReadinessUnavailable(false);
      setReadiness((current) => {
        if (
          current &&
          current.phase === next.phase &&
          current.live_ready === next.live_ready &&
          current.text_chat === next.text_chat &&
          current.stt === next.stt &&
          current.tts === next.tts &&
          current.vad === next.vad &&
          current.errors.length === next.errors.length
        ) {
          return current;
        }
        return next;
      });
      return next;
    } catch {
      if (epoch !== readinessEpoch.current) return null;
      // The core status indicator remains authoritative while the readiness
      // endpoint is unavailable during an older or restarting backend.
      setReadinessUnavailable(true);
      return null;
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
    const readinessTimer = window.setInterval(async () => {
      const result = await refreshReadiness();
      if (result && ![result.text_chat, result.stt, result.tts, result.vad].includes("loading")) {
        window.clearInterval(readinessTimer);
      }
    }, 1200);
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
    void configureAvatarPlacement(settings.avatar_placement)
      .then((status) => {
        if (status) setAvatarHostStatus(status);
      })
      .catch(() => {
        // Settings remain usable in a browser or when an optional avatar build
        // is unavailable. Avatar diagnostics show the connection state.
      });
  }, [servicesReady, settings?.avatar_placement]);

  const retryAvatar = useCallback(async () => {
    const status = await restartAvatar();
    if (status) setAvatarHostStatus(status);
  }, []);

  const startFreshSession = useCallback(async (
    boundaryReason: ConversationBoundaryReason = "new_dialog",
  ) => {
    setStartingSession(true);
    try {
      const session = await resetConversationSession(boundaryReason);
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

  const checkSession = useCallback(async () => {
    const session = await getConversationSession();
    // A late idle check must not replace a session started manually meanwhile.
    setSessionId(current => current === sessionId ? session.session_id : current);
  }, [sessionId]);

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
          notifyBackendEvent(event, () => { setSettingsNavigationRequest(current => ({ section: "models", id: (current?.id ?? 0) + 1 })); switchView("settings"); });
          retrievalNotifications.current.consume(event);
        } catch {
          // Ignore malformed event frames.
        }
      };

      socket.onclose = () => {
        retrievalNotifications.current.disconnect();
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

  if (isClosing) {
    return <StartupScreen key="closing" status="closing" onClose={handleAppClose} />;
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
    setVisitedViews((previous) => previous.has(view) ? previous : new Set([...previous, view]));
    setActiveView(view);
    closeNavigation();
  };
  useShortcutCommands({
    search: () => setGlobalSearchOpen(true),
    settings: () => switchView("settings"),
    chat: () => switchView("chat"),
    history: () => switchView("journal"),
    memory: () => switchView("memory"),
    plans: () => { setMemoryFocus({ id: "", section: "commitments", query: "", requestId: crypto.randomUUID() }); switchView("memory"); },
    sidebar: () => setSidebarCollapsed(current => !current),
  }, !showStartup && !setupOpen);
  return (
    <>
    {(!showStartup || (startupReady && startupRevealRequested)) && (
    <div ref={appShellRef} className={`app-shell${sidebarCollapsed ? " is-sidebar-collapsed" : ""}`}
      inert={showStartup || undefined} aria-hidden={showStartup || undefined}
      style={showStartup ? { opacity: 0 } : undefined}>
      <CorpusSurface />
      <Sidebar
        activeView={activeView}
        isOpen={navigationOpen}
        isCollapsed={sidebarCollapsed}
        onNavigate={switchView}
        onToggleCollapsed={() => setSidebarCollapsed((value) => !value)}
      />
      {navigationScrim.present && <button ref={navigationScrim.ref} className="navigation-scrim" type="button" aria-label="Закрыть меню" inert={!navigationOpen || undefined} aria-hidden={!navigationOpen || undefined} onClick={closeNavigation} />}
      <WindowChrome
        onOpenSearch={() => setGlobalSearchOpen(true)}
        title=""
        navigationOpen={navigationOpen}
        navigationButtonRef={menuToggleRef}
        onOpenNavigation={toggleNavigation}
        onClose={handleAppClose}
      />
      <section className="app-content">
        <main className={`workspace workspace-${activeView}`}>
          <WorkspaceView active={activeView === "overview"}>
            <OverviewPage
              isActive={activeView === "overview"}
              onOpenChat={() => switchView("chat")}
              onOpenHistory={(episode) => {
                if (episode) { setHistoryFocus(undefined); setHistoryEpisodeRequest({ episode, requestId: crypto.randomUUID() }); }
                switchView("journal");
              }}
              onOpenMemory={() => switchView("memory")}
              onOpenPlans={() => { setMemoryFocus({ id: "", section: "commitments", query: "", requestId: crypto.randomUUID() }); switchView("memory"); }}
              />
          </WorkspaceView>
          <div className="chat-view" hidden={activeView !== "chat"}>
            <Suspense fallback={<LoadingRing className="page-loading" />}>
              <LazyChatPage
                sessionId={sessionId}
                sessionStarting={startingSession}
                isActive={activeView === "chat"}
                backgroundConversationHost={backgroundConversationRef}
                events={events}
                settings={settings}
                readiness={readiness}
                avatarStatus={avatarStatus}
                avatarHostStatus={avatarHostStatus}
                showInAppAvatar={settings?.avatar_placement === "in_app" && (settings.avatar_in_app_visible ?? true)}
                avatarSuspended={globalSearchOpen || changelogOpen}
                onRefreshEvents={refreshEvents}
                onOpenMemory={() => switchView("memory")}
                onOpenChat={() => switchView("chat")}
                onOpenSettings={() => switchView("settings")}
                onStartNewDialog={startFreshSession}
                onCheckSession={checkSession}
                onRetryAvatar={retryAvatar}
              />
            </Suspense>
          </div>
          {visitedViews.has("journal") && (
            <WorkspaceView active={activeView === "journal"}>
              <Suspense fallback={<LoadingRing className="page-loading" />}>
                <JournalPage focusRequest={historyFocus} episodeRequest={historyEpisodeRequest} developerMode={settings?.developer_mode_enabled ?? false} currentSessionId={sessionId} onOpenChat={() => switchView("chat")} isActive={activeView === "journal"} />
              </Suspense>
            </WorkspaceView>
          )}
          {visitedViews.has("memory") && (
            <WorkspaceView active={activeView === "memory"}>
              <Suspense fallback={<LoadingRing className="page-loading" />}>
                <MemoryPage focusRequest={memoryFocus} developerMode={settings?.developer_mode_enabled ?? false} onOpenSource={id => { setHistoryFocus({ id, query: "", requestId: crypto.randomUUID() }); switchView("journal"); }} />
              </Suspense>
            </WorkspaceView>
          )}
          {visitedViews.has("state") && (
            <WorkspaceView active={activeView === "state"}>
              <Suspense fallback={<LoadingRing className="page-loading" />}>
                <StatePage events={events} />
              </Suspense>
            </WorkspaceView>
          )}
          {visitedViews.has("coding") && (
            <WorkspaceView active={activeView === "coding"}>
              <Suspense fallback={<LoadingRing className="page-loading" />}>
                <CodingAgentPage
                  settings={settings}
                  events={events}
                  sessionId={sessionId}
                  onOpenApiSettings={() => {
                    setSettingsNavigationRequest(current => ({ section: "api-keys", target: "coding", id: (current?.id ?? 0) + 1 }));
                    switchView("settings");
                  }}
                  onSettingsChanged={(nextSettings) => {
                    overviewRevision.current += 1;
                    setSettings(nextSettings);
                  }}
                />
              </Suspense>
            </WorkspaceView>
          )}
          {visitedViews.has("settings") && (
            <WorkspaceView active={activeView === "settings"}>
              <Suspense fallback={<LoadingRing className="page-loading" />}>
                <LazySettingsPage
                  settings={settings}
                  onOpenSetup={() => setSetupOpen(true)}
                  onDraftChange={handleSettingsDraft}
                  navigationRequest={settingsNavigationRequest}
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
                  qaStudioEnabled={qaStudioOpen}
                  onToggleQaStudioEnabled={handleToggleQaStudio}
                  onOpenQaStudio={() => void handleToggleQaStudio(true)}
                />
              </Suspense>
            </WorkspaceView>
          )}
        </main>
        <GlobalSearch open={globalSearchOpen} developerMode={settings?.developer_mode_enabled ?? false} onClose={() => setGlobalSearchOpen(false)} onSelect={destination => {
          if (destination.kind === "history") { setHistoryFocus(destination.focus); switchView("journal"); }
          else if (destination.kind === "memory") { setMemoryFocus(destination.focus); switchView("memory"); }
          else if (destination.section === "changelog") handleOpenChangelog();
          else { setSettingsNavigationRequest({ section: destination.section as SettingsSection, focusId: destination.focusId || `settings-${destination.section}`, id: Date.now() }); switchView("settings"); }
        }} />
        <ReminderDelivery enabled={status?.backend === "ok"} />
        <ChangelogController enabled={!showStartup && !setupOpen} open={changelogOpen} onOpen={handleOpenChangelog} onClose={() => setChangelogOpen(false)} />
        <FirstConversationSetup open={setupOpen} settings={settings} onSettingsChanged={setSettings} onClose={() => setSetupOpen(false)} onStart={() => switchView("chat")} />
        <AppDialog open={confirmDiscardSettings} title="Есть несохранённые настройки" description="Город, словарь или новый API-ключ ещё не сохранены. Можно вернуться к настройкам или закрыть Iris без сохранения черновиков." onClose={() => setConfirmDiscardSettings(false)} variant="warning">
          <MaterialButton materialKey="settings.close.keep-drafts" className="secondary" onClick={() => { setConfirmDiscardSettings(false); switchView("settings"); }}>Вернуться к настройкам</MaterialButton>
          <MaterialButton materialKey="settings.close.discard-drafts" className="danger-button" onClick={() => { settingsDraftRef.current = false; setHasSettingsDraft(false); setConfirmDiscardSettings(false); setIsClosing(true); void startGracefulShutdown(); }}>Закрыть без сохранения</MaterialButton>
        </AppDialog>
        <NotificationHost pinnedContentRef={backgroundConversationRef} onNavigate={(view) => { if (view === "changelog") handleOpenChangelog(); else if (view === "reminders") { setMemoryFocus({ id: "", section: "commitments", query: "", requestId: crypto.randomUUID() }); switchView("memory"); } else switchView(view as AppView); }} />
      </section>
    </div>
    )}
    {showStartup && (
      <StartupScreen key={startupAttempt} status={startupReady ? "ready" : coreStatus}
        stage={startupStage} subdetail={recoveryError || coreError || startupSubdetail} retrying={retryingCore || recoveryBusy}
        onRestoreBackup={desktopManaged ? () => { void (async () => {
          setRecoveryBusy(true); setRecoveryError(null);
          try { const backup = await importDesktopBackup(); if (backup) setRecoveryBackup(backup.name); }
          catch (error) { setRecoveryError(String(error)); }
          finally { setRecoveryBusy(false); }
        })(); } : undefined}
        onRetry={() => void retryCore()} onClose={handleAppClose} revealTarget={appShellRef}
        onReveal={() => setStartupRevealRequested(true)}
        onComplete={() => setShowStartup(false)} />
    )}
    <AppDialog open={recoveryBackup !== null} title="Восстановить данные?" description="Iris сохранит текущие данные перед заменой. После восстановления приложение перезапустится." onClose={() => { if (!recoveryBusy) setRecoveryBackup(null); }} variant="danger">
      {recoveryError && <p role="alert">{recoveryError}</p>}
      <MaterialButton materialKey="startup.recovery.cancel" className="secondary" disabled={recoveryBusy} onClick={() => setRecoveryBackup(null)}>Отмена</MaterialButton>
      <MaterialButton materialKey="startup.recovery.confirm" className="primary-button" disabled={recoveryBusy} onClick={() => { if (!recoveryBackup) return; void (async () => {
        setRecoveryBusy(true); setRecoveryError(null);
        try { await restoreDesktopBackup(recoveryBackup); window.location.reload(); }
        catch (error) { setRecoveryError(String(error)); }
        finally { setRecoveryBusy(false); }
      })(); }}>{recoveryBusy ? "Выполняем операцию…" : "Восстановить"}</MaterialButton>
    </AppDialog>
    </>
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
  const sidebarRef = useRef<HTMLElement>(null);
  useDrawerMotion(sidebarRef, isOpen);

  return (
    <aside id="main-sidebar" ref={sidebarRef} className={`sidebar${isOpen ? " is-open" : ""}`} aria-label="Основная навигация">
      <div className="sidebar-brand" data-tauri-drag-region>
        <span className="brand-lockup brand-lockup-wordmark">
          <img className="brand-logo brand-logo-wordmark" src="/brand/iris-wordmark-light.svg" alt="Iris" />
        </span>
        <span className="brand-lockup brand-lockup-mark" aria-hidden="true">
          <img className="brand-logo brand-logo-mark" src="/brand/iris-mark-light.svg" alt="" aria-hidden="true" />
        </span>
      </div>
      <nav className="sidebar-nav" aria-label="Разделы приложения">
        {MAIN_NAVIGATION.map(({ id, label, icon: Icon }) => (
          <NavigationButton key={id} materialKey={`navigation.${id}`} icon={Icon} label={label} active={activeView === id} compact={isCollapsed} onClick={() => onNavigate(id)} />
        ))}
      </nav>
      <div className="sidebar-footer">
        <div className="sidebar-footer-row">
          <NavigationButton materialKey="navigation.settings" icon={FigmaSettingsIcon} label="Настройки" active={activeView === "settings"} compact={isCollapsed} iconSize={20} onClick={() => onNavigate("settings")} />
          <MaterialButton materialKey={"App.button-2"}
            appearance="quiet"
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
          </MaterialButton>
        </div>
      </div>
    </aside>
  );
}

function NavigationButton({
  materialKey,
  icon: Icon,
  label,
  active,
  compact = false,
  iconSize = 21,
  onClick,
}: {
  materialKey: string;
  icon: any;
  label: string;
  active: boolean;
  compact?: boolean;
  iconSize?: number;
  onClick: () => void;
}) {
  return (
    <MaterialButton materialKey={materialKey}
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
    </MaterialButton>
  );
}

export function ChatPage({
  sessionId,
  sessionStarting,
  isActive,
  backgroundConversationHost,
  events,
  settings,
  readiness,
  avatarStatus,
  avatarHostStatus,
  showInAppAvatar,
  avatarSuspended = false,
  onRefreshEvents,
  onOpenMemory,
  onOpenChat,
  onOpenSettings,
  onStartNewDialog,
  onCheckSession,
  onRetryAvatar,
}: {
  sessionId: string | null;
  sessionStarting: boolean;
  isActive: boolean;
  backgroundConversationHost?: React.RefObject<HTMLDivElement | null>;
  events: BackendEvent[];
  settings: PublicSettings | null;
  readiness: ReadinessResponse | null;
  avatarStatus: AvatarStatusResponse | null;
  avatarHostStatus: AvatarHostStatus | null;
  showInAppAvatar: boolean;
  avatarSuspended?: boolean;
  onRefreshEvents: () => Promise<void>;
  onOpenMemory: () => void;
  onOpenChat?: () => void;
  onOpenSettings?: () => void;
  onStartNewDialog: (boundaryReason?: ConversationBoundaryReason) => Promise<void>;
  onCheckSession?: () => Promise<void>;
  onRetryAvatar: () => Promise<void>;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [documentBusy, setDocumentBusy] = useState(false);
  const [liveSttTranscript, setLiveSttTranscript] = useState("");
  const composerTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [composerExtraHeight, setComposerExtraHeight] = useState(0);
  const [manualComposerExtraHeight, setManualComposerExtraHeight] = useState<number | null>(null);
  const [isResizingComposer, setIsResizingComposer] = useState(false);
  const composerResizeStartYRef = useRef<number>(0);
  const composerResizeStartHeightRef = useRef<number>(0);
  const [loading, setLoading] = useState(false);
  const [isStarted, setIsStarted] = useState(false);
  const [soundMuted, setSoundMuted] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [retryText, setRetryText] = useState<string | null>(null);
  const [memoryNotice, setMemoryNotice] = useState<string | null>(null);
  const [liveConversation, setLiveConversation] = useState(false);
  const [microphoneMuted, setMicrophoneMuted] = useState(false);
  const [microphoneStarting, setMicrophoneStarting] = useState(false);
  const [activeAudioElement, setActiveAudioElement] = useState<HTMLAudioElement | null>(null);
  const [livePlaybackSegment, setLivePlaybackSegment] = useState("");
  const [livePlaybackDurationSeconds, setLivePlaybackDurationSeconds] = useState(0);
  const [livePlaybackRevision, setLivePlaybackRevision] = useState(0);
  const [conversationStatus, setConversationStatus] = useState("Микрофон включён");
  const [conversationDebug, setConversationDebug] = useState<ConversationDebug | null>(null);
  const [newDialogConfirmationOpen, setNewDialogConfirmationOpen] = useState(false);
  const [newDialogPending, setNewDialogPending] = useState(false);
  const listRef = useRef<HTMLDivElement | null>(null);
  const chatPanelRef = useRef<HTMLElement | null>(null);
  const dockScale = useDockScale(chatPanelRef);
  const handledVoiceEventIdsRef = useRef<Set<string>>(new Set());
  const activeAudioRef = useRef<HTMLAudioElement | null>(null);
  const liveSocketRef = useRef<VoiceSocketClient | null>(null);
  const liveSocketSessionIdRef = useRef<string | null>(null);
  const livePlayerRef = useRef<TTSStreamPlayer | null>(null);
  const vadRecorderRef = useRef<BrowserVadRecorder | null>(null);
  const pcmInputRef = useRef<PcmInputClient | null>(null);
  const liveConnectingRef = useRef(false);
  const playbackCoordinatorRef = useRef(new PlaybackCoordinator());
  const avatarOwnsAudioRef = useRef(false);
  const liveAudioStartedRef = useRef(false);
  const liveMetadataRef = useRef({ emotion: "neutral", intent: "unknown" });
  const [liveVoiceEmotion, setLiveVoiceEmotion] = useState<string | null>(null);
  const [persistentEmotion, setPersistentEmotion] = useState<string>("neutral");

  const refreshCharacterState = useCallback(async () => {
    try {
      const state = await getCharacterState();
      if (state?.mood?.primary_emotion) {
        setPersistentEmotion(state.mood.primary_emotion);
      }
    } catch {
      // The state service may be unavailable during startup
    }
  }, []);

  useEffect(() => {
    void refreshCharacterState();
  }, [refreshCharacterState, sessionId]);

  useEffect(() => {
    const latest = events[events.length - 1]?.type ?? "";
    if (latest.startsWith("character.state.") || latest.startsWith("character.state_reset") || latest.startsWith("character.reflection.")) {
      void refreshCharacterState();
    }
  }, [events, refreshCharacterState]);
  const pendingSpeakerLabelRef = useRef("Вы");
  const latestPlaybackSegmentRef = useRef("");
  const playbackSegmentTextsRef = useRef<string[]>([]);
  const playbackSegmentDurationsRef = useRef<number[]>([]);
  const avatarSubtitleTimerRef = useRef<number | null>(null);
  const avatarSubtitleSequenceRef = useRef(0);
  const avatarSubtitleUsesBoundariesRef = useRef(false);
  const activeVoiceGenerationRef = useRef<number | undefined>(undefined);
  const conversationStatusTimerRef = useRef<number | null>(null);
  const bargeInTimerRef = useRef<number | null>(null);
  const sttClearTimerRef = useRef<number | null>(null);
  const pendingTextDeltasRef = useRef(new Map<string, string>());
  const pendingTextDeltaTimerRef = useRef<number | null>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  const submissionRef = useRef<{ id: string; text: string; sessionId: string } | null>(null);
  const chatRevisionRef = useRef(0);
  const currentSessionRef = useRef(sessionId);
  currentSessionRef.current = sessionId;
  const replyRecoveryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestStartedUtteranceRef = useRef<string | null>(null);
  const outputDisconnectRevisionRef = useRef(0);
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

  const clearAvatarSubtitleTimer = useCallback(() => {
    if (avatarSubtitleTimerRef.current !== null) {
      window.clearTimeout(avatarSubtitleTimerRef.current);
      avatarSubtitleTimerRef.current = null;
    }
  }, []);

  const startAvatarSubtitleFallback = useCallback(() => {
    clearAvatarSubtitleTimer();
    avatarSubtitleUsesBoundariesRef.current = false;
    avatarSubtitleSequenceRef.current = 0;

    const advance = () => {
      if (avatarSubtitleUsesBoundariesRef.current) return;
      const sequence = avatarSubtitleSequenceRef.current;
      const text = playbackSegmentTextsRef.current[sequence];
      const durationSeconds = playbackSegmentDurationsRef.current[sequence];
      if (!text || !durationSeconds) {
        avatarSubtitleTimerRef.current = window.setTimeout(advance, 50);
        return;
      }
      setLivePlaybackSegment(text);
      setLivePlaybackDurationSeconds(durationSeconds);
      setLivePlaybackRevision((revision) => revision + 1);
      avatarSubtitleTimerRef.current = window.setTimeout(() => {
        avatarSubtitleSequenceRef.current = sequence + 1;
        advance();
      }, Math.max(120, durationSeconds * 1000));
    };

    advance();
  }, [clearAvatarSubtitleTimer]);

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

  const adjustComposerHeight = useCallback(() => {
    const textarea = composerTextareaRef.current;
    if (!textarea) return;

    textarea.style.height = "auto";
    const scrollHeight = textarea.scrollHeight;

    const autoHeight = Math.min(Math.max(scrollHeight, 24), 144);
    const textExtra = Math.max(0, autoHeight - 24);

    const targetExtra = manualComposerExtraHeight !== null
      ? Math.max(manualComposerExtraHeight, textExtra)
      : textExtra;

    const targetTextareaHeight = 24 + targetExtra;
    textarea.style.height = `${targetTextareaHeight}px`;

    if (scrollHeight > targetTextareaHeight) {
      textarea.classList.add("has-scroll");
    } else {
      textarea.classList.remove("has-scroll");
    }

    setComposerExtraHeight(targetExtra);
  }, [manualComposerExtraHeight]);

  useLayoutEffect(() => {
    adjustComposerHeight();
  }, [draft, liveSttTranscript, adjustComposerHeight]);

  const onComposerResizeStart = (e: React.PointerEvent) => {
    e.preventDefault();
    setIsResizingComposer(true);
    composerResizeStartYRef.current = e.clientY;
    composerResizeStartHeightRef.current = composerExtraHeight;

    const onPointerMove = (moveEvent: PointerEvent) => {
      const scale = Number(dockScale) || 1;
      const deltaY = (composerResizeStartYRef.current - moveEvent.clientY) / scale;
      const newExtra = Math.max(0, Math.min(composerResizeStartHeightRef.current + deltaY, 200));
      setManualComposerExtraHeight(newExtra);
    };

    const onPointerUp = () => {
      setIsResizingComposer(false);
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerUp);
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
  };

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

    notify.error("Диалог", error, {
      actions: retryText
        ? [
            {
              label: "Повторить",
              onClick: () => {
                setDraft(retryText);
                setRetryText(null);
              },
              variant: "primary",
            },
          ]
        : undefined,
    });

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
    notify.info("Память", `Сохранено в памяти: ${update.predicate}.`, {
      navigateView: "memory",
      actions: [
        {
          label: "Открыть память",
          onClick: onOpenMemory,
          variant: "primary",
        },
      ],
    });
  }, [onOpenMemory]);

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

  const refreshTimelineMessages = useCallback((targetSessionId?: string) => {
    const revision = chatRevisionRef.current;
    const activeUtterance = liveSocketRef.current?.activeUtteranceId;
    const knownMessageIds = new Set(messagesRef.current.map(message => message.id));
    return (targetSessionId ? getTimelineMessages(50, targetSessionId) : getTimelineMessages(50)).then((payload) => {
      if (revision !== chatRevisionRef.current || activeUtterance !== liveSocketRef.current?.activeUtteranceId || (targetSessionId && targetSessionId !== currentSessionRef.current)) return;
      const restored = payload.items
        .filter((message) => message.role === "user" || message.role === "assistant")
        .map((message) => ({ id: message.id, role: message.role as "user" | "assistant", content: message.content,
          clientMessageId: message.client_message_id ?? undefined, utteranceId: message.utterance_id ?? undefined }));
      setMessages(current => [...restored, ...current.filter(message =>
        (!knownMessageIds.has(message.id)
          || (submissionRef.current !== null && message.role === "user" && message.clientMessageId === submissionRef.current.id))
        && !restored.some(item => item.id === message.id
          || (message.clientMessageId && item.clientMessageId === message.clientMessageId)))]);
      if (payload.items.length > 0) {
        setIsStarted(true);
      }
    }).catch(() => {
      // The V0.4 compatibility backend may intentionally keep Timeline V2 disabled.
    });
  }, []);

  const restoredSessionRef = useRef(sessionId);
  useEffect(() => {
    const previousSession = restoredSessionRef.current;
    restoredSessionRef.current = sessionId;
    if (previousSession && previousSession !== sessionId) {
      chatRevisionRef.current++;
      submissionRef.current = null;
      pendingTextDeltasRef.current.clear();
      liveSocketRef.current?.close();
      liveSocketRef.current = null;
      liveSocketSessionIdRef.current = null;
      livePlayerRef.current?.stop();
      setMessages([]);
      setIsStarted(false);
      setLoading(false);
      setVoiceState("idle");
      setRetryText(null);
      setError(null);
    }
    if (sessionId) void refreshTimelineMessages(sessionId);
  }, [refreshTimelineMessages, sessionId]);

  const canCheckSessionRef = useRef(false);
  canCheckSessionRef.current = !loading && !liveConversation && !microphoneStarting
    && !sessionStarting && !newDialogPending && voiceState === "idle";
  const dialogHasMessagesRef = useRef(false);
  dialogHasMessagesRef.current = messages.length > 0 || isStarted;

  useEffect(() => {
    if (!isActive || !sessionId || !onCheckSession) return;
    let pending = false;
    const check = () => {
      if (pending || !canCheckSessionRef.current || document.visibilityState === "hidden") return;
      pending = true;
      void onCheckSession().catch(() => {
        // Keep the saved conversation visible until the core is reachable.
      }).finally(() => { pending = false; });
    };
    // Covers returning from another section, restoring a window, and sleep.
    if (dialogHasMessagesRef.current) check();
    const timer = window.setInterval(check, 60_000);
    window.addEventListener("focus", check);
    document.addEventListener("visibilitychange", check);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", check);
      document.removeEventListener("visibilitychange", check);
    };
  }, [isActive, sessionId, onCheckSession]);

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
        (startedUtteranceId) => {
          clearLiveSttTranscript();
          liveAudioStartedRef.current = true;
          liveSocketRef.current?.send("playback.started", {
            utterance_id: startedUtteranceId || liveSocketRef.current?.activeUtteranceId,
          });
          setVoiceState("speaking");
        },
        (finishedUtteranceId) => {
          clearLiveSttTranscript();
          setLivePlaybackSegment("");
          const resolvedUtteranceId = finishedUtteranceId || liveSocketRef.current?.activeUtteranceId;
          liveSocketRef.current?.send("playback.finished", {
            utterance_id: resolvedUtteranceId,
          });
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
        (text, durationSeconds) => {
          setLivePlaybackSegment(text);
          setLivePlaybackDurationSeconds(durationSeconds);
          setLivePlaybackRevision((revision) => revision + 1);
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
          latestStartedUtteranceRef.current = event.utterance_id;
          clearLiveSttTranscript();
          clearAvatarSubtitleTimer();
          playbackSegmentTextsRef.current = [];
          playbackSegmentDurationsRef.current = [];
          avatarSubtitleUsesBoundariesRef.current = false;
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
          const nextEmotion = event.emotion ?? "neutral";
          liveMetadataRef.current = {
            emotion: nextEmotion,
            intent: event.intent ?? "unknown",
          };
          setLiveVoiceEmotion(nextEmotion);
          if (nextEmotion && nextEmotion !== "neutral") {
            setPersistentEmotion(nextEmotion);
          }
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
          if (event.text && event.segment_id !== undefined) {
            playbackSegmentTextsRef.current[event.segment_id] = event.text;
          }
          liveSocketRef.current?.send("playback.segment.started", {
            text: event.text ?? "",
            generation: event.generation,
          });
        } else if (event.type === "tts.segment.finished") {
          if (event.segment_id !== undefined && event.duration_seconds !== undefined) {
            playbackSegmentDurationsRef.current[event.segment_id] = event.duration_seconds;
          }
        } else if (event.type === "avatar.playback.started") {
          clearLiveSttTranscript();
          setVoiceState("speaking");
          startAvatarSubtitleFallback();
        } else if (event.type === "avatar.playback.segment.started") {
          clearLiveSttTranscript();
          avatarSubtitleUsesBoundariesRef.current = true;
          clearAvatarSubtitleTimer();
          setLivePlaybackSegment(event.text ?? "");
          setLivePlaybackDurationSeconds(
            event.segment_id === undefined
              ? 0
              : (playbackSegmentDurationsRef.current[event.segment_id] ?? 0),
          );
          setLivePlaybackRevision((revision) => revision + 1);
          setVoiceState("speaking");
        } else if (event.type === "voice.utterance.finished") {
          clearLiveSttTranscript();
          if (!avatarOwnsAudioRef.current) {
            livePlayerRef.current?.finish(event.utterance_id);
          }
        } else if (event.type === "avatar.playback.finished") {
          clearLiveSttTranscript();
          clearAvatarSubtitleTimer();
          setLivePlaybackSegment("");
          playbackSegmentTextsRef.current = [];
          playbackCoordinatorRef.current.release(playbackCoordinatorRef.current.snapshot());
          liveSocketRef.current?.clearActive();
          setLoading(false);
          setVoiceState("idle");
        } else if (event.type === "avatar.playback.failed") {
          clearLiveSttTranscript();
          clearAvatarSubtitleTimer();
          setLivePlaybackSegment("");
          playbackSegmentTextsRef.current = [];
          playbackCoordinatorRef.current.cancel();
          liveSocketRef.current?.clearActive();
          setError(event.message ?? "Не удалось воспроизвести голос Ирис");
          setLoading(false);
          setVoiceState("error");
        } else if (event.type === "voice.utterance.cancelled") {
          clearLiveSttTranscript();
          clearAvatarSubtitleTimer();
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
        (state) => {
          if (currentSessionRef.current !== sessionId) return;
          if (state === "disconnected") {
            outputDisconnectRevisionRef.current++;
            flushPendingTextDeltas();
            clearAvatarSubtitleTimer();
            setLivePlaybackSegment("");
            livePlayerRef.current?.stop();
            stopVoicePlayback();
            playbackCoordinatorRef.current.cancel();
            setLoading(false);
            setVoiceState("idle");
            setError("Соединение прервано. Восстанавливаем связь с Ирис.");
          } else {
            void refreshTimelineMessages(sessionId);
          }
        },
      );
      liveSocketSessionIdRef.current = sessionId;
    }
    await player.unlock();
    await liveSocketRef.current.connect();
  }, [clearAvatarSubtitleTimer, clearLiveSttTranscript, ensureLivePlayer, flushPendingTextDeltas, queueTextDelta, refreshTimelineMessages, sessionId, showMemoryUpdates, speakTextInBrowser, startAvatarSubtitleFallback, stopVoicePlayback]);

  useEffect(() => () => {
    chatRevisionRef.current++;
    if (replyRecoveryTimerRef.current !== null) clearTimeout(replyRecoveryTimerRef.current);
    livePlayerRef.current?.stop();
    liveSocketRef.current?.close();
    liveSocketRef.current = null;
    liveSocketSessionIdRef.current = null;
    vadRecorderRef.current?.stop();
    pcmInputRef.current?.close();
    if (pendingTextDeltaTimerRef.current !== null) {
      window.clearTimeout(pendingTextDeltaTimerRef.current);
    }
    clearAvatarSubtitleTimer();
  }, [clearAvatarSubtitleTimer]);

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
    if (!text || !sessionId || loading || documentBusy) {
      return;
    }
    flushPendingTextDeltas();
    if (replyRecoveryTimerRef.current !== null) clearTimeout(replyRecoveryTimerRef.current);
    stopVoicePlayback();
    livePlayerRef.current?.stop();

    const previousSubmission = submissionRef.current;
    const clientId = previousSubmission?.sessionId === sessionId && previousSubmission.text === text
      ? previousSubmission.id : crypto.randomUUID();
    submissionRef.current = { id: clientId, text, sessionId };
    const revision = ++chatRevisionRef.current;
    const userMessage: ChatMessage = {
      id: clientId,
      clientMessageId: clientId,
      role: "user",
      content: text,
    };
    setMessages((current) => current.some(message => message.clientMessageId === clientId || message.id === clientId) ? current : [...current, userMessage]);
    setDraft("");
    setManualComposerExtraHeight(null);
    setComposerExtraHeight(0);
    if (composerTextareaRef.current) {
      composerTextareaRef.current.style.height = "24px";
      composerTextareaRef.current.classList.remove("has-scroll");
    }
    setLoading(true);
    setError(null);
    setRetryText(null);

    try {
      try {
        await ensureLiveVoice();
        liveSocketRef.current?.clearActive();
        liveAudioStartedRef.current = false;
        const disconnectRevision = outputDisconnectRevisionRef.current;
        const response = await sendLiveTextMessage(sessionId, text, clientId);
        if (revision !== chatRevisionRef.current || currentSessionRef.current !== sessionId) return;
        submissionRef.current = null;
        if (response.message_id) {
          setMessages((current) => current.map((message) =>
            message.clientMessageId === clientId ? { ...message, id: response.message_id! } : message,
          ));
        }
        if (disconnectRevision !== outputDisconnectRevisionRef.current) {
          void refreshTimelineMessages(sessionId);
          return;
        }
        if (response.replayed && response.reply) {
          setMessages(current => [...current.filter(message => message.id !== response.assistant_message_id && message.utteranceId !== response.utterance_id), {
            id: response.assistant_message_id ?? response.utterance_id, role: "assistant", content: response.reply!, utteranceId: response.utterance_id,
          }]);
        }
        if (response.status && response.status !== "streaming") {
          liveSocketRef.current?.clearActive();
          if (response.status !== "completed") setError("Предыдущий ответ был прерван. Его сохранённая часть восстановлена.");
          return;
        }
        const activeUtterance = liveSocketRef.current?.activeUtteranceId;
        if ((latestStartedUtteranceRef.current === response.utterance_id && activeUtterance !== response.utterance_id)
          || (activeUtterance && activeUtterance !== response.utterance_id)) return;
        liveSocketRef.current?.activate(response.utterance_id);
        if (response.replayed && response.assistant_message_id) {
          let attempts = 0;
          const check = async () => {
            if (revision !== chatRevisionRef.current || currentSessionRef.current !== sessionId || liveSocketRef.current?.activeUtteranceId !== response.utterance_id) return;
            try {
              const snapshot = await getTimelineMessages(50, sessionId);
              if (revision !== chatRevisionRef.current || currentSessionRef.current !== sessionId || liveSocketRef.current?.activeUtteranceId !== response.utterance_id) return;
              const saved = snapshot.items.find(item => item.id === response.assistant_message_id);
              if (saved && saved.status !== "streaming") {
                flushPendingTextDeltas();
                setMessages(current => [...current.filter(item => item.id !== saved.id && item.utteranceId !== response.utterance_id), {
                  id: saved.id, role: "assistant", content: saved.content, utteranceId: response.utterance_id,
                }]);
                liveSocketRef.current?.clearActive();
                setLoading(false);
                setVoiceState("idle");
                return;
              }
            } catch { /* A later read can recover a transient failure. */ }
            if (revision !== chatRevisionRef.current || currentSessionRef.current !== sessionId || liveSocketRef.current?.activeUtteranceId !== response.utterance_id) return;
            if (++attempts < 180) replyRecoveryTimerRef.current = setTimeout(() => void check(), 1000);
            else {
              liveSocketRef.current?.clearActive();
              setLoading(false);
              setVoiceState("idle");
              setError("Не удалось восстановить ответ. Проверьте историю диалога.");
            }
          };
          void check();
        }
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
      const response = await sendChatMessage(sessionId, text, clientId);
      if (revision !== chatRevisionRef.current || currentSessionRef.current !== sessionId) return;
      submissionRef.current = null;
      showMemoryUpdates(response.memory_updates);
      if (response.emotion && response.emotion !== "neutral") {
        setPersistentEmotion(response.emotion);
      }
      setMessages((current) => [
        ...current.filter(message => message.id !== response.assistant_message_id).map((message) => message.clientMessageId === clientId && response.message_id
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
      if (response.status && response.status !== "completed") setError("Предыдущий ответ был прерван. Его сохранённая часть восстановлена.");
      if (response.voice_request_id && response.tts_status === "queued") {
        void pollVoiceTtsStatus(response.voice_request_id);
      }
      await onRefreshEvents();
    } catch (requestError) {
      if (revision !== chatRevisionRef.current || currentSessionRef.current !== sessionId) return;
      setError(requestError instanceof Error ? requestError.message : "Не удалось отправить сообщение");
      setRetryText(text);
      // A transport failure is ambiguous: the server may already have
      // accepted the client id.  Keep the optimistic user bubble so retry
      // cannot silently erase a durable turn.
    } finally {
      if (revision === chatRevisionRef.current && currentSessionRef.current === sessionId && !liveSocketRef.current?.activeUtteranceId) {
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
    if (!sessionId || liveConnectingRef.current || microphoneStarting) return;
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
    if (!liveVoiceSupported) {
      notify.error("Микрофон недоступен", "Браузер не поддерживает необходимый аудиорежим.");
      return;
    }
    const startupNotificationId = `voice-microphone-startup-${crypto.randomUUID()}`;
    liveConnectingRef.current = true;
    setMicrophoneStarting(true);
    cancelPendingBargeIn();
    vadRecorderRef.current?.stop();
    pcmInputRef.current?.close();
    pcmInputRef.current = null;
    vadRecorderRef.current = null;
    setMicrophoneMuted(false);
    setLiveConversation(false);
    try {
      let nextReadiness = readiness;
      const readinessDeadline = Date.now() + 90_000;
      while (!nextReadiness?.live_ready) {
        const voiceUnavailable = nextReadiness?.stt === "failed"
          || nextReadiness?.stt === "disabled"
          || nextReadiness?.tts === "failed"
          || nextReadiness?.tts === "disabled";
        if (voiceUnavailable) {
          throw new Error(nextReadiness?.errors[0] ?? "Голосовые сервисы не запустились");
        }
        if (Date.now() >= readinessDeadline) {
          throw new Error("Голосовые сервисы загружаются слишком долго. Попробуйте ещё раз.");
        }
        const progress = voiceReadinessProgress(nextReadiness);
        notify.info(
          "Подготавливаю микрофон",
          `Загружаю голосовые сервисы · ${Math.round(progress * 100)}%`,
          { id: startupNotificationId, duration: "persistent", progress },
        );
        await new Promise((resolve) => window.setTimeout(resolve, 650));
        nextReadiness = await getReadiness().catch(() => nextReadiness);
      }
      notify.info(
        "Подготавливаю микрофон",
        "Запрашиваю доступ к устройству · 78%",
        { id: startupNotificationId, duration: "persistent", progress: 0.78 },
      );
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
      notify.info(
        "Подготавливаю микрофон",
        "Подключаю поток распознавания · 92%",
        { id: startupNotificationId, duration: "persistent", progress: 0.92 },
      );
      await input.connect(
        capture.sampleRate,
        settings?.voice_language ?? "ru",
        capture,
      );
      setLiveConversation(true);
      setMicrophoneMuted(false);
      updateConversationStatus("Микрофон включён");
      notify.info(
        "Подготавливаю микрофон",
        "Голосовые сервисы загружены, поток подключён · 100%",
        { id: startupNotificationId, duration: 3000, progress: 1 },
      );
      notify.success(
        "Микрофон готов",
        "Можно говорить — повторное нажатие не требуется.",
        { duration: 4500 },
      );
    } catch (vadError) {
      cancelPendingBargeIn();
      vadRecorderRef.current?.stop();
      pcmInputRef.current?.close();
      vadRecorderRef.current = null;
      pcmInputRef.current = null;
      setMicrophoneMuted(false);
      const rawMsg = vadError instanceof Error ? vadError.message : "";
      let userMsg = "Live-режим недоступен";
      if (rawMsg.includes("WebSocket") || rawMsg.includes("closed before")) {
        userMsg = "Не удалось подключиться к аудиосерверу диалога. Попробуйте ещё раз.";
      } else if (/worklet/i.test(rawMsg)) {
        userMsg = "Не удалось запустить обработку звука. Перезапустите Iris и попробуйте ещё раз.";
      } else if (rawMsg.includes("AudioWorklet") || rawMsg.includes("getUserMedia") || rawMsg.includes("Permission") || rawMsg.includes("NotAllowed")) {
        userMsg = "Микрофон недоступен или заблокирован в браузере.";
      } else if (rawMsg) {
        userMsg = rawMsg;
      }
      setError(null);
      notify.error(
        "Не удалось включить микрофон",
        userMsg,
        { id: startupNotificationId, duration: "persistent" },
      );
      setLiveConversation(false);
    } finally {
      liveConnectingRef.current = false;
      setMicrophoneStarting(false);
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

  const shortcutBindings = useShortcutBindings();
  useShortcutCommands({
    microphone: () => { if (!liveConversation || !vadRecorderRef.current) return false; toggleMicrophoneMute(); },
    sound: () => { if (!sessionId) return false; toggleSoundMute(); },
    stopSpeech: () => { if (voiceState !== "speaking") return false; interruptAssistantSpeech(); setVoiceState("idle"); },
    composer: () => { if (!isActive || !composerTextareaRef.current) return false; composerTextareaRef.current.focus(); },
  });

  const isDialogActive = isStarted || messages.length > 0 || liveConversation;
  useAvatarPresentation(!isDialogActive, showInAppAvatar && isActive, avatarHostStatus?.phase);

  const handleStart = async (event?: React.MouseEvent<HTMLElement>) => {
    if (event) animateButtonPress(event.currentTarget);
    clearLiveSttTranscript();
    setIsStarted(true);
    if (liveReady && liveVoiceSupported && !liveConversation) {
      await toggleLive();
    }
  };

  const handleFinish = async () => {
    chatRevisionRef.current++;
    submissionRef.current = null;
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
    if (currentEmotion && currentEmotion !== "neutral") {
      setPersistentEmotion(currentEmotion);
    }
    try {
      await onStartNewDialog("manual_reset");
      setMessages([]);
      setIsStarted(false);
      void refreshCharacterState();
    } catch (finishError) {
      setError(finishError instanceof Error ? finishError.message : "Не удалось завершить диалог.");
    }
  };

  const startNewDialog = async () => {
    if (!sessionId || newDialogPending) return;
    chatRevisionRef.current++;
    submissionRef.current = null;
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
      if (currentEmotion && currentEmotion !== "neutral") {
        setPersistentEmotion(currentEmotion);
      }
      await onStartNewDialog("new_dialog");
      setMessages([]);
      setIsStarted(false);
      setNewDialogConfirmationOpen(false);
      void refreshCharacterState();
    } catch (newDialogError) {
      setError(newDialogError instanceof Error ? newDialogError.message : "Не удалось начать новый диалог.");
    } finally {
      setNewDialogPending(false);
    }
  };

  const currentEmotion = useMemo(() => {
    if (liveVoiceEmotion && liveVoiceEmotion !== "neutral") {
      return liveVoiceEmotion;
    }
    if (liveMetadataRef.current.emotion && liveMetadataRef.current.emotion !== "neutral") {
      return liveMetadataRef.current.emotion;
    }
    const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
    if (lastAssistant?.emotion && lastAssistant.emotion !== "neutral") {
      return lastAssistant.emotion;
    }
    if (avatarStatus?.emotion_engine?.current_emotion && avatarStatus.emotion_engine.current_emotion !== "neutral") {
      return avatarStatus.emotion_engine.current_emotion;
    }
    if (persistentEmotion && persistentEmotion !== "neutral") {
      return persistentEmotion;
    }
    if (lastAssistant?.emotion) {
      return lastAssistant.emotion;
    }
    if (avatarStatus?.emotion_engine?.current_emotion) {
      return avatarStatus.emotion_engine.current_emotion;
    }
    return persistentEmotion || "neutral";
  }, [avatarStatus?.emotion_engine?.current_emotion, liveVoiceEmotion, messages, persistentEmotion]);

  let lastAssistantIndex = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "assistant") {
      lastAssistantIndex = i;
      break;
    }
  }

  if (!isDialogActive) {
    return (
      <section
        ref={chatPanelRef}
        className={`panel chat-panel is-idle${showInAppAvatar && isActive ? " has-in-app-avatar" : ""}`}
        style={{ "--dock-scale": dockScale } as React.CSSProperties}
      >
        <IrisPortalBackground
          key="iris-portal-bg"
          emotion={currentEmotion}
          voiceState={voiceState}
          loading={loading}
          isDialogActive={false}
          showInAppAvatar={showInAppAvatar && isActive}
          isActive={isActive}
        />
        <div className="chat-idle-stage">
          <ChatWelcomeScenery active={isActive} />
          {showInAppAvatar && isActive && (
            <InAppAvatarHost status={avatarHostStatus} onRetry={onRetryAvatar} suspended={avatarSuspended} />
          )}
          <div className="chat-start-banner">
            <div className="chat-start-banner-inner">
              <MaterialButton materialKey={"App.button-4"}
                className="chat-start-button"
                type="button"
                onClick={handleStart}
                title="Начать"
                aria-label="Начать"
              >
                <span className="btn-content">
                  <IrisPetalsIcon size={28} />
                  <span>Начать</span>
                </span>
              </MaterialButton>
              <p className="chat-start-caption">Голосом или текстом</p>
            </div>
          </div>
        </div>
        <AppDialog
          open={newDialogConfirmationOpen}
          title="Начать новый диалог?"
          icon={<MessageSquarePlus size={24} aria-hidden="true" />}
          description="Текущий диалог будет завершён и сохранён в истории. Начнётся новый разговор с Iris."
          onClose={() => !newDialogPending && setNewDialogConfirmationOpen(false)}
          variant="danger"
        >
          <div className="dialog-actions">
            <MaterialButton materialKey={"App.button-5"} className="secondary" type="button" disabled={newDialogPending} onClick={() => setNewDialogConfirmationOpen(false)}>
              Отмена
            </MaterialButton>
            <MaterialButton materialKey={"App.button-6"}
              className="danger-button"
              type="button"
              disabled={newDialogPending}
              onClick={() => void startNewDialog()}
              aria-label="Начать новый диалог"
              title="Начать новый диалог"
            >
              {newDialogPending ? "Создаю…" : "Новый диалог"}
            </MaterialButton>
          </div>
        </AppDialog>
      </section>
    );
  }

  return (
    <section
      ref={chatPanelRef}
      className={`panel chat-panel is-active${showInAppAvatar && isActive ? " has-in-app-avatar" : ""}`}
      style={{ "--dock-scale": dockScale } as React.CSSProperties}
    >
      <IrisPortalBackground
        key="iris-portal-bg"
        emotion={currentEmotion}
        voiceState={voiceState}
        loading={loading}
        isDialogActive={true}
        showInAppAvatar={showInAppAvatar && isActive}
        isActive={isActive}
      />
      {showInAppAvatar && isActive && (
        <InAppAvatarHost status={avatarHostStatus} onRetry={onRetryAvatar} suspended={avatarSuspended} />
      )}
      <div className="chat-content">
        {memoryNotice && (
          <div className="notice" role="status">
            {memoryNotice}
            <MaterialButton materialKey={"App.button-7"} className="text-button" onClick={onOpenMemory}>Открыть память</MaterialButton>
          </div>
        )}
        <ConversationSurface
          active={isActive}
          backgroundVisible={(settings?.background_conversation_notifications_enabled ?? true) && (isStarted || liveConversation || microphoneStarting || loading || voiceState !== "idle")}
          backgroundHost={backgroundConversationHost}
        >
          {(inBackground, minimized, toggleMinimized) => <>
          {inBackground && minimized && <BackgroundConversationExpandButton onExpand={toggleMinimized} />}
          <div className="background-conversation-body" hidden={inBackground && minimized}>
          {inBackground && (
            <BackgroundConversationControls
              microphoneActive={liveConversation && !microphoneMuted}
              microphoneStarting={microphoneStarting}
              microphoneDisabled={!liveVoiceSupported || microphoneStarting || !sessionId || voiceState === "stopping"}
              soundMuted={soundMuted}
              onMicrophone={() => { liveConversation ? toggleMicrophoneMute() : void toggleLive(); }}
              onSound={toggleSoundMute}
              onMinimize={toggleMinimized}
            />
          )}
          <IrisSubtitles
            messages={messages}
            loading={loading}
            voiceState={voiceState}
            activeAudio={activeAudioElement}
            livePlaybackSegment={livePlaybackSegment}
            livePlaybackDurationSeconds={livePlaybackDurationSeconds}
            livePlaybackRevision={livePlaybackRevision}
            containerRef={listRef}
            onOpenMemory={onOpenMemory}
            compact={inBackground}
          />
          </div>
          </>}
        </ConversationSurface>

        <div
          className="chat-composer-container"
          style={{ "--composer-extra-height": `${composerExtraHeight}px` } as React.CSSProperties}
        >
          {settings?.memory_incognito && <span className="chat-memory-mode" title="Новые реплики и факты не сохраняются. Прежняя история и память остаются. Запросы по-прежнему отправляются выбранной модели.">Инкогнито</span>}
          <form className="chat-form" onSubmit={onSubmit}>
            <div className={`chat-composer ${isResizingComposer ? "is-resizing" : ""}`}>
              <div
                className="chat-composer-resizer"
                onPointerDown={onComposerResizeStart}
                onDoubleClick={() => setManualComposerExtraHeight(null)}
                title="Потяните вверх для изменения размера (двойной клик для сброса)"
                aria-hidden="true"
              />
              <FigmaInputPlateFullBg
                className="chat-composer-bg"
                preserveAspectRatio="none"
                extraHeight={composerExtraHeight}
              />
              <div className="chat-composer-inner">
                <DocumentAttachment sessionId={sessionId} disabled={loading || voiceState === "thinking" || sessionStarting} onBusyChange={setDocumentBusy} />
                <textarea
                  ref={composerTextareaRef}
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
                <MaterialButton materialKey={"App.button-8"}
                  className="send-button"
                  type="submit"
                  disabled={!sessionId || sessionStarting || loading || documentBusy || !draft.trim().length}
                  onClick={(e) => animateButtonPress(e.currentTarget)}
                  aria-label={sessionStarting ? "Подготавливаем сессию" : loading ? "Отправка сообщения" : "Отправить сообщение"}
                  title={sessionStarting ? "Подготавливаем сессию" : loading ? "Отправка сообщения" : "Отправить сообщение"}
                >
                  <SendHorizontal size={18} aria-hidden="true" />
                </MaterialButton>
              </div>
            </div>

            <div className="chat-dock-toolbar voice-controls">
              <FigmaDockBg className="dock-bg-svg" preserveAspectRatio="none" />
              <div className="dock-left-actions">
                <MaterialButtonGroup materialKey="chat.media-controls" muted={[microphoneMuted, soundMuted]} className="dock-dual-pill" role="group" aria-label="Микрофон и звук">
                  <MaterialButton materialKey={"App.button-9"}
                    appearance="joined" tone={microphoneMuted ? "danger" : "graphite"}
                    className={`dock-dual-btn ${microphoneMuted ? "is-muted" : ""}${microphoneStarting ? " is-loading" : ""}`}
                    disabled={!liveVoiceSupported || !sessionId || microphoneStarting || voiceState === "stopping"}
                    onClick={(e) => {
                      animateButtonPress(e.currentTarget);
                      if (!liveConversation) {
                        void toggleLive();
                      } else {
                        toggleMicrophoneMute();
                      }
                    }}
                    title={(
                      microphoneStarting
                        ? "Микрофон подключается"
                        : microphoneMuted
                        ? "Микрофон выключен (нажмите, чтобы включить)"
                        : liveConversation
                          ? "Микрофон включён (нажмите, чтобы выключить)"
                          : liveReady
                            ? "Включить микрофон"
                            : "Включить после загрузки голосовых сервисов"
                    ) + (shortcutBindings.microphone ? ` · ${formatBinding(shortcutBindings.microphone)}` : "")}
                    aria-label={microphoneStarting ? "Микрофон подключается" : "Live"}
                    aria-busy={microphoneStarting}
                    aria-pressed={liveConversation && !microphoneMuted}
                    type="button"
                  >
                    <FigmaMicIcon width={24} height={26} />
                  </MaterialButton>
                  <MaterialButton materialKey={"App.button-10"}
                    appearance="joined" tone={soundMuted ? "danger" : "graphite"}
                    className={`dock-dual-btn ${soundMuted ? "is-muted" : ""}`}
                    onClick={(e) => {
                      animateButtonPress(e.currentTarget);
                      toggleSoundMute();
                    }}
                    title={(soundMuted ? "Звук выключен (нажмите, чтобы включить)" : "Звук включён (нажмите, чтобы выключить)") + (shortcutBindings.sound ? ` · ${formatBinding(shortcutBindings.sound)}` : "")}
                    aria-label={soundMuted ? "Звук выключен" : "Звук включён"}
                    aria-pressed={!soundMuted}
                    type="button"
                  >
                    <FigmaHeadphonesIcon width={26} height={25} />
                  </MaterialButton>
                </MaterialButtonGroup>

                <MaterialButton materialKey={"App.button-11"}
                  className="dock-icon-btn"
                  onClick={(e) => {
                    animateButtonPress(e.currentTarget);
                    onOpenSettings?.();
                  }}
                  title="Настройки"
                  aria-label="Параметры"
                  type="button"
                >
                  <span className="btn-content"><FigmaSettingsIcon width={26} height={26} /></span>
                </MaterialButton>
              </div>

              <MaterialButton materialKey={"App.button-12"}
                className="dock-finish-btn"
                type="button"
                onClick={(e) => {
                  animateButtonPress(e.currentTarget);
                  handleFinish();
                }}
                title="Завершить"
                aria-label="Завершить"
              >
                <span className="btn-content">
                  <FigmaExitIcon />
                  <span>Завершить</span>
                </span>
              </MaterialButton>

              <MaterialButton materialKey={"App.button-13"}
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
                <span className="btn-content">
                  <FigmaNewChatIcon />
                  <span>Новый диалог</span>
                </span>
              </MaterialButton>
            </div>
          </form>
        </div>

          {import.meta.env.DEV && liveConversation && conversationDebug && (
            <Disclosure materialKey="conversation.debug" label={<>Диагностика живого разговора</>} className="conversation-debug">

              <dl>
                <div><dt>Phase / generation</dt><dd>{conversationDebug.phase} / {conversationDebug.generation}</dd></div>
                <div><dt>Decision</dt><dd>{conversationDebug.last_decision?.action ?? "—"} · {conversationDebug.last_decision?.reason ?? "—"} · {conversationDebug.last_decision_source ?? "—"}</dd></div>
                <div><dt>Speaker</dt><dd>{conversationDebug.last_speaker_estimate?.role ?? "—"} ({conversationDebug.last_speaker_estimate?.confidence?.toFixed(2) ?? "—"})</dd></div>
                <div><dt>Detector</dt><dd>{conversationDebug.turn_detector?.provider ?? "—"}{conversationDebug.turn_detector?.fallback ? " · fallback" : ""}</dd></div>
                <div><dt>Budget</dt><dd>{Math.round((conversationDebug.speech_budget?.iris_share_2m ?? 0) * 100)}% · {conversationDebug.speech_budget?.initiative_count_10m ?? 0}/2</dd></div>
                <div><dt>Deferred / tasks</dt><dd>{conversationDebug.deferred_reactions?.length ?? 0} / {conversationDebug.active_tasks?.length ?? 0}</dd></div>
              </dl>
            </Disclosure>
          )}
        </div>
      <AppDialog
        open={newDialogConfirmationOpen}
        title="Начать новый диалог?"
        icon={<MessageSquarePlus size={24} aria-hidden="true" />}
        description="Текущий диалог будет завершён и сохранён в истории. Начнётся новый разговор с Iris."
        onClose={() => !newDialogPending && setNewDialogConfirmationOpen(false)}
        variant="danger"
      >
        <div className="dialog-actions">
          <MaterialButton materialKey={"App.button-14"} className="secondary" type="button" disabled={newDialogPending} onClick={() => setNewDialogConfirmationOpen(false)}>
            Отмена
          </MaterialButton>
          <MaterialButton materialKey={"App.button-15"}
            className="danger-button"
            type="button"
            disabled={newDialogPending}
            onClick={() => void startNewDialog()}
            aria-label="Начать новый диалог"
            title="Начать новый диалог"
          >
            {newDialogPending ? "Создаю…" : "Новый диалог"}
          </MaterialButton>
        </div>
      </AppDialog>
    </section>
  );
}

function getStringMetadata(event: BackendEvent, key: string): string | null {
  const value = event.metadata[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}
