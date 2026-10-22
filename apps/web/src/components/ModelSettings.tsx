import { useCallback, useEffect, useRef, useState } from "react";
import { cancelModel, getModels, installModel, removeModel } from "../api";
import { chooseModelDirectory, isDesktopApp, openModelInformation, removeManagedModel, restartDesktopCore } from "../desktop";
import type { ManagedModel } from "../types";
import { notify } from "../notifications";
import { AppDialog } from "./AppDialog";
import { MaterialButton } from "./MaterialButton";

const active = (model: ManagedModel) => ["downloading", "verifying"].includes(model.status);
function modelPurpose(model: ManagedModel): string {
  const name = `${model.id} ${model.name}`.toLowerCase();
  if (/gigaam|whisper|\bstt\b/.test(name)) return "Распознаёт речь с микрофона";
  if (/teratts|\btts\b/.test(name)) return "Озвучивает ответы Iris";
  if (/smart.?turn/.test(name)) return "Определяет конец реплики";
  if (/silero|\bvad\b/.test(name)) return "Определяет начало речи";
  if (/embed|\bbge\b|\be5\b/.test(name)) return "Помогает искать сведения в памяти";
  return "Локальная модель";
}
export function ModelManager(_props: { developerMode?: boolean; onUnlockRequest?: () => void }) {
  const connectionFailed = useRef(false);
  const operationBusy = useRef(false);
  const [models, setModels] = useState<ManagedModel[]>([]);
  const [directory, setDirectory] = useState("");
  const [downloadPending, setDownloadPending] = useState<ManagedModel | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<ManagedModel | null>(null);
  const refresh = useCallback(async () => { const result = await getModels(); setModels(result.models); setDirectory(result.directory ?? ""); }, []);
  const run = async (action: () => Promise<unknown>) => {
    operationBusy.current = true; setBusy(true);
    try { await action(); await refresh(); }
    catch (error) { notify.error("Модели", error instanceof Error ? error.message : String(error), { id: "models.operation" }); }
    finally { operationBusy.current = false; setBusy(false); }
  };
  const chooseDirectory = async () => {
    const result = await chooseModelDirectory();
    if (!result) return;
    setDirectory(result.directory);
    // Maintenance returns after spawning the core; wait for its HTTP listener.
    for (let attempt = 0; attempt < 90; attempt++) {
      try { await refresh(); return; }
      catch { await new Promise(resolve => setTimeout(resolve, 500)); }
    }
    throw new Error("Папка сохранена, но ядро ещё недоступно. Перезапустите Iris.");
  };
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { if (!stopped && !operationBusy.current) { await refresh(); connectionFailed.current = false; } } catch (error) { if (!stopped && !operationBusy.current && !connectionFailed.current) { connectionFailed.current = true; notify.error("Модели", String(error), { id: "models.connection" }); } }
      if (!stopped) timer = setTimeout(() => void poll(), 1500);
    };
    void poll(); return () => { stopped = true; clearTimeout(timer); };
  }, [refresh]);
  return <section className="settings-card" aria-label="Управление моделями" aria-busy={busy}>
    <div className="settings-card-header models-heading">
      <h2 className="settings-card-title">Модели</h2>
      <span className="models-total-size" aria-label="Общий объём моделей" data-i18n-skip>{(models.reduce((sum, model) => sum + model.size_bytes, 0) / 1024**3).toFixed(2)} GiB</span>
    </div>
    <div className="model-item-card">
      <strong>Папка моделей</strong>
      <p data-i18n-skip className="model-storage-path">{directory}</p>
      <MaterialButton materialKey="models.directory" className="secondary" title="При смене папки разговор остановится. Прежние файлы останутся на месте." disabled={busy || models.some(active) || !isDesktopApp()} onClick={() => void run(chooseDirectory)}>Выбрать папку</MaterialButton>
    </div>
    {models.map(model => {
      const percent = model.total_bytes ? Math.min(100, Math.round(100 * model.downloaded_bytes / model.total_bytes)) : 0;
      return <div className="model-item-card" key={model.id}>
        <strong data-i18n-skip>{model.name}</strong>
        <p className="settings-apply-note">{modelPurpose(model)}</p>
        {model.delivery === "upstream_download" && <>
          <div className="model-actions">
            {model.source_url && <MaterialButton materialKey="models.source" className="text-button settings-inline-link" disabled={busy} onClick={() => void run(() => openModelInformation(model.id, "source", model.source_url!))}>Источник модели</MaterialButton>}
            {model.terms_url && <MaterialButton materialKey="models.terms" className="text-button settings-inline-link" disabled={busy} onClick={() => void run(() => openModelInformation(model.id, "terms", model.terms_url!))}>Условия использования</MaterialButton>}
          </div>
        </>}
        <p>{(model.size_bytes / 1024**2).toFixed(1)} MiB · {model.installed ? "Установлена и проверена" : model.status === "verifying" ? "Проверяем файлы" : active(model) ? "Загрузка модели" : "Не установлена"}</p>
        {active(model) && <progress aria-label={model.name} value={percent} max={100}>{percent}%</progress>}
        {model.error && <p className="notice" role="status">{model.error}</p>}
        <div className="model-actions">
          {active(model) ? <MaterialButton materialKey="ModelSettings.1" className="secondary" disabled={busy} onClick={() => void run(() => cancelModel(model.id))}>Отменить загрузку</MaterialButton>
            : !model.installed ? <MaterialButton materialKey="ModelSettings.2" className="primary-button" disabled={busy} onClick={() => setDownloadPending(model)}>{model.status === "failed" || model.status === "cancelled" ? "Повторить загрузку" : "Скачать"}</MaterialButton>
              : <MaterialButton materialKey="ModelSettings.3" className="secondary danger-button" disabled={busy} onClick={() => setPending(model)}>Удалить</MaterialButton>}
        </div>
      </div>;
    })}
    {isDesktopApp() && models.some(model => model.installed) && <MaterialButton materialKey="ModelSettings.4" className="secondary" disabled={busy || models.some(active)} onClick={() => void run(async () => { await restartDesktopCore(); window.location.reload(); })}>Перезапустить голосовые сервисы</MaterialButton>}
    <AppDialog open={downloadPending !== null} onClose={() => setDownloadPending(null)} title="Загрузить модель?" variant="info"
      description="Проверьте папку перед загрузкой.">
      <p data-i18n-skip className="model-storage-path">{directory}</p>
      <div className="model-download-actions">
      <MaterialButton materialKey="models.download.choose" className="secondary" disabled={busy || models.some(active) || !isDesktopApp()} onClick={() => void run(chooseDirectory)}>Выбрать папку</MaterialButton>
      <MaterialButton materialKey="models.download.confirm" className="primary-button" disabled={busy} onClick={() => { const model = downloadPending; setDownloadPending(null); if (model) void run(() => installModel(model.id)); }}>Начать загрузку</MaterialButton>
      <MaterialButton materialKey="models.download.cancel" className="secondary model-download-cancel" disabled={busy} onClick={() => setDownloadPending(null)}>Отмена</MaterialButton>
      </div>
    </AppDialog>
    <AppDialog open={pending !== null} onClose={() => setPending(null)} title="Удалить модель?" variant="danger"
      description="Iris остановит разговор и ядро перед удалением. Модель можно будет скачать повторно.">
      <MaterialButton materialKey="ModelSettings.5" className="secondary" onClick={() => setPending(null)}>Отмена</MaterialButton>
      <MaterialButton materialKey="ModelSettings.6" className="primary-button" onClick={() => { const model = pending; setPending(null); if (model) void run(async () => { if (isDesktopApp()) { await removeManagedModel(model.id); window.location.reload(); } else await removeModel(model.id); }); }}>Удалить</MaterialButton>
    </AppDialog>
  </section>;
}
