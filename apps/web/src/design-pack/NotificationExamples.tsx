import { useCallback, useState } from "react";
import { MaterialButton } from "../components/MaterialButton";
import { NotificationCard } from "../components/NotificationHost";
import type { AppNotification } from "../notifications";

export function NotificationExamples() {
  const [run, setRun] = useState(0);
  const [visible, setVisible] = useState(false);
  const [loadingVisible, setLoadingVisible] = useState(true);
  const [progress, setProgress] = useState(50);
  const dismiss = useCallback((id: string) => {
    if (id === "preview.loading") setLoadingVisible(false);
    else setVisible(false);
  }, []);
  const loading: AppNotification = { id: "preview.loading", type: "info", title: "Подготавливаю микрофон",
    message: `Загружаю голосовые сервисы · ${progress}%`, progress: progress / 100, duration: "persistent", createdAt: 0 };
  const timed: AppNotification = { id: "preview.saved", type: "success", title: "Настройки сохранены",
    message: "Изменения применены", duration: 9000, details: "Образец подробностей уведомления.", createdAt: 0,
    actions: [{ label: "Понятно", variant: "primary", onClick: () => {} }] };
  return <section className="dp-section dp-notification-examples" aria-labelledby="notifications-title">
    <div className="dp-section-heading"><h2 id="notifications-title">Уведомления</h2></div>
    <div className="dp-sample">
      <div className="dp-notification-tools">
        <MaterialButton materialKey="preview.notifications.repeat" appearance="quiet" onClick={() => {
          setRun(value => value + 1); setVisible(true); setLoadingVisible(true);
        }}>Показать отсчёт</MaterialButton>
        <label>Загрузка <input aria-label="Загрузка в образце" type="range" min={0} max={100} value={progress}
          onChange={event => setProgress(Number(event.target.value))} /></label>
      </div>
      <div className="notification-preview">
        {loadingVisible && <NotificationCard notification={loading} onDismiss={dismiss} />}
        {visible && <NotificationCard key={run} notification={timed} onDismiss={dismiss} />}
      </div>
    </div>
  </section>;
}
