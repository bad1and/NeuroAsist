import { useRef, useState } from "react";
import {
  IconInterfaceReset as RotateCcw,
} from "../CustomIcons";
import { notify } from "../notifications";
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

  const run = async (action: () => Promise<DesktopWindowPreferences>, success: string) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    try {
      update(await action());
      notify.success("Окно Iris", success);
    } catch (error) {
      console.error("Could not apply desktop window preferences", error);
      notify.error("Окно Iris", "Не удалось применить настройку окна. Попробуйте ещё раз.");
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
      <section className="settings-card" aria-label="Размер окна">
        <div className="settings-card-header">
          <div className="settings-card-header-main">
            <div className="settings-card-title-group">
              <h3 className="settings-card-title">Размер по умолчанию</h3>
            </div>
          </div>
        </div>
        {preferences && (
          <div className="window-reference-preview">
          <svg viewBox="0 0 240 150" role="img" aria-label="Размер окна по умолчанию и минимальный размер"><rect x="5" y="5" width="230" height="140" rx="16" fill="var(--color-base-deep)" /><rect x="15" y="15" width="210" height="120" rx="12" fill="var(--color-surface-raised)" /><rect x="24" y="24" width={Math.max(30, Math.min(190, preferences.minimum.width / preferences.reference.width * 190))} height={Math.max(25, Math.min(98, preferences.minimum.height / preferences.reference.height * 98))} rx="8" fill="var(--color-accent)" opacity=".6" /></svg>
          <dl className="window-size-summary">
            <div><dt>По умолчанию</dt><dd>{formatSize(preferences.reference)}</dd></div>
            <div><dt>Минимальный размер</dt><dd>{formatSize(preferences.minimum)}</dd></div>
          </dl>
          </div>
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
          description="Вернёт исходный размер. Окно нельзя будет растянуть или развернуть."
          onChange={(locked) => void run(
            () => setReferenceWindowLocked(locked),
            locked ? "Размер окна зафиксирован." : "Изменение размера окна разрешено.",
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
              void run(resetReferenceWindow, "Исходный размер окна восстановлен.");
            }}
          >
            <RotateCcw size={16} aria-hidden="true" />
            Вернуть исходный размер
          </MaterialButton>
        </div>
      </section>
    </div>
  );
}
