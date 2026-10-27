
import { MaterialButton } from "../components/MaterialButton";

import { IconComputerDatabase, IconInterfaceDeleteBin3, IconInterfaceAlertTriangle } from "../CustomIcons";
import { useEffect, useState } from "react";

import { requestJson, clearMemories, reindexMemories, resetAllCompanionData, clearTimelineHistory } from "../api";

import { AppDialog } from "../components/AppDialog";

import { notify } from "../notifications";

import { animateButtonPress } from "../animations";

export function SystemMaintenance({
  developerMode = false,
  onUnlockRequest,
  technical = false,
}: {
  developerMode?: boolean;
  onUnlockRequest?: () => void;
  technical?: boolean;
}) {
  const canManage = !technical || developerMode;
  const [busy, setBusy] = useState(false);
  const [pendingAction, setPendingAction] = useState<{
    title: string;
    description: string;
    action: () => Promise<unknown>;
    success: string;
  } | null>(null);
  const [resetDialogOpen, setResetDialogOpen] = useState(false);
  const [confirmPhrase, setConfirmPhrase] = useState("");
  const [maintenanceCounts, setMaintenanceCounts] = useState<{ messages: number; episodes: number; memories: number; archived_memories: number; plans: number } | null>(null);
  useEffect(() => {
    if (!pendingAction && !resetDialogOpen) return;
    const controller = new AbortController();
    setMaintenanceCounts(null);
    void requestJson<NonNullable<typeof maintenanceCounts>>("/maintenance/preview", { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setMaintenanceCounts(result); }).catch(() => {});
    return () => controller.abort();
  }, [pendingAction, resetDialogOpen]);

  const isPhraseMatched =
    confirmPhrase.trim().toLowerCase() === "удалить историю и память" ||
    confirmPhrase.trim().toLowerCase() === "delete history and memory";

  const run = async (action: () => Promise<unknown>, success: string) => {
    if (!canManage) return;
    setBusy(true);
    try {
      const result = await action();
      const restartRequired =
        typeof result === "object" &&
        result !== null &&
        "chroma_cleanup_pending" in result &&
        Boolean(result.chroma_cleanup_pending);
      notify.success("Настройки",
        restartRequired
          ? `${success} Перезапусти приложение: тогда папка ChromaDB будет удалена полностью.`
          : success
      );
    } catch (error) {
      notify.error("Настройки", error instanceof Error ? error.message : "Не удалось завершить обслуживание.");
    } finally {
      setBusy(false);
      setPendingAction(null);
    }
  };

  const handleResetConfirm = async () => {
    if (!isPhraseMatched || busy || !canManage) return;
    setResetDialogOpen(false);
    setConfirmPhrase("");
    await run(resetAllCompanionData, "История, память и планы удалены.");
  };

  return (
    <section className="settings-card maintenance-card" aria-label="Обслуживание данных">
      <div className="settings-card-header">
        <div className="settings-card-header-main">
          <div className="settings-card-title-group">
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <h2 className="settings-card-title">{technical ? "Поиск по памяти" : "История и память"}</h2>
            </div>
            <p className="settings-card-subtitle">{technical ? "Перестроение поискового индекса без удаления записей." : "История, долгосрочная память и полное удаление данных общения."}</p>
          </div>
        </div>
      </div>

      <div className="maintenance-body">
        {/* Зона 1: Оптимизация и поиск */}
        <div className="maintenance-zone" hidden={!technical}>
          <div className="maintenance-zone-title">Оптимизация и поиск</div>

          <div className="maintenance-row">
            <IconComputerDatabase size={20} className="maintenance-icon" aria-hidden="true" />
            <div className="maintenance-row-copy">
              <strong className="maintenance-row-title">Перестроить индекс памяти</strong>
              <p className="maintenance-row-desc">
                Сами записи останутся на месте. Iris заново подготовит их для поиска.
              </p>
            </div>
            <MaterialButton materialKey={"App.button-34"}
              type="button"
              className="secondary"
              disabled={busy || !canManage}
              onClick={(e) => {
                animateButtonPress(e.currentTarget);
                setPendingAction({
                  title: "Перестроить индекс памяти?",
                  description: "Сами записи останутся на месте. Iris заново подготовит их для поиска.",
                  action: reindexMemories,
                  success: "Индекс памяти перестроен.",
                });
              }}
            >
              Перестроить индекс памяти
            </MaterialButton>
          </div>
        </div>

        {/* Зона 2: Опасная зона */}
        <div className="maintenance-zone" hidden={technical}>
          <div className="maintenance-zone-title is-danger">Опасная зона</div>

          <div className="maintenance-row">
            <IconInterfaceDeleteBin3 size={20} className="maintenance-icon is-danger" aria-hidden="true" />
            <div className="maintenance-row-copy">
              <strong className="maintenance-row-title">Удалить всю историю диалогов</strong>
              <p className="maintenance-row-desc">
                Все диалоги и их сводки будут удалены без возможности восстановления. Долгосрочная память сохранится.
              </p>
            </div>
            <MaterialButton materialKey="App.clear-history"
              type="button"
              className="secondary danger-button"
              disabled={busy || !canManage}
              onClick={(e) => {
                animateButtonPress(e.currentTarget);
                setPendingAction({
                  title: "Удалить всю историю диалогов?",
                  description: "Все диалоги и их сводки будут удалены без возможности восстановления. Долгосрочная память сохранится.",
                  action: clearTimelineHistory,
                  success: "Вся история диалогов удалена.",
                });
              }}
            >
              Удалить всю историю
            </MaterialButton>
          </div>

          <div className="maintenance-row">
            <IconInterfaceDeleteBin3 size={20} className="maintenance-icon is-danger" aria-hidden="true" />
            <div className="maintenance-row-copy">
              <strong className="maintenance-row-title">Перенести память в архив</strong>
              <p className="maintenance-row-desc">
                Текущие факты переместятся в архив и перестанут использоваться. История диалогов сохранится. «Забыть навсегда» удаляет запись отдельно в центре памяти.
              </p>
            </div>
            <MaterialButton materialKey={"App.button-35"}
              type="button"
              className="secondary danger-button"
              disabled={busy || !canManage}
              onClick={(e) => {
                animateButtonPress(e.currentTarget);
                setPendingAction({
                  title: "Перенести память в архив?",
                  description: "Факты будут архивированы и перестанут использоваться. История диалогов и исходные сообщения сохранятся; отдельную запись можно восстановить в архиве.",
                  action: clearMemories,
                  success: "Долгосрочная память очищена.",
                });
              }}
            >
              Перенести в архив
            </MaterialButton>
          </div>

          <div className="maintenance-row">
            <IconInterfaceAlertTriangle size={20} className="maintenance-icon is-danger" aria-hidden="true" />
            <div className="maintenance-row-copy">
              <strong className="maintenance-row-title">Удалить историю и память Iris</strong>
              <p className="maintenance-row-desc">
                История, сводки, память и планы будут удалены без возможности восстановления. Настройки, API-ключи и резервные копии останутся.
              </p>
            </div>
            <MaterialButton materialKey={"App.button-36"}
              type="button"
              className="danger-button"
              disabled={busy || !canManage}
              onClick={(e) => {
                animateButtonPress(e.currentTarget);
                setConfirmPhrase("");
                setResetDialogOpen(true);
              }}
            >
              Удалить историю и память
            </MaterialButton>
          </div>
        </div>
      </div>

      {/* Стандартный диалог подтверждения для переиндексации / очистки памяти */}
      <AppDialog
        open={Boolean(pendingAction)}
        title={pendingAction?.title ?? ""}
        description={pendingAction?.description}
        onClose={() => !busy && setPendingAction(null)}
        variant={technical ? "info" : "danger"}
      >
        <p className="settings-apply-note">{maintenanceCounts ? `Объём профиля сейчас: ${maintenanceCounts.messages} сообщений, ${maintenanceCounts.episodes} диалогов, ${maintenanceCounts.memories} текущих фактов, ${maintenanceCounts.archived_memories} записей архива, ${maintenanceCounts.plans} планов.` : "Проверяю объём данных…"}</p>
        <div className="dialog-actions">
          <MaterialButton materialKey={"App.button-37"} className="secondary" type="button" disabled={busy} onClick={() => setPendingAction(null)}>
            Отмена
          </MaterialButton>
          <MaterialButton materialKey={"App.button-38"}
            className={technical ? "primary-button" : "danger-button"}
            type="button"
            disabled={busy || !canManage}
            onClick={() => pendingAction && void run(pendingAction.action, pendingAction.success)}
          >
            {busy ? "Выполняю…" : "Подтвердить"}
          </MaterialButton>
        </div>
      </AppDialog>

      {/* Специальный модальный диалог со строгим ручным подтверждением фразы */}
      <AppDialog
        open={resetDialogOpen}
        title="Удалить историю и память Iris?"
        description="История, сводки, память и планы будут удалены без возможности восстановления. Настройки, API-ключи и резервные копии останутся."
        onClose={() => {
          if (!busy) {
            setResetDialogOpen(false);
            setConfirmPhrase("");
          }
        }}
        variant="danger"
      >
        <div className="maintenance-confirm-dialog">
          <p className="settings-apply-note">{maintenanceCounts ? `Будут затронуты: ${maintenanceCounts.messages} сообщений, ${maintenanceCounts.episodes} диалогов, ${maintenanceCounts.memories} текущих фактов, ${maintenanceCounts.archived_memories} записей архива и ${maintenanceCounts.plans} планов с напоминаниями.` : "Проверяю объём данных…"}</p>
          <p className="maintenance-confirm-prompt">
            Для подтверждения введите <strong>удалить историю и память</strong>:
          </p>
          <input
            type="text"
            className="maintenance-confirm-input"
            value={confirmPhrase}
            onChange={(e) => setConfirmPhrase(e.target.value)}
            placeholder="удалить историю и память"
            autoFocus
            disabled={busy}
            autoComplete="off"
            spellCheck={false}
          />

          <div className="dialog-actions">
            <MaterialButton materialKey={"App.button-39"}
              className="secondary"
              type="button"
              disabled={busy}
              onClick={() => {
                setResetDialogOpen(false);
                setConfirmPhrase("");
              }}
            >
              Отмена
            </MaterialButton>
            <MaterialButton materialKey={"App.button-40"}
              className="danger-button"
              type="button"
              disabled={busy || !developerMode || !isPhraseMatched}
              onClick={() => void handleResetConfirm()}
            >
              {busy ? "Выполняю…" : "Удалить историю и память"}
            </MaterialButton>
          </div>
        </div>
      </AppDialog>
    </section>
  );
}

