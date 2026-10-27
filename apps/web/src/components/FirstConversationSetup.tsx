import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import {
  IconInterfaceArrowRight as ArrowRight,
  IconInterfaceCheckCircle as CheckCircle,
  IconInterfaceClock as Clock,
  IconInterfaceKey as Key,
  IconInterfaceMicrophone as Microphone,
  IconMailChatBubbleTextSquare as MessageSquare,
} from "../CustomIcons";
import { animate, isTestEnvironment, prefersReducedMotion } from "../animations/core";
import { AppDialog } from "./AppDialog";
import { MaterialButton } from "./MaterialButton";
import { ApiKeysSettings } from "./ApiKeysSettings";
import { ModelManager } from "./ModelSettings";
import { AudioCheck } from "./AudioCheck";
import { CustomSelect } from "./CustomSelect";
import { useScrollEdgeFade } from "./useScrollEdgeFade";
import { SetupStepNavigation } from "./SetupStepNavigation";
import { getReadiness, getSettings, updateRuntimeSettings } from "../api";
import { getAudioDeviceCatalog, type AudioDeviceCatalog } from "../audio-devices";
import type { PublicSettings, ReadinessResponse } from "../types";
import "./FirstConversationSetup.css";

const steps = [
  { label: "Модель ответа", short: "Ответы", hint: "Подключение DeepSeek", title: "Подключим модель ответа", description: "Добавьте ключ DeepSeek — он нужен Iris для диалога и работы с памятью." },
  { label: "Речевые модели", short: "Голос", hint: "Локальные модели", title: "Подготовим голос", description: "Для текста речевые модели не нужны. Голос можно подготовить сейчас или позже." },
  { label: "Микрофон и звук", short: "Устройства", hint: "Выбор и проверка звука", title: "Проверим микрофон и звук", description: "Выберите, через что говорить и слушать Iris. Микрофон включится только по вашему нажатию." },
  { label: "Первый разговор", short: "Разговор", hint: "Готовность к разговору", title: "Начнём знакомство", description: "Проверьте готовность Iris. Начать можно с текста, а голос настроить в удобное время." },
];

function savedStep() {
  try { return Math.max(0, Math.min(3, Math.trunc(Number(localStorage.getItem("iris.setup.step.v1"))) || 0)); } catch { return 0; }
}

function SetupPage({ step, focusHeading, children }: { step: number; focusHeading: boolean; children: ReactNode }) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const headingId = useId();
  useScrollEdgeFade(viewportRef);
  useLayoutEffect(() => {
    if (focusHeading) headingRef.current?.focus({ preventScroll: true });
    if (!viewportRef.current || isTestEnvironment()) return;
    const motion = animate(viewportRef.current, { opacity: [0, 1], duration: prefersReducedMotion() ? 100 : 180, ease: "outQuad" });
    return () => { motion.cancel(); };
  }, [focusHeading]);
  return <section ref={viewportRef} className={`setup-page${step === 1 ? " setup-models-page" : ""}`} aria-labelledby={headingId} tabIndex={0}>
    <div className="setup-page-inner">
      <header className="setup-page-heading">
        <span className="setup-eyebrow">Шаг {step + 1} из {steps.length}</span>
        <h3 ref={headingRef} id={headingId} tabIndex={-1}>{steps[step].title}</h3>
        <p>{steps[step].description}</p>
      </header>
      {children}
    </div>
  </section>;
}

function ReadinessRow({ icon, title, ready, children }: { icon: ReactNode; title: string; ready: boolean; children: ReactNode }) {
  return <div className="setup-readiness-row">
    <span className="setup-readiness-icon" aria-hidden="true">{icon}</span>
    <div><h4>{title}</h4><p>{children}</p></div>
    <span className={`setup-readiness-state${ready ? " is-ready" : ""}`}>
      {ready ? <CheckCircle size={16} aria-hidden="true" /> : <Clock size={16} aria-hidden="true" />}
      {ready ? "Готово" : "Не готово"}
    </span>
  </div>;
}

export function FirstConversationSetup({ open, settings, onSettingsChanged, onClose, onStart }: {
  open: boolean; settings: PublicSettings | null; onSettingsChanged: (settings: PublicSettings) => void;
  onClose: () => void; onStart: () => void;
}) {
  const [step, setStep] = useState(savedStep);
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [devices, setDevices] = useState<AudioDeviceCatalog | null>(null);
  const [error, setError] = useState("");
  const [readinessError, setReadinessError] = useState("");
  const [busy, setBusy] = useState(false);
  const revision = useRef(0);
  const deviceRevision = useRef(0);
  const saving = useRef(false);
  const focusStepHeading = useRef(false);
  useEffect(() => { try { localStorage.setItem("iris.setup.step.v1", String(step)); } catch { /* The wizard remains usable. */ } }, [step]);
  useEffect(() => {
    if (!open) return;
    let stopped = false;
    let pending = false;
    const refresh = async () => {
      if (pending || saving.current) return;
      pending = true;
      const token = revision.current;
      try { const [next, ready] = await Promise.all([getSettings(), getReadiness()]); if (!stopped && token === revision.current) { onSettingsChanged(next); setReadiness(ready); setReadinessError(""); } }
      catch (cause) { if (!stopped) setReadinessError(cause instanceof Error ? cause.message : "Не удалось проверить готовность"); }
      finally { pending = false; }
    };
    void refresh(); const timer = setInterval(() => void refresh(), 3000);
    return () => { stopped = true; clearInterval(timer); };
  }, [open, onSettingsChanged]);
  const refreshDevices = async (requestPermission = false) => {
    const token = ++deviceRevision.current;
    try { const next = await getAudioDeviceCatalog(requestPermission); if (token === deviceRevision.current) { setDevices(next); setError(""); } }
    catch (cause) { if (token === deviceRevision.current) setError(cause instanceof Error ? cause.message : "Не удалось получить устройства"); }
  };
  useEffect(() => {
    if (!open || step !== 2) return;
    const refresh = () => { void refreshDevices(); };
    refresh(); navigator.mediaDevices?.addEventListener?.("devicechange", refresh);
    return () => { deviceRevision.current++; navigator.mediaDevices?.removeEventListener?.("devicechange", refresh); };
  }, [open, step]);
  const updateDevice = async (key: "voice_input_device_id" | "voice_output_device_id", value: string) => {
    revision.current++; saving.current = true;
    setBusy(true); setError("");
    try { onSettingsChanged(await updateRuntimeSettings({ [key]: value })); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Не удалось сохранить устройство"); }
    finally { saving.current = false; setBusy(false); }
  };
  const goToStep = (next: number, focusHeading = true) => { focusStepHeading.current = focusHeading; setStep(next); };
  const textReady = Boolean(settings?.api_key_configured && readiness?.text_chat === "ready");
  const start = () => {
    try { localStorage.setItem("iris.setup.completed.v1", "1"); } catch { /* Completion is optional persistence. */ }
    onClose(); onStart();
  };
  const heading = <SetupStepNavigation steps={steps} step={step} onSelect={next => goToStep(next, false)} />;
  return <AppDialog className="first-conversation-dialog" open={open} onClose={onClose} title="Настроить Iris" headerContent={heading} variant="info" size="wide" presentation="spotlight">
    {open && <div className="first-conversation-setup">
      <div className="setup-workspace">
      <SetupPage key={step} step={step} focusHeading={focusStepHeading.current}>
        {error && <p role="alert" className="error-text">{error}</p>}
        {readinessError && <p role="alert" className="error-text">{readinessError}</p>}
        {!settings ? <p className="setup-connection-status" role="status">Ожидаю подключения к Iris…</p> : <>
        {step === 0 && <>
          <div className="setup-content-panel"><ApiKeysSettings settings={settings} active only={["deepseek"]} idPrefix="setup-" onSettingsChanged={onSettingsChanged} /></div>
          <aside className="setup-privacy-note"><Key size={17} aria-hidden="true" /><p>Ключ хранится в защищённом хранилище Windows. Текст запроса и нужный контекст отправляются DeepSeek. Распознавание и синтез речи работают локально.</p></aside>
        </>}
        {step === 1 && <div className="setup-content-panel setup-models"><ModelManager /></div>}
        {step === 2 && <>
          <div className="setup-content-panel setup-devices">
          <h4>Устройства</h4>
          <div className="settings-card-grid">
            <label>Микрофон<CustomSelect value={settings.voice_input_device_id || ""} disabled={busy} onChange={event => void updateDevice("voice_input_device_id", event.target.value)}><option value="">По умолчанию в Windows</option>{settings.voice_input_device_id && !devices?.inputs.some(device => device.deviceId === settings.voice_input_device_id) && <option value={settings.voice_input_device_id}>Выбранный микрофон недоступен</option>}{devices?.inputs.map(device => <option key={device.deviceId} value={device.deviceId}>{device.label}</option>)}</CustomSelect></label>
            <label>Устройство вывода<CustomSelect value={settings.voice_output_device_id || ""} disabled={busy || !devices?.canSelectOutput} onChange={event => void updateDevice("voice_output_device_id", event.target.value)}><option value="">По умолчанию в Windows</option>{settings.voice_output_device_id && !devices?.outputs.some(device => device.deviceId === settings.voice_output_device_id) && <option value={settings.voice_output_device_id}>Выбранное устройство вывода недоступно</option>}{devices?.outputs.map(device => <option key={device.deviceId} value={device.deviceId}>{device.label}</option>)}</CustomSelect></label>
          </div>
          <MaterialButton materialKey="setup.devices-refresh" className="text-button" onClick={() => void refreshDevices(true)}>Разрешить доступ и обновить устройства</MaterialButton>
          </div>
          <div className="setup-content-panel setup-audio-check"><h4>Проверка звука</h4><p>Скажите пару слов в микрофон или послушайте пробную фразу Iris.</p>
          <AudioCheck inputDeviceId={settings.voice_input_device_id} outputDeviceId={settings.voice_output_device_id} playbackRate={settings.voice_playback_rate} />
          </div>
        </>}
        {step === 3 && <section className="setup-content-panel setup-readiness" aria-label="Готовность к разговору" aria-live="polite">
          <ReadinessRow icon={<MessageSquare size={22} />} title="Текстовый диалог" ready={textReady}>{!settings.api_key_configured ? "Добавьте ключ модели на первом шаге." : textReady ? "Текстовый диалог готов" : "Ключ сохранён. Подключаем модель…"}</ReadinessRow>
          <ReadinessRow icon={<Microphone size={22} />} title="Голосовой разговор" ready={Boolean(readiness?.live_ready)}>{readiness?.live_ready ? "Всё готово. Чтобы говорить, включите микрофон в диалоге." : "Голос пока не готов. Можно начать с текста и вернуться к настройке позже."}</ReadinessRow>
          {!settings.api_key_configured && <MaterialButton materialKey="setup.return-to-key" className="secondary" type="button" onClick={() => goToStep(0)}>Добавить ключ модели<ArrowRight size={16} aria-hidden="true" /></MaterialButton>}
        </section>}
        </>}
      </SetupPage>
      <footer className="setup-actions">
        <MaterialButton materialKey="setup.close" className="text-button setup-later" type="button" onClick={onClose}>Продолжить позже</MaterialButton>
        <div className="setup-paging">
          {step > 0 && <MaterialButton materialKey="setup.back" className="secondary" type="button" onClick={() => goToStep(step - 1)}>Назад</MaterialButton>}
          {step < 3 ? <MaterialButton materialKey="setup.next" className="primary-button" type="button" onClick={() => goToStep(step + 1)}>Далее<ArrowRight size={16} aria-hidden="true" /></MaterialButton>
            : <MaterialButton materialKey="setup.start" className="primary-button" type="button" disabled={!textReady} onClick={start}>Начать разговор<ArrowRight size={16} aria-hidden="true" /></MaterialButton>}
        </div>
      </footer>
      </div>
    </div>}
  </AppDialog>;
}
