import { RefreshCw } from "lucide-react";

import type { CoreStatus } from "../desktop";
import leftFloraUrl from "../../../../assets/Для загрузки лево.png";
import rightFloraUrl from "../../../../assets/Для загрузки права.png";
import { IrisLoader } from "./IrisLoader";
import { WindowChrome } from "./WindowChrome";

const STATUS_COPY: Record<CoreStatus, { title: string; detail: string }> = {
  starting: { title: "Запускаю Iris", detail: "Подготавливаю ядро, модель и голосовые сервисы" },
  ready: { title: "Рада тебя видеть", detail: "Всё готово к разговору" },
  failed: { title: "Не удалось запустить ядро", detail: "Проверь журнал диагностики или попробуй ещё раз" },
  crashed: { title: "Ядро завершило работу", detail: "Iris сохранила данные и готова к повторному запуску" },
};

export function StartupScreen({
  status,
  retrying,
  onRetry,
}: {
  status: CoreStatus;
  retrying: boolean;
  onRetry: () => void;
}) {
  const copy = STATUS_COPY[status];
  const failed = status === "failed" || status === "crashed";
  return (
    <div className="startup-screen">
      <div className="startup-flora startup-flora-left" aria-hidden="true">
        <img src={leftFloraUrl} alt="" />
      </div>
      <div className="startup-flora startup-flora-right" aria-hidden="true">
        <img src={rightFloraUrl} alt="" />
      </div>
      <WindowChrome title="" compact />
      <main className={`startup-content is-${status}`} aria-live="polite">
        <div className="startup-mark" aria-hidden="true">
          <IrisLoader size="hero" active={status === "starting" || retrying} />
        </div>
        <div className="startup-copy">
          <h1>{copy.title}</h1>
          <p>{copy.detail}</p>
        </div>
        {failed && (
          <button className="primary-button" type="button" onClick={onRetry} disabled={retrying}>
            <RefreshCw size={17} className={retrying ? "is-spinning" : ""} aria-hidden="true" />
            {retrying ? "Перезапускаю…" : "Попробовать снова"}
          </button>
        )}
      </main>
    </div>
  );
}
