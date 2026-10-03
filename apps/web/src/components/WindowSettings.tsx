import { useRef, useState } from "react";
import { RotateCcw } from "lucide-react";
import { animateButtonPress } from "../animations";
import { resetReferenceWindow, setReferenceWindowLocked, type DesktopWindowPreferences } from "../desktop";
import { useDesktopWindowPreferences } from "../useDesktopWindowPreferences";
import { AppSwitch } from "./AppSwitch";
import { MaterialButton } from "./MaterialButton";
import "./WindowSettings.css";

const formatSize = (size: { width: number; height: number }) => `${Math.round(size.width)} × ${Math.round(size.height)}`;

export function WindowSettings() {
  const { available, preferences, loadError, update, retry } = useDesktopWindowPreferences();
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const run = async (action: () => Promise<DesktopWindowPreferences>, success: string) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setMessage(null);
    setFailed(false);
    try {
      update(await action());
      setMessage(success);
    } catch (error) {
      console.error("Could not apply desktop window preferences", error);
      setFailed(true);
      setMessage("Не удалось применить настройку окна. Попробуйте ещё раз.");
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  const adapted = preferences && (
    Math.abs(preferences.reference.width - preferences.effectiveReference.width) > 1
    || Math.abs(preferences.reference.height - preferences.effectiveReference.height) > 1
  );

  return (
    <div className="form-grid settings-form" aria-busy={busy}>
      <section className="settings-card" aria-label="Эталонное окно">
        <div className="settings-card-header">
          <div className="settings-card-header-main">
            <div className="settings-card-title-group">
              <h3 className="settings-card-title">Эталонный размер</h3>
              <p className="settings-card-subtitle">Начальный размер окна, для которого настроены пропорции и отступы интерфейса.</p>
            </div>
          </div>
        </div>
        {preferences && (
          <dl className="window-size-summary">
            <div><dt>Эталон</dt><dd>{formatSize(preferences.reference)}</dd></div>
            <div><dt>Минимальный размер</dt><dd>{formatSize(preferences.minimum)}</dd></div>
          </dl>
        )}
        {adapted && <p className="muted">На этом экране размер ограничен доступной рабочей областью.</p>}
        {!available && <p className="muted">Управление размером окна доступно в настольном приложении Iris.</p>}
        {available && !preferences && !loadError && <p role="status">Загрузка настройки окна…</p>}
        {loadError && (
          <div className="notice is-error" role="alert">
            <span>Не удалось загрузить настройку окна.</span>
            <MaterialButton materialKey="window-settings.retry" type="button" appearance="quiet" onClick={retry}>Повторить</MaterialButton>
          </div>
        )}
        <AppSwitch
          checked={preferences?.locked ?? false}
          disabled={!available || !preferences || busy}
          label="Запретить изменение размера окна"
          description="Возвращает эталонный размер и отключает растягивание и разворачивание. Сохраняется после перезапуска Iris."
          onChange={(locked) => void run(
            () => setReferenceWindowLocked(locked),
            locked ? "Эталонный размер зафиксирован." : "Изменение размера окна разрешено.",
          )}
        />
        <div className="settings-card-actions">
          <MaterialButton
            materialKey="window-settings.reset"
            type="button"
            className="secondary"
            disabled={!available || !preferences || busy}
            onClick={(event) => {
              animateButtonPress(event.currentTarget);
              void run(resetReferenceWindow, "Окно возвращено к эталонному размеру.");
            }}
          >
            <RotateCcw size={16} aria-hidden="true" />
            Вернуть эталонный размер
          </MaterialButton>
        </div>
        <p className="muted">Сброс размера выводит окно из развёрнутого режима. Фиксация остаётся в выбранном состоянии.</p>
        {message && <p className={failed ? "notice is-error" : "muted"} role={failed ? "alert" : "status"}>{message}</p>}
      </section>
    </div>
  );
}
