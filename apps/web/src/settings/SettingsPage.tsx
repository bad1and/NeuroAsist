import { Disclosure, DisclosureTrigger } from "../components/Disclosure";
import { SystemMaintenance } from "./DataMaintenance";
import { AvatarControls } from "./AvatarSettings";
import { DevBadge } from "./SettingsControls";
import { APP_VERSION } from "../changelog/catalog";
import { SettingsNavigation } from "./SettingsNavigation";
import { MaterialButton } from "../components/MaterialButton";

import { useScrollEdgeFade } from "../components/useScrollEdgeFade";

import { CustomSelect } from "../components/CustomSelect";
import { DictionaryEditor } from "../components/DictionaryEditor";

import { IconInterfaceContentArchive, IconInterfaceAlertAlarmBell2, IconInterfaceSpirals } from "../CustomIcons";
import { Activity as ViewActivity, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { IconInterfaceRefresh as RefreshCw } from "../CustomIcons";
import { ModelManager } from "../components/ModelSettings";
import { BackupControls } from "../components/BackupControls";
import { EnvironmentSettings } from "../components/EnvironmentSettings";
import { ApiKeysSettings } from "../components/ApiKeysSettings";
import { useRuntimeSettingsAutosave, type RuntimeSettingsPatch, type AutoSaveStatus } from "../settingsAutosave";

import { getSettings, getPronunciations, getSttTerms, updatePronunciations, updateSttTerms } from "../api";
import type { BackendEvent, AvatarStatusResponse, AvatarOverlaySettings, EventLevel, PublicSettings, InterfaceLocale } from "../types";

import { getAudioDeviceCatalog, type AudioDeviceCatalog, type AudioDeviceOption } from "../audio-devices";
import { type MicrophoneProfile } from "../vad";

import { openChangelog } from "../changelog/notice";
import { ShortcutSettings } from "../components/ShortcutSettings";

import { AudioCheck } from "../components/AudioCheck";
import { ConversationProfiles, ConversationSettingsDetails } from "../components/ConversationProfiles";
import { StartupSpeedSetting } from "../components/StartupSpeedSetting";

import { isDesktopApp } from "../desktop";

import { WindowSettings } from "../components/WindowSettings";
import { AppDialog } from "../components/AppDialog";
import { AppSwitch } from "../components/AppSwitch";
import { InfoRow } from "../components/InfoRow";
import { GuidedSttCapture } from "../stt-capture";

import { TokenAnalyticsSettings } from "../components/TokenAnalyticsSettings";
import { notify } from "../notifications";

import { interfaceIntlLocale } from "../i18n";
import { animate, animateButtonPress, animatePageEnter, animateStaggerCards, animateTabSwitch, prefersReducedMotion } from "../animations";
import { SETTINGS_SECTIONS, normalizeSettingsSection, type SettingsSection, type SettingsNavigationRequest, type SettingsPageId } from "./registry";
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
function dictionaryValidation(value: string): string | null {
  const words = new Set<string>();
  for (const line of value.split("\n")) {
    const at = line.indexOf("=");
    const left = (at < 0 ? line : line.slice(0, at)).trim();
    const right = at < 0 ? "" : line.slice(at + 1).trim();
    if (!left && !right) continue;
    if (!left || !right) return "Заполните обе части слова или удалите незавершённую строку.";
    if (words.has(left)) return "Одинаковые слова нужно объединить в одну строку.";
    words.add(left);
  }
  return null;
}

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
    return <span ref={elRef} className="settings-save-status is-error" role="alert">Не удалось сохранить <MaterialButton materialKey={"App.button-1"} type="button" onClick={(e) => { animateButtonPress(e.currentTarget); onRetry(); }}>Повторить</MaterialButton></span>;
  }
  if (status === "saved") return <span ref={elRef} className="settings-save-status is-saved" role="status">Сохранено</span>;
  return null;
}

const SettingsSwitch = AppSwitch;

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

type LevelFilter = "all" | EventLevel;
function formatTime(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString(interfaceIntlLocale(), { hour: "2-digit", minute: "2-digit" }); }
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
  const filteredEvents = useMemo(() => {
    const rows = levelFilter === "all" ? events : events.filter(event => event.level === levelFilter);
    const grouped = new Map<string, BackendEvent & { repeat_count: number }>();
    rows.forEach(event => { const key = JSON.stringify([event.type, event.level, event.message]); const previous = grouped.get(key); grouped.set(key, { ...event, repeat_count: (previous?.repeat_count || 0) + 1 }); });
    return [...grouped.values()].sort((left, right) => left.created_at.localeCompare(right.created_at));
  }, [events, levelFilter]);

  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (listRef.current && filteredEvents.length > 0) {
      animateStaggerCards(listRef.current, ".event-row", 30);
    }
  }, [filteredEvents, levelFilter]);

  return (
    <section className="panel events-panel">
      {compact ? (
        <div className="settings-card-header">
          <div className="settings-card-header-main">
            <div className="settings-card-title-group">
              <h2 className="settings-card-title">Журнал событий</h2>
              <p className="settings-card-subtitle">Технические события, ошибки и системная диагностика</p>
            </div>
          </div>
          <div className="settings-card-header-actions">
            <MaterialButton materialKey={"App.button-16"}
              className="secondary"
              onClick={(e) => {
                animateButtonPress(e.currentTarget);
                void onRefreshEvents();
              }}
              aria-label="Обновить журнал событий"
              title="Обновить журнал событий"
            >
              <RefreshCw size={15} aria-hidden="true" />
              Обновить
            </MaterialButton>
          </div>
        </div>
      ) : (
        <div className="panel-header">
          <div><h2>Журнал системы</h2><span>Технические события и диагностика</span></div>
          <MaterialButton materialKey={"App.button-17"} className="secondary" onClick={(e) => { animateButtonPress(e.currentTarget); void onRefreshEvents(); }}>
            <IconInterfaceSpirals size={16} aria-hidden="true" />
            Обновить
          </MaterialButton>
        </div>
      )}

      <div className="filters">
        {(["all", "info", "warning", "error", "critical"] as LevelFilter[]).map(
          (level) => {
            const labels: Record<LevelFilter, string> = { all: "Все", debug: "Отладка", info: "Информация", warning: "Предупреждения", error: "Ошибки", critical: "Критические" };
            return (
            <MaterialButton materialKey={["App.button-18", level].join(":")}
              key={level}
              className={levelFilter === level ? "is-active" : ""}
              onClick={(e) => {
                animateTabSwitch(e.currentTarget);
                setLevelFilter(level);
              }}
            >
              {labels[level]}
            </MaterialButton>
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
                <strong data-i18n-skip>{event.message}{event.repeat_count > 1 && <small> · повторилось {event.repeat_count} раз</small>}</strong>
              </div>
              <Disclosure materialKey={`events.metadata.${event.id}`} label="Технические данные" className="event-details"><pre>{JSON.stringify(event.metadata, null, 2)}</pre></Disclosure>
            </article>
          ))}
      </div>
    </section>
  );
}

export function SettingsPage({
  settings,
  onOpenSetup,
  initialSection,
  navigationRequest,
  avatarStatus,
  avatarOverlay,
  events,
  onRefreshEvents,
  onRefreshAvatar,
  onAvatarOverlayChanged,
  onInterfaceLocaleChange,
  onSettingsChanged,
  qaStudioEnabled,
  onToggleQaStudioEnabled,
  onOpenQaStudio,
  onDraftChange,
}: {
  settings: PublicSettings | null;
  onOpenSetup?: () => void;
  initialSection?: SettingsSection;
  navigationRequest?: SettingsNavigationRequest;
  avatarStatus: AvatarStatusResponse | null;
  avatarOverlay: AvatarOverlaySettings | null;
  events: BackendEvent[];
  onRefreshEvents: () => Promise<void>;
  onRefreshAvatar: () => Promise<void>;
  onAvatarOverlayChanged: (overlay: AvatarOverlaySettings | null) => void;
  onInterfaceLocaleChange: (locale: InterfaceLocale) => void;
  onSettingsChanged: (settings: PublicSettings) => void;
  qaStudioEnabled?: boolean;
  onToggleQaStudioEnabled?: (enabled: boolean) => void;
  onOpenQaStudio?: () => void;
  onDraftChange?: (dirty: boolean) => void;
}) {
  const [activeSection, setActiveSection] = useState<SettingsPageId>(() => {
    const initial = normalizeSettingsSection(initialSection ?? navigationRequest?.section ?? "conversation");
    return initial === "events" && !settings?.developer_mode_enabled ? "developer" : initial;
  });
  const [interfaceLocale, setInterfaceLocale] = useState<InterfaceLocale>("ru");
  const [developerModeEnabled, setDeveloperModeEnabled] = useState(Boolean(settings?.developer_mode_enabled));
  const [backgroundConversationNotificationsEnabled, setBackgroundConversationNotificationsEnabled] = useState(true);
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
  const [pronunciationsSaved, setPronunciationsSaved] = useState("");
  const [sttTermsSaved, setSttTermsSaved] = useState("");
  const [dictionaryLoadError, setDictionaryLoadError] = useState(false);
  const [dictionariesReady, setDictionariesReady] = useState(false);
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
  const [showSttCapture, setShowSttCapture] = useState(false);
  const [environmentValues, setEnvironmentValues] = useState<Partial<PublicSettings>>({});
  const [focusTarget, setFocusTarget] = useState<string | null>(null);
  // Polling must not replace edits waiting in the autosave queue. Only the
  // initial snapshot and confirmed responses update the local form fields.
  const hasInitialSettings = useRef(false);
  const applyRuntimeFields = useCallback((next: PublicSettings, fields: Array<keyof RuntimeSettingsPatch>) => {
    const setters: Partial<Record<keyof RuntimeSettingsPatch, (value: any) => void>> = {
      interface_locale: value => { setInterfaceLocale(value); onInterfaceLocaleChange(value); },
      developer_mode_enabled: setDeveloperModeEnabled,
      background_conversation_notifications_enabled: setBackgroundConversationNotificationsEnabled,
      voice_language: setVoiceLanguage, voice_microphone_profile: setVoiceMicrophoneProfile,
      voice_input_device_id: setVoiceInputDeviceId, voice_output_device_id: setVoiceOutputDeviceId,
      voice_tts_voice: setVoiceTtsVoice, voice_tts_style: setVoiceTtsStyle, voice_tts_expression_level: setVoiceExpressionLevel, voice_playback_rate: setVoicePlaybackRate,
      voice_live_playback_prebuffer_segments: setPrebufferSegments,
      voice_live_playback_prebuffer_ms: setPrebufferMs,
      memory_mode: setMemoryMode, memory_incognito: setMemoryIncognito,
    };
    const environmentPatch: Partial<PublicSettings> = {};
    const livePatch: Partial<LiveConversationSettings> = {};
    for (const field of fields) {
      if (field.startsWith("live_conversation_")) Object.assign(livePatch, { [field]: next[field] });
      else if (["location_mode", "location_city", "weather_enabled", "news_enabled", "news_category", "web_search_enabled", "web_search_notifications_enabled", "web_search_provider"].includes(field)) {
        Object.assign(environmentPatch, { [field]: next[field] });
      } else setters[field]?.(next[field]);
    }
    if (Object.keys(environmentPatch).length) setEnvironmentValues(current => ({ ...current, ...environmentPatch }));
    if (Object.keys(livePatch).length) setLiveSettings(current => ({ ...current, ...livePatch }));
  }, [onInterfaceLocaleChange]);
  const autosave = useRuntimeSettingsAutosave(onSettingsChanged, settings, applyRuntimeFields);

  const [credentialDraft, setCredentialDraft] = useState(false);
  const [pendingNavigation, setPendingNavigation] = useState<{section: SettingsSection; target?: string} | null>(null);
  const openSettingsSection = useCallback((section: SettingsSection, target?: string) => {
    if (credentialDraft && activeSection === "api-keys" && section !== "api-keys") {
      setPendingNavigation({ section, target });
      return;
    }
    autosave.flush();
    const normalized = normalizeSettingsSection(section);
    setActiveSection(normalized === "events" && !developerModeEnabled ? "developer" : normalized);
    setFocusTarget(target ?? (section === "system-window" ? "settings-system-window" : section === "voice-advanced" ? "voice-buffer" : null));
  }, [autosave.flush, developerModeEnabled, credentialDraft, activeSection]);
  const consumedNavigation = useRef<number | null>(null);
  useEffect(() => {
    if (navigationRequest && consumedNavigation.current !== navigationRequest.id) {
      consumedNavigation.current = navigationRequest.id;
      openSettingsSection(navigationRequest.section,
      navigationRequest.focusId || (navigationRequest.target ? `credential-${navigationRequest.target}` : undefined));
    }
  }, [navigationRequest, openSettingsSection]);

  useEffect(() => {
    if (initialSection) openSettingsSection(initialSection);
  }, [initialSection]);

  useEffect(() => { if (!developerModeEnabled && activeSection === "events") setActiveSection("developer"); }, [developerModeEnabled, activeSection]);

  const applySettingsToForm = useCallback((nextSettings: PublicSettings) => {
    setInterfaceLocale(nextSettings.interface_locale === "en" ? "en" : "ru");
    setDeveloperModeEnabled(Boolean(nextSettings.developer_mode_enabled));
    setBackgroundConversationNotificationsEnabled(nextSettings.background_conversation_notifications_enabled ?? true);
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

  const loadDictionaries = useCallback(async () => {
    setDictionaryLoadError(false);
    try {
      const [pronunciation, terms] = await Promise.all([getPronunciations(), getSttTerms()]);
      setPronunciationsText(formatPronunciations(pronunciation.pronunciations));
      setPronunciationsSaved(formatPronunciations(pronunciation.pronunciations));
      setSttTermsText(formatSttTerms(terms.terms));
      setSttTermsSaved(formatSttTerms(terms.terms));
      setDictionariesReady(true);
    } catch { setDictionaryLoadError(true); }
  }, []);
  useEffect(() => { if (settings && !dictionariesReady) void loadDictionaries(); }, [Boolean(settings), dictionariesReady, loadDictionaries]);
  const dictionaryDirty = pronunciationsText !== pronunciationsSaved || sttTermsText !== sttTermsSaved;
  const [cityDirty, setCityDirty] = useState(false);
  const manualDraft = dictionaryDirty || credentialDraft || cityDirty;
  useEffect(() => { onDraftChange?.(manualDraft); }, [manualDraft, onDraftChange]);
  useEffect(() => {
    if (!manualDraft) return;
    const preventLoss = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", preventLoss);
    return () => window.removeEventListener("beforeunload", preventLoss);
  }, [manualDraft]);

  const [saveStatusSection, setSaveStatusSection] = useState<SettingsPageId>("conversation");
  const saveRuntimeSetting = useCallback((patch: RuntimeSettingsPatch, rollback?: () => void) => {
    setSaveStatusSection(activeSection);
    return autosave.save(patch, rollback);
  }, [autosave.save, activeSection]);

  const saveEnvironmentSetting = useCallback((patch: RuntimeSettingsPatch, rollback?: () => void,
    committed?: (next: PublicSettings) => void) => {
    setSaveStatusSection(activeSection);
    setEnvironmentValues(current => ({ ...current, ...patch }));
    return autosave.save(patch, rollback, committed);
  }, [autosave.save, activeSection]);

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

  const scheduleRuntimeSetting = useCallback((patch: RuntimeSettingsPatch, rollback?: () => void) => {
    setSaveStatusSection(activeSection);
    void autosave.save(patch, rollback, undefined, 300);
  }, [autosave.save, activeSection]);

  useEffect(() => () => autosave.flush(), [activeSection, autosave.flush]);

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

  const changeVoiceStyle = (value: string) => {
    const previousValue = voiceTtsStyle;
    setVoiceTtsStyle(value);
    void saveRuntimeSetting({ voice_tts_style: value }, () => setVoiceTtsStyle(previousValue));
  };
  const changeVoiceExpression = (value: string) => {
    const previousValue = voiceExpressionLevel;
    setVoiceExpressionLevel(value);
    void saveRuntimeSetting({ voice_tts_expression_level: value }, () => setVoiceExpressionLevel(previousValue));
  };

  const savePronunciations = async () => {
    setSaving(true);
    try {
      const submitted = pronunciationsText;
      const result = await updatePronunciations(parsePronunciations(submitted));
      const saved = formatPronunciations(result.pronunciations);
      setPronunciationsText(current => current === submitted ? saved : current);
      setPronunciationsSaved(saved);
      notify.success("Настройки", "Словарь произношений сохранён и применён.");
    } catch (error) {
      notify.error("Настройки", error instanceof Error ? error.message : "Не удалось сохранить словарь.");
    } finally {
      setSaving(false);
    }
  };

  const settingsContentRef = useRef<HTMLDivElement | null>(null);
  useScrollEdgeFade(settingsContentRef);
  const previousSettingsSection = useRef(activeSection);
  const sectionScroll = useRef<Partial<Record<SettingsPageId, number>>>({});

  useLayoutEffect(() => {
    if (previousSettingsSection.current === activeSection) return;
    if (settingsContentRef.current) {
      sectionScroll.current[previousSettingsSection.current] = settingsContentRef.current.scrollTop;
      settingsContentRef.current.scrollTop = sectionScroll.current[activeSection] ?? 0;
    }
    previousSettingsSection.current = activeSection;
  }, [activeSection]);

  useLayoutEffect(() => {
    if (!focusTarget) settingsContentRef.current?.querySelector<HTMLElement>(".settings-heading h2")?.focus({ preventScroll: true });
  }, [activeSection]);

  useEffect(() => {
    if (settingsContentRef.current) {
      const motion = animatePageEnter(settingsContentRef.current);
      return () => { motion?.revert(); };
    }
  }, [activeSection, Boolean(settings)]);

  useLayoutEffect(() => {
    if (!focusTarget || !settings) return;
    const heading = settingsContentRef.current?.querySelector<HTMLElement>(`#${focusTarget}`);
    if (!heading) return;
    // A controlled disclosure can reveal after this parent layout effect.
    const focus = () => {
      if (heading.closest("[hidden], [inert], [data-disclosure-animating]")) return false;
      heading.scrollIntoView?.({ block: "start", behavior: "instant" });
      heading.focus({ preventScroll: true });
      setFocusTarget(null);
      return true;
    };
    if (focus()) return;
    const observer = new MutationObserver(() => { if (focus()) observer.disconnect(); });
    observer.observe(settingsContentRef.current!, { subtree: true, attributes: true, attributeFilter: ["hidden", "inert", "data-disclosure-animating"] });
    return () => observer.disconnect();
  }, [focusTarget, activeSection, Boolean(settings)]);

  if (!settings) {
    return (
      <section className="panel settings-panel">
        <SettingsNavigation current={activeSection} onChange={openSettingsSection} />
        <div className="settings-content" ref={settingsContentRef}>
          {activeSection === "system-interface" ? <>
            <header className="settings-heading"><h2>Интерфейс и окно</h2></header>
            <div className="form-grid settings-form"><StartupSpeedSetting /><WindowSettings /></div>
          </> : activeSection === "shortcuts" ? <>
            <header className="settings-heading"><h2>Сочетания клавиш</h2><p>Настройте клавиши для частых действий.</p></header>
            <ShortcutSettings />
          </> : activeSection === "about" ? <section className="settings-card"><h2>Iris <span data-i18n-skip>{APP_VERSION}</span></h2><MaterialButton materialKey="settings.offline-changelog" className="secondary" onClick={openChangelog}>Что нового</MaterialButton></section> : <div className="empty-state"><IconInterfaceAlertAlarmBell2 size={28} aria-hidden="true" /><strong>Настройки недоступны</strong><span>Нет связи с ядром Iris. Локальные настройки окна и клавиш остаются доступны.</span><MaterialButton materialKey="settings.retry-core" className="secondary" onClick={() => void getSettings().then(onSettingsChanged).catch(() => notify.error("Настройки", "Ядро пока недоступно."))}>Повторить подключение</MaterialButton></div>}
        </div>
      </section>
    );
  }

  const ttsProviderLabel = settings.voice_tts_provider === "teratts" ? "TeraTTSv2" : settings.voice_tts_provider;
  const ttsRuntimeLabel = [ttsProviderLabel, settings.voice_tts_device?.toUpperCase()]
    .filter(Boolean)
    .join(" · ");
  const settingsSectionMeta = SETTINGS_SECTIONS;

  const saveSttTerms = async () => {
    setSaving(true);
    try {
      const submitted = sttTermsText;
      const result = await updateSttTerms(parseSttTerms(submitted));
      const saved = formatSttTerms(result.terms);
      setSttTermsText(current => current === submitted ? saved : current);
      setSttTermsSaved(saved);
      notify.success("Настройки", "Словарь распознавания сохранён и применён.");
    } catch (error) {
      notify.error("Настройки", error instanceof Error ? error.message : "Не удалось сохранить словарь распознавания.");
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

  const activeSettingsMeta = settingsSectionMeta[activeSection] || { title: "", description: "" };
  const desktopCredentialStorageAvailable = isDesktopApp();

  return (
    <section className="panel settings-panel">
      <AppDialog open={Boolean(pendingNavigation)} title="Отбросить введённый ключ?" description="Новый ключ ещё не сохранён. При переходе введённый текст будет удалён." onClose={() => setPendingNavigation(null)} variant="warning">
        <MaterialButton materialKey="settings.keep-key-draft" className="secondary" onClick={() => setPendingNavigation(null)}>Остаться</MaterialButton>
        <MaterialButton materialKey="settings.discard-key-draft" className="danger-button" onClick={() => {
          const pending = pendingNavigation; setPendingNavigation(null); setCredentialDraft(false);
          if (pending) { setActiveSection(normalizeSettingsSection(pending.section)); setFocusTarget(pending.target ?? null); }
        }}>Отбросить и перейти</MaterialButton>
      </AppDialog>
      <SettingsNavigation current={activeSection} developerMode={developerModeEnabled} onChange={openSettingsSection} />

      <div className="settings-content" ref={settingsContentRef}>
        {autosave.status === "error" && <div className="notice is-error settings-inline-notice" role="alert">
          <span>Не удалось сохранить часть изменений настроек.</span>
          <MaterialButton materialKey="settings.retry-autosave" className="secondary" onClick={autosave.retry}>Повторить</MaterialButton>
        </div>}

        <header className="settings-heading" hidden={activeSection === "token-usage"}>
          <div className="settings-heading-row">
            <div>
              <h2 id={`settings-${activeSection}`} tabIndex={-1}>{activeSettingsMeta.title}</h2>
              <p>{activeSettingsMeta.description}</p>
            </div>
            {autosave.status !== "error" && saveStatusSection === activeSection && !(activeSection === "voice" && pronunciationsText !== pronunciationsSaved) && !(activeSection === "voice-recognition" && sttTermsText !== sttTermsSaved) && !["shortcuts", "api-keys", "token-usage", "system-overview", "models", "backups", "maintenance", "events", "avatar", "about"].includes(activeSection) && <AutoSaveStatus status={autosave.status} onRetry={autosave.retry} />}
          </div>
        </header>

        {activeSection === "about" && <section className="settings-card"><h3>Iris <span data-i18n-skip>{APP_VERSION}</span></h3><p>Настольный помощник для общения и повседневных задач.</p><MaterialButton materialKey="settings.changelog" className="secondary" onClick={openChangelog}>Что нового</MaterialButton></section>}
        <div className="form-grid settings-form" hidden={activeSection !== "api-keys"}>
          <ApiKeysSettings settings={settings} active={activeSection === "api-keys"} collapseOptional revealTarget={focusTarget} onDirtyChange={setCredentialDraft}
            onSettingsChanged={onSettingsChanged} />
        </div>

        {onOpenSetup && <section className="settings-card" hidden={activeSection !== "system-overview"}>
          <div className="settings-card-header">
            <div className="settings-card-title-group">
              <h3 className="settings-card-title">Первый разговор</h3>
              <p className="settings-card-subtitle">Подключите модель и проверьте микрофон перед разговором.</p>
            </div>
          </div>
          <div className="settings-card-actions">
            <MaterialButton materialKey="system.first-conversation" className="primary-button" onClick={onOpenSetup}>Настроить Iris</MaterialButton>
          </div>
        </section>}
        <div className="settings-scenario-grid" hidden={activeSection !== "system-overview"}>
          <article className="settings-scenario">
            <h3 className="settings-card-title">Ответы</h3>
            <p>{settings.api_key_configured ? "Ключ модели настроен" : "Нужен ключ модели"}</p>
            <MaterialButton materialKey="system.open-keys" className="secondary" onClick={() => openSettingsSection("api-keys")}>API-ключи</MaterialButton>
          </article>
          <article className="settings-scenario">
            <h3 className="settings-card-title">Голос</h3>
            <p>Готовность локальных моделей и выбранных устройств.</p>
            <MaterialButton materialKey="system.open-audio" className="secondary" onClick={() => openSettingsSection("voice-devices")}>Проверить устройства</MaterialButton>
          </article>
          <article className="settings-scenario">
            <h3 className="settings-card-title">Аватар</h3>
            <p>Размещение и состояние подключения.</p>
            <MaterialButton materialKey="system.open-avatar" className="secondary" onClick={() => openSettingsSection("avatar")}>Открыть аватар</MaterialButton>
          </article>
          <article className="settings-scenario">
            <h3 className="settings-card-title">Поиск</h3>
            <p>{settings.web_search_enabled ? "Поиск включён" : "Поиск выключен"}</p>
            <MaterialButton materialKey="system.open-search" className="secondary" onClick={() => openSettingsSection("internet")}>Источники информации</MaterialButton>
          </article>
        </div>
        <Disclosure materialKey="system.technical" label="Технические данные системы" hidden={activeSection !== "system-overview"}>
        <div className="settings-grid system-status-grid">
          <InfoRow label="DeepSeek API" value={settings.api_key_configured ? "Настроен" : "Не настроен"} />
          <InfoRow label="Coding API" value={settings.coding_api_key_configured ? "Настроен" : "Не настроен"} />
          <InfoRow label="Провайдер" value={settings.provider} />
          <InfoRow label="Модель" value={settings.model} />
          <InfoRow label="История в контексте" value={`${settings.chat_history_limit} сообщений`} />
          <InfoRow label="Уровень журнала" value={settings.log_level} />
          <InfoRow
            label="Голос"
            value={`${settings.voice_language} / ${settings.voice_tts_voice} / ${settings.voice_playback_rate.toFixed(2)}x`}
          />
        </div></Disclosure>

        {activeSection === "shortcuts" && <ShortcutSettings />}

        <div className="form-grid settings-form" hidden={activeSection !== "system-interface"}>
          {/* Interface Language Card */}
          <div className="settings-card">
            <div className="settings-card-header">
              <div className="settings-card-header-main">
                <div className="settings-card-title-group">
                  <h3 className="settings-card-title">Язык интерфейса</h3>
                  <p className="settings-card-subtitle">Язык меню, кнопок и подсказок.</p>
                </div>
              </div>
            </div>

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
            </label>
          </div>

          {activeSection === "system-interface" && <StartupSpeedSetting />}

          {activeSection === "system-interface" && <section id="settings-system-window" tabIndex={-1} className="settings-section-anchor"><WindowSettings /></section>}
        </div>

        <div className="form-grid settings-form" hidden={activeSection !== "notifications"}>
          <div className="settings-card">
            <SettingsSwitch
              checked={backgroundConversationNotificationsEnabled}
              label="Разговор в уведомлениях"
              description="Показывать субтитры и управление микрофоном сверху уведомлений вне диалога. Если выключить, разговор продолжится без панели."
              onChange={(checked) => {
                const previousValue = backgroundConversationNotificationsEnabled;
                setBackgroundConversationNotificationsEnabled(checked);
                saveRuntimeSetting(
                  { background_conversation_notifications_enabled: checked },
                  () => setBackgroundConversationNotificationsEnabled(previousValue),
                );
              }}
            />
          </div>

          <section className="settings-card">
            <SettingsSwitch checked={environmentValues.web_search_notifications_enabled ?? settings.web_search_notifications_enabled ?? false}
              label="Показывать поиск в уведомлениях" description="Этапы поиска и источники. История сохраняется и без уведомлений."
              onChange={checked => void saveEnvironmentSetting({ web_search_notifications_enabled: checked })} />
          </section>
        </div>
        <div className="form-grid settings-form" hidden={activeSection !== "developer"}>
          {/* Developer Tools & QA Studio Card */}
          <div className="settings-card">
            <div className="settings-card-header">
              <div className="settings-card-header-main">
                <div className="settings-card-title-group">
                  <h3 className="settings-card-title">Инструменты разработчика</h3>
                  <p className="settings-card-subtitle">Диагностика и расширенные настройки Iris.</p>
                </div>
              </div>
            </div>

            <SettingsSwitch
              checked={developerModeEnabled}
              label="Режим разработчика"
              description="Открывает технические параметры голоса и настроения, журнал событий и инструменты проверки."
              onChange={(checked) => {
                const previousValue = developerModeEnabled;
                setDeveloperModeEnabled(checked);
                saveRuntimeSetting(
                  { developer_mode_enabled: checked },
                  () => setDeveloperModeEnabled(previousValue),
                );
              }}
            />
            <SettingsSwitch
              disabled={!developerModeEnabled}
              checked={Boolean(qaStudioEnabled)}
              label="Окно тестирования (QA Studio)"
              description="Отдельное окно для тестирования аватара, эмоций, жестов, речи и системных уведомлений. При включении открывается, при выключении — закрывается."
              onChange={(checked) => {
                onToggleQaStudioEnabled?.(checked);
              }}
            />
          </div>
        </div>
        <div className="system-stack" hidden={!(["models", "backups", "maintenance", "events"] as SettingsSection[]).includes(activeSection)}>
          <ViewActivity mode={activeSection === "models" ? "visible" : "hidden"}><div hidden={activeSection !== "models"}>
            <ModelManager
              developerMode={developerModeEnabled}
              onUnlockRequest={() => openSettingsSection("developer")}
            />
          </div></ViewActivity>
          <ViewActivity mode={activeSection === "backups" ? "visible" : "hidden"}><div hidden={activeSection !== "backups"}><BackupControls /></div></ViewActivity>
          <ViewActivity mode={activeSection === "maintenance" ? "visible" : "hidden"}><div hidden={activeSection !== "maintenance"}>
            <SystemMaintenance
              developerMode={developerModeEnabled}
              onUnlockRequest={() => openSettingsSection("developer")}
            />
          </div></ViewActivity>
          <ViewActivity mode={activeSection === "events" ? "visible" : "hidden"}><div hidden={activeSection !== "events"}>
            <EventsPage events={events} onRefreshEvents={onRefreshEvents} compact />
          </div></ViewActivity>
        </div>

        {activeSection === "developer" && developerModeEnabled && <SystemMaintenance technical developerMode />}
        <ViewActivity mode={activeSection === "avatar" || activeSection === "developer" && developerModeEnabled ? "visible" : "hidden"}><div hidden={activeSection !== "avatar" && !(activeSection === "developer" && developerModeEnabled)}>
          <AvatarControls diagnostics={activeSection === "developer"}
            avatarStatus={avatarStatus}
            overlay={avatarOverlay}
            placement={settings.avatar_placement}
            inAppVisible={settings.avatar_in_app_visible}
            interfaceLocale={interfaceLocale}
            developerMode={developerModeEnabled}
            onUnlockRequest={() => openSettingsSection("developer")}
            onRefresh={onRefreshAvatar}
            onOverlayChanged={onAvatarOverlayChanged}
            onSettingsChanged={onSettingsChanged}
            onOpenQaStudio={onOpenQaStudio}
          />
        </div></ViewActivity>

        <ViewActivity mode={activeSection === "environment" || activeSection === "internet" ? "visible" : "hidden"}><div className="form-grid settings-form" hidden={activeSection !== "environment" && activeSection !== "internet"}>
          <EnvironmentSettings section={activeSection === "internet" ? "search" : "context"}
            onDirtyChange={setCityDirty}
            onOpenNotifications={() => openSettingsSection("notifications")}
            settings={{ ...settings, ...environmentValues }}
            developerMode={developerModeEnabled}
            onSaveSetting={saveEnvironmentSetting}
            onOpenApiKeys={() => openSettingsSection("api-keys", "credential-tavily")}
          />
        </div></ViewActivity>

        <ViewActivity mode={activeSection === "token-usage" ? "visible" : "hidden"}><div hidden={activeSection !== "token-usage"}>
          <TokenAnalyticsSettings />
        </div></ViewActivity>

        <div className="form-grid settings-form" hidden={!["conversation", "voice", "voice-devices", "voice-recognition", "memory", "developer"].includes(activeSection)}>
          {/* VOICE: Synthesis Card */}
          <div className="settings-card" hidden={activeSection !== "voice"}>
            <div className="settings-card-header">
              <div className="settings-card-header-main">
                <div className="settings-card-title-group">
                  <h3 className="settings-card-title">Как звучит Iris</h3>
                  <p className="settings-card-subtitle">Выберите голос и настройте скорость речи.</p>
                </div>
              </div>

            </div>

            <div className="settings-card-grid">
              <label>
                Голос {ttsProviderLabel}{settings.available_tts_voices.length === 1 && <small>Установлен один голос</small>}
                <CustomSelect
                  value={voiceTtsVoice}
                  disabled={saving || settings.available_tts_voices.length < 2}
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
                  step="0.01"
                  type="range"
                  value={voicePlaybackRate}
                  disabled={saving}
                  onChange={(event) => {
                    const nextValue = Number(event.target.value);
                    const previousValue = voicePlaybackRate;
                    setVoicePlaybackRate(nextValue);
                    scheduleRuntimeSetting({ voice_playback_rate: nextValue }, () => setVoicePlaybackRate(previousValue));
                  }}
                />
              </label>

              <label>
                Подача голоса
                <CustomSelect value={voiceTtsStyle} onChange={(event) => void changeVoiceStyle(event.target.value)} disabled={saving}>
                  <option value="auto">Автоматически — по настроению Iris</option>
                  <option value="calm">Спокойно</option>
                  <option value="normal">Обычно</option>
                  <option value="energetic">Энергично</option>
                  <option value="thoughtful">Задумчиво</option>
                  <option value="assertive">Напористо</option>
                </CustomSelect>
                <small>Выбор сохраняется между запусками. «Автоматически» подбирает подачу по настроению Iris.</small>
              </label>

              <label>
                Выразительность
                <CustomSelect value={voiceExpressionLevel} onChange={(event) => void changeVoiceExpression(event.target.value)} disabled={saving}>
                  <option value="minimal">Минимальная — почти нейтрально</option>
                  <option value="natural">Естественная — рекомендовано</option>
                  <option value="noticeable">Заметная — сильнее эмоции</option>
                </CustomSelect>
                <small>Усиливает или смягчает выбранную подачу. Выбор сохраняется между запусками.</small>
              </label>
            </div>


            <AudioCheck checks={["voice"]} outputDeviceId={voiceOutputDeviceId} playbackRate={voicePlaybackRate} />
          </div>

          {/* VOICE-RECOGNITION: Pronunciations Card */}
          <div id="voice-pronunciations" tabIndex={-1} className="settings-card settings-section-anchor" hidden={activeSection !== "voice"}>
            <div className="settings-card-header">
              <div className="settings-card-header-main">
                <div className="settings-card-title-group">
                  <h3 className="settings-card-title">Произношение слов</h3>
                  <p className="settings-card-subtitle">Укажите, как произносить имена и незнакомые слова.</p>
                </div>
              </div>

            </div>

            {dictionaryLoadError && <p role="alert">Не удалось загрузить словари. <MaterialButton materialKey="settings.retry-dictionaries-voice" appearance="quiet" onClick={() => void loadDictionaries()}>Повторить</MaterialButton></p>}
            {pronunciationsText !== pronunciationsSaved && <p role="status" className="settings-saved-note">{dictionaryValidation(pronunciationsText) || "Есть несохранённые изменения словаря."}</p>}
            <DictionaryEditor value={pronunciationsText} onChange={setPronunciationsText} leftLabel="Слово" rightLabel="Как произносить" disabled={saving || !dictionariesReady} /><p className="settings-apply-note">Изменения применяются после сохранения словаря. Пример: Iris → Ирис.</p>
            <div className="settings-card-actions">
              <MaterialButton materialKey={"App.button-25"} className="secondary" type="button" onClick={() => void savePronunciations()} disabled={saving || !dictionariesReady || pronunciationsText === pronunciationsSaved || Boolean(dictionaryValidation(pronunciationsText))}>
                Сохранить словарь
              </MaterialButton>
            </div>
          </div>

          {/* VOICE-DEVICES: Devices Card */}
          <div className="settings-card" hidden={activeSection !== "voice-devices"}>


            <div className="settings-card-grid">


              <label>
                Микрофон для разговора
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
              </label>

              <label className="settings-field-full">
                Где воспроизводить голос Iris
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
                    ? "Голос Iris и сообщения будут звучать здесь. Резервный голос использует устройство по умолчанию в Windows."
                    : "Выбор устройства недоступен. Звук выводится на устройство по умолчанию в Windows."}
                </small>
              </label>
            </div>

            <AudioCheck checks={["microphone"]} inputDeviceId={voiceInputDeviceId} />
            <div className="settings-card-grid">
              <label>
                Профиль микрофона
                <CustomSelect
                  value={voiceMicrophoneProfile}
                  disabled={saving}
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
                <small>
                  Подавляет шум и эхо с учётом того, используете вы гарнитуру или колонки.

                </small>
              </label>
              <label>
                Защита от собственного голоса
                <CustomSelect
                  value={liveSettings.live_conversation_echo_mode}
                  disabled={saving}
                  onChange={(event) => updateLiveSetting(
                    "live_conversation_echo_mode",
                    event.target.value as LiveConversationSettings["live_conversation_echo_mode"],
                  )}
                >
                  <option value="auto">Автоматически</option>
                  <option value="half_duplex">Не слушать во время ответа</option>
                </CustomSelect>
              </label>
            </div>

            <div className="readonly-setting audio-device-refresh">
              <span>Аудиоустройства</span>
              <MaterialButton materialKey={"App.button-23"}
                className="secondary"
                type="button"
                onClick={() => void refreshAudioDevices(true)}
                disabled={saving || audioDevicesLoading}
              >
                {audioDevicesLoading ? "Обновляем…" : "Разрешить доступ и обновить"}
              </MaterialButton>
              {audioDevicesMessage && <small role="status">{audioDevicesMessage}</small>}
            </div>
          </div>

          {/* VOICE-RECOGNITION: VAD Card */}
          <div className="settings-card" hidden={activeSection !== "developer" || !developerModeEnabled}>
            <div className="settings-card-header">
              <div className="settings-card-header-main">
                <div className="settings-card-title-group">
                  <h3 className="settings-card-title">Голосовые движки</h3>
                  <p className="settings-card-subtitle">Техническое состояние распознавания и синтеза речи.</p>
                </div>
              </div>
              <div className="settings-card-header-actions">
                <DevBadge active={developerModeEnabled} onClick={() => openSettingsSection("developer")} />
              </div>
            </div>

            <div className={`readonly-setting${!developerModeEnabled ? " dev-locked-field" : ""}`}>
              <span>Детектор речи</span>
              <strong>
                {settings.voice_vad?.active_provider ?? "energy"}
                {settings.voice_vad?.model ? ` · ${settings.voice_vad.model}` : ""}
                {settings.voice_vad?.ready ? " · готов" : " · fallback"}
              </strong>
              {settings.voice_vad?.fallback_reason && <small>{settings.voice_vad.fallback_reason}</small>}
            </div>
            <div className={`readonly-setting${!developerModeEnabled ? " dev-locked-field" : ""}`}>
              <span>Движок синтеза</span>
              <strong>
                {ttsRuntimeLabel}
                {" · активен"}
              </strong>
            </div>
          </div>

          {/* VOICE: Language Card */}
          <div className="settings-card" hidden={activeSection !== "voice-recognition"}>
            <div className="settings-card-header">
              <div className="settings-card-header-main">
                <div className="settings-card-title-group">
                  <h3 className="settings-card-title">Распознавание речи</h3>
                  <p className="settings-card-subtitle">Выберите язык, на котором будете говорить с Iris.</p>
                </div>
              </div>
            </div>

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
          </div>

          {/* VOICE-RECOGNITION: STT Terms Card */}
          <div className="settings-card" hidden={activeSection !== "voice-recognition"}>
            <div className="settings-card-header">
              <div className="settings-card-header-main">
                <div className="settings-card-title-group">
                  <h3 className="settings-card-title">Исправления распознавания</h3>
                  <p className="settings-card-subtitle">Добавьте слова, которые Iris часто слышит неправильно.</p>
                </div>
              </div>

            </div>

            {dictionaryLoadError && <p role="alert">Не удалось загрузить словари. <MaterialButton materialKey="settings.retry-dictionaries-input" appearance="quiet" onClick={() => void loadDictionaries()}>Повторить</MaterialButton></p>}
            {sttTermsText !== sttTermsSaved && <p role="status" className="settings-saved-note">{dictionaryValidation(sttTermsText) || "Есть несохранённые изменения словаря."}</p>}
            <DictionaryEditor value={sttTermsText} onChange={setSttTermsText} leftLabel="Правильное написание" rightLabel="Как Iris слышит (варианты через |)" disabled={saving || !dictionariesReady} /><p className="settings-apply-note">Например: NeuroAsist → Нейро Асист | нейроасист. Iris будет исправлять только указанные варианты.</p>
            <div className="settings-card-actions">
              <MaterialButton materialKey={"App.button-24"} className="secondary" type="button" onClick={() => void saveSttTerms()} disabled={saving || !dictionariesReady || sttTermsText === sttTermsSaved || Boolean(dictionaryValidation(sttTermsText))}>
                Сохранить словарь распознавания
              </MaterialButton>
            </div>
          </div>

          {/* VOICE-ADVANCED: Buffer & Guided STT Card */}
          <div className="settings-card" hidden={activeSection !== "developer" || !developerModeEnabled}>
            <div className="settings-card-header">
              <div className="settings-card-header-main">
                <div className="settings-card-title-group">
                  <h3 id="voice-buffer" tabIndex={-1} className="settings-card-title">Воспроизведение и тестовые записи</h3>
                  <p className="settings-card-subtitle">Настройки для проверки прерываний и задержек звука.</p>
                </div>
              </div>
              <div className="settings-card-header-actions">
                <DevBadge active={developerModeEnabled} onClick={() => openSettingsSection("developer")} />
              </div>
            </div>

            <div className="settings-card-grid">
              <label className={!developerModeEnabled ? "dev-locked-field" : ""}>
                Сегментов в буфере
                <input
                  min="1"
                  max="4"
                  step="1"
                  type="number"
                  value={prebufferSegments}
                  disabled={!developerModeEnabled}
                  onChange={(event) => {
                    const nextValue = Number(event.target.value);
                    const previousValue = prebufferSegments;
                    setPrebufferSegments(nextValue);
                    scheduleRuntimeSetting({ voice_live_playback_prebuffer_segments: nextValue }, () => setPrebufferSegments(previousValue));
                  }}
                />
              </label>

              <label className={!developerModeEnabled ? "dev-locked-field" : ""}>
                Задержка буфера, мс
                <input
                  min="0"
                  max="1500"
                  step="50"
                  type="number"
                  value={prebufferMs}
                  disabled={!developerModeEnabled}
                  onChange={(event) => {
                    const nextValue = Number(event.target.value);
                    const previousValue = prebufferMs;
                    setPrebufferMs(nextValue);
                    scheduleRuntimeSetting({ voice_live_playback_prebuffer_ms: nextValue }, () => setPrebufferMs(previousValue));
                  }}
                />
              </label>
            </div>

            <div className="settings-card-actions">
              <DisclosureTrigger materialKey={"App.button-26"}
                open={showSttCapture}
                aria-controls="stt-guided-capture"
                disabled={!developerModeEnabled}
                onClick={() => setShowSttCapture((value) => !value)}
              >
                {showSttCapture ? "Скрыть сбор тестовых записей" : "Записать примеры для проверки распознавания"}
              </DisclosureTrigger>
            </div>
          </div>

          {showSttCapture && activeSection === "developer" && developerModeEnabled && (
            <GuidedSttCapture profile={voiceMicrophoneProfile} inputDeviceId={voiceInputDeviceId} />
          )}

          {activeSection === "conversation" && <ConversationProfiles engagement={liveSettings.live_conversation_engagement} initiative={liveSettings.live_conversation_initiative} onChange={patch => {
            const previous = liveSettings;
            setLiveSettings(current => ({ ...current, ...patch }));
            saveRuntimeSetting(patch, () => setLiveSettings(previous));
          }}>              <label className="settings-field-full">
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
              </label></ConversationProfiles>}
          {/* CONVERSATION: Card 1 - Format & Initiative */}
          <ConversationSettingsDetails hidden={activeSection !== "conversation"} reveal={focusTarget === "conversation-timing"}>
          <div className="settings-card" hidden={activeSection !== "conversation"}>
            <div className="settings-card-header">
              <div className="settings-card-header-main">
                <div className="settings-card-title-group">
                  <h3 className="settings-card-title">Участники и инициатива</h3>
                  <p className="settings-card-subtitle">
                    Кто участвует в беседе и как часто Iris проявляет инициативу.
                  </p>
                </div>
              </div>
            </div>

            <div className="settings-card-grid">

              <label>
                Активность в беседе
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
            </div>
          </div>

          {/* CONVERSATION: Card 2 - Speech Dynamics & Timings */}
          <div className="settings-card" hidden={activeSection !== "conversation"}>
            <div className="settings-card-header">
              <div className="settings-card-header-main">
                <div className="settings-card-title-group">
                  <h3 className="settings-card-title" id="conversation-timing" tabIndex={-1}>Паузы и перебивания</h3>
                  <p className="settings-card-subtitle">Когда Iris ждёт продолжения, отвечает или уступает слово.</p>
                </div>
              </div>

            </div>

            <div className="settings-card-grid">
              <label>
                Чувствительность к перебиванию
                <CustomSelect
                  value={liveSettings.live_conversation_interruption_sensitivity}
                  disabled={saving}
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
                Прямое обращение
                <CustomSelect
                  value={liveSettings.live_conversation_address_strictness}
                  disabled={saving}
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
                Терпимость к паузам
                <CustomSelect
                  value={liveSettings.live_conversation_pause_tolerance}
                  disabled={saving}
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
            </div>
          </div>

          </ConversationSettingsDetails>
          {/* CONVERSATION: Card 3 - Emotions & Audio Balance */}
          <div className="settings-card" hidden={activeSection !== "developer" || !developerModeEnabled}>
            <div className="settings-card-header">
              <div className="settings-card-header-main">
                <div className="settings-card-title-group">
                  <h3 className="settings-card-title">Эмоции и настроение</h3>
                </div>
              </div>
              <div className="settings-card-header-actions">
                <DevBadge active={developerModeEnabled} onClick={() => openSettingsSection("developer")} />
              </div>
            </div>

            <div className="settings-card-grid">
              <label className={!developerModeEnabled ? "dev-locked-field" : ""}>
                Выраженность эмоций
                <CustomSelect
                  value={liveSettings.live_conversation_emotion_expression}
                  disabled={!developerModeEnabled}
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

              <label className={!developerModeEnabled ? "dev-locked-field" : ""}>
                Восстановление настроения
                <CustomSelect
                  value={liveSettings.live_conversation_mood_recovery}
                  disabled={!developerModeEnabled}
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

              <label className={!developerModeEnabled ? "dev-locked-field" : ""}>
                Влияние недавних событий
                <CustomSelect
                  value={liveSettings.live_conversation_recent_event_weight}
                  disabled={!developerModeEnabled}
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

            </div>
          </div>

          {/* MEMORY: Long-term Memory Card */}

          <div className="settings-card" hidden={activeSection !== "memory"}>
            <div className="settings-card-header">
              <div className="settings-card-header-main">
                <div className="settings-card-title-group">
                  <h3 className="settings-card-title">Долгосрочная память</h3>
                  <p className="settings-card-subtitle">Режим ниже управляет долгосрочными фактами. История сообщений сохраняется отдельно, если не включено инкогнито.</p>
                </div>
              </div>

            </div>

            <label>
              Режим сохранения
              <CustomSelect
                value={memoryMode}
                disabled={saving}
                onChange={(event) => {
                  const nextValue = event.target.value;
                  const previousValue = memoryMode;
                  setMemoryMode(nextValue);
                  saveRuntimeSetting({ memory_mode: nextValue }, () => setMemoryMode(previousValue));
                }}
              >
                <option value="off">Не сохранять новые факты</option>
                <option value="balanced">Умный — только важные устойчивые факты</option>
                <option value="automatic">Автоматический — все обычные факты</option>
              </CustomSelect>
            </label>

            <div id="memory-incognito" tabIndex={-1} className="settings-section-anchor"><SettingsSwitch
              checked={memoryIncognito}
              label="Режим инкогнито"
              description="Действует, пока вы его не выключите, в том числе после перезапуска. Новые сообщения и факты не сохраняются. Прежние данные остаются, запросы отправляются выбранной модели."
              onChange={(checked) => {
                const previousValue = memoryIncognito;
                setMemoryIncognito(checked);
                saveRuntimeSetting({ memory_incognito: checked }, () => setMemoryIncognito(previousValue));
              }}
            /></div>
          </div>
        </div>

      </div>
    </section>
  );
}

