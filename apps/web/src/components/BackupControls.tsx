import { useCallback, useEffect, useState } from "react";
import { createBackup, deleteBackup, getBackups } from "../api";
import { exportDesktopBackup, importDesktopBackup, isDesktopApp, restoreDesktopBackup } from "../desktop";
import { notify } from "../notifications";
import { AppDialog } from "./AppDialog";
import { MaterialButton } from "./MaterialButton";

export function BackupControls() {
  const [backups, setBackups] = useState<Awaited<ReturnType<typeof getBackups>>>([]);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<{ name: string; action: "restore" | "delete" } | null>(null);
  const refresh = useCallback(async () => setBackups(await getBackups()), []);
  const run = async (action: () => Promise<unknown>, success?: string) => {
    setBusy(true);
    try { const result = await action(); await refresh(); if (success && result !== null) notify.success("Резервные копии", success); }
    catch (error) { notify.error("Резервные копии", error instanceof Error ? error.message : String(error), { id: "backups.operation" }); }
    finally { setBusy(false); }
  };
  useEffect(() => { void refresh().catch(error => notify.error("Резервные копии", String(error), { id: "backups.connection" })); }, [refresh]);
  const confirm = () => {
    if (!pending) return;
    const operation = pending; setPending(null);
    void run(async () => {
      if (operation.action === "delete") await deleteBackup(operation.name);
      else { await restoreDesktopBackup(operation.name); window.location.reload(); }
    });
  };
  return <section className="settings-card" aria-label="Резервные копии" aria-busy={busy}>
    <div className="settings-card-header">
      <div className="settings-card-header-main"><div className="settings-card-title-group">
        <h2 className="settings-card-title">Резервные копии</h2>
        <p className="settings-card-subtitle">История, память, настройки и словари. Ключи API не входят в копии.</p>
      </div></div>
      <div className="settings-card-header-actions">
        <MaterialButton materialKey="BackupControls.1" className="primary-button" disabled={busy} onClick={() => void run(createBackup, "Резервная копия создана.")}>Создать копию</MaterialButton>
        <MaterialButton materialKey="BackupControls.2" className="secondary" disabled={busy || !isDesktopApp()} onClick={() => void run(importDesktopBackup, "Импорт завершён.")}>Загрузить копию из ZIP</MaterialButton>
      </div>
    </div>
    {busy && <p role="status">Выполняем операцию…</p>}
    {backups.length === 0 && <p className="empty-state compact">Резервных копий пока нет</p>}
    {backups.map(backup => <div className="model-item-card" key={backup.name}>
      <strong data-i18n-skip style={{ overflowWrap: "anywhere" }}>{backup.name}</strong>
      <p>{new Date(backup.created_at).toLocaleString()} · {(backup.size_bytes / 1024**2).toFixed(1)} MiB</p>
      <div className="model-actions">
        <MaterialButton materialKey="BackupControls.3" className="secondary" disabled={busy || !isDesktopApp()} onClick={() => void run(() => exportDesktopBackup(backup.name))}>Сохранить копию в ZIP</MaterialButton>
        <MaterialButton materialKey="BackupControls.4" className="secondary" disabled={busy || !isDesktopApp()} onClick={() => setPending({ name: backup.name, action: "restore" })}>Восстановить</MaterialButton>
        <MaterialButton materialKey="BackupControls.5" className="secondary danger-button" disabled={busy} onClick={() => setPending({ name: backup.name, action: "delete" })}>Удалить</MaterialButton>
      </div>
    </div>)}
    <small>Срок хранения — 30 дней. Экспортированная копия остаётся в выбранной папке.</small>
    <AppDialog open={pending !== null} onClose={() => setPending(null)} variant="danger"
      title={pending?.action === "restore" ? "Восстановить данные?" : "Удалить копию?"}
      description={pending?.action === "restore" ? "Разговор и задания остановятся. Iris сохранит текущие данные перед заменой и перезапустится. Устройства и проекты потребуется проверить заново." : "Эта резервная копия будет удалена."}>
      {pending?.action === "restore" && <p><strong data-i18n-skip>{pending.name}</strong><br />Будут заменены история, память, настройки и словари. Ключи API в архив не входят; текущие данные будут сохранены перед восстановлением.</p>}
      <MaterialButton materialKey="BackupControls.6" className="secondary" onClick={() => setPending(null)}>Отмена</MaterialButton>
      <MaterialButton materialKey="BackupControls.7" className="primary-button" onClick={confirm}>{pending?.action === "restore" ? "Восстановить" : "Удалить"}</MaterialButton>
    </AppDialog>
  </section>;
}
