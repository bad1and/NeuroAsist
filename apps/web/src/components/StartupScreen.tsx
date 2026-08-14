import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

import type { CoreStatus } from "../desktop";
import { IrisLoader } from "./IrisLoader";
import { WindowChrome } from "./WindowChrome";

const floraAssetsPromise = Promise.all([
  import("../../../../assets/startup-flora-left.webp"),
  import("../../../../assets/startup-flora-right.webp"),
  import("../../../../assets/startup-flora-left-compact.webp"),
  import("../../../../assets/startup-flora-right-compact.webp"),
]);

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
  const [flora, setFlora] = useState<{ left: string; right: string; leftCompact: string; rightCompact: string } | null>(null);
  useEffect(() => {
    let active = true;
    void floraAssetsPromise.then(([left, right, leftCompact, rightCompact]) => {
      if (active) setFlora({
        left: left.default,
        right: right.default,
        leftCompact: leftCompact.default,
        rightCompact: rightCompact.default,
      });
    });
    return () => { active = false; };
  }, []);

  const copy = STATUS_COPY[status];
  const failed = status === "failed" || status === "crashed";
  return (
    <div className="startup-screen">
      <div className="startup-flora startup-flora-left" aria-hidden="true">
        {flora && <picture><source media="(max-width: 700px)" srcSet={flora.leftCompact} /><img src={flora.left} alt="" /></picture>}
      </div>
      <div className="startup-flora startup-flora-right" aria-hidden="true">
        {flora && <picture><source media="(max-width: 700px)" srcSet={flora.rightCompact} /><img src={flora.right} alt="" /></picture>}
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
