import { useEffect, useRef, useState } from "react";
import {
  IconMailChatBubbleTextSquare as MessageSquare,
} from "../CustomIcons";
import { AppDialog } from "./AppDialog";
import { MaterialButton } from "./MaterialButton";
import { ApiKeysSettings } from "./ApiKeysSettings";
import { ModelManager } from "./ModelSettings";
import { AudioCheck } from "./AudioCheck";
import { CustomSelect } from "./CustomSelect";
import { getReadiness, getSettings, updateRuntimeSettings } from "../api";
import { getAudioDeviceCatalog, type AudioDeviceCatalog } from "../audio-devices";
import type { PublicSettings, ReadinessResponse } from "../types";

function savedStep() {
  try { return Math.max(0, Math.min(3, Number(localStorage.getItem("iris.setup.step.v1")) || 0)); } catch { return 0; }
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
  const steps = ["Модель ответа", "Речевые модели", "Микрофон и звук", "Первый разговор"];
  return <AppDialog open={open} onClose={onClose} title="Настроить Iris" icon={<MessageSquare size={24} aria-hidden="true" />} variant="info" size="wide">
    {open && <div className="first-conversation-setup">
      <nav className="setup-steps" aria-label="Шаги первого запуска">{steps.map((label, n) => <MaterialButton key={label} materialKey={`setup.step.${n}`} type="button" appearance="quiet" aria-current={step === n ? "step" : undefined} onClick={() => setStep(n)}>{n + 1}. {label}</MaterialButton>)}</nav>
      <p className="memory-section-description">Распознавание и синтез речи работают локально. Текст запроса и нужный контекст отправляются выбранной внешней модели. Ключ хранится в защищённом хранилище Windows.</p>
      {error && <p role="alert" className="error-text">{error}</p>}
      {readinessError && <p role="alert" className="error-text">{readinessError}</p>}
      {!settings ? <p role="status">Ожидаю подключения к Iris…</p> : <>
        {step === 0 && <ApiKeysSettings settings={settings} active only={["deepseek"]} idPrefix="setup-" onSettingsChanged={onSettingsChanged} />}
        {step === 1 && <><p>Для текста речевые модели не нужны. Голос можно подготовить сейчас или позже.</p><ModelManager /></>}
        {step === 2 && <>
          <div className="settings-card-grid">
            <label>Микрофон<CustomSelect value={settings.voice_input_device_id || ""} disabled={busy} onChange={event => void updateDevice("voice_input_device_id", event.target.value)}><option value="">По умолчанию в Windows</option>{settings.voice_input_device_id && !devices?.inputs.some(device => device.deviceId === settings.voice_input_device_id) && <option value={settings.voice_input_device_id}>Выбранный микрофон недоступен</option>}{devices?.inputs.map(device => <option key={device.deviceId} value={device.deviceId}>{device.label}</option>)}</CustomSelect></label>
            <label>Устройство вывода<CustomSelect value={settings.voice_output_device_id || ""} disabled={busy || !devices?.canSelectOutput} onChange={event => void updateDevice("voice_output_device_id", event.target.value)}><option value="">По умолчанию в Windows</option>{settings.voice_output_device_id && !devices?.outputs.some(device => device.deviceId === settings.voice_output_device_id) && <option value={settings.voice_output_device_id}>Выбранное устройство вывода недоступно</option>}{devices?.outputs.map(device => <option key={device.deviceId} value={device.deviceId}>{device.label}</option>)}</CustomSelect></label>
          </div>
          <MaterialButton materialKey="setup.devices-refresh" className="text-button" onClick={() => void refreshDevices(true)}>Разрешить доступ и обновить устройства</MaterialButton>
          <AudioCheck inputDeviceId={settings.voice_input_device_id} outputDeviceId={settings.voice_output_device_id} playbackRate={settings.voice_playback_rate} />
        </>}
        {step === 3 && <div className="setup-readiness"><h3>Готовность к разговору</h3><p>{!settings.api_key_configured ? "Добавьте ключ модели на первом шаге." : readiness?.text_chat === "ready" ? "Текстовый диалог готов" : "Ключ сохранён. Подключаем модель…"}</p><p>{readiness?.live_ready ? "Всё готово. Чтобы говорить, включите микрофон в диалоге." : "Голос пока не готов. Можно начать с текста и вернуться к настройке позже."}</p><MaterialButton materialKey="setup.start" className="primary-button" disabled={!settings.api_key_configured || readiness?.text_chat !== "ready"} onClick={() => { try { localStorage.setItem("iris.setup.completed.v1", "1"); } catch { /* Completion is optional persistence. */ } onClose(); onStart(); }}>Начать разговор</MaterialButton></div>}
      </>}
      <div className="setup-actions"><MaterialButton materialKey="setup.close" className="text-button" type="button" onClick={onClose}>Продолжить позже</MaterialButton>{step > 0 && <MaterialButton materialKey="setup.back" className="secondary" type="button" onClick={() => setStep(value => value - 1)}>Назад</MaterialButton>}{step < 3 && <MaterialButton materialKey="setup.next" className="primary-button" type="button" onClick={() => setStep(value => value + 1)}>Далее</MaterialButton>}</div>
    </div>}
  </AppDialog>;
}
