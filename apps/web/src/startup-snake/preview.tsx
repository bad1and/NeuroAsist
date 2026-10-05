import React, { useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { StartupScreen } from "../components/StartupScreen";
import { MaterialButtonContours } from "../components/MaterialButtonContours";
import type { StartupStage } from "../startup";
import type { CoreStatus } from "../desktop";
import "../fonts/proxima-nova.css";
import "../tokens.css";
import "../styles.css";
import "./preview.css";

function Preview() {
  const showControls = new URLSearchParams(window.location.search).has("controls");
  const [status, setStatus] = useState<CoreStatus>("starting");
  const [stage, setStage] = useState<StartupStage>(2);
  const [attempt, setAttempt] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [done, setDone] = useState(false);
  const appRef = useRef<HTMLDivElement>(null);
  const reset = () => { setStatus("starting"); setStage(2); setRevealed(false); setDone(false); setAttempt((value) => value + 1); };
  return <div className="snake-review">
    <MaterialButtonContours />
    {revealed && <div ref={appRef} className="snake-review-ready" style={{ opacity: done ? 1 : 0 }}>
      <p>Iris готова к разговору</p><button onClick={reset}>Вернуться к макету</button>
    </div>}
    {!done && <>
      <StartupScreen key={attempt} stage={stage} status={status} revealTarget={appRef}
        onReveal={() => setRevealed(true)} onComplete={() => setDone(true)} onRetry={reset} />
    </>}
    {showControls && <nav className="snake-review-tools" aria-label="Макет загрузки">
      <span>Макет</span><button onClick={reset}>Сначала</button>
      <button onClick={() => { setStage(3); setStatus("starting"); }}>Сервисы</button>
      <button onClick={() => { setStage(3); setStatus("ready"); }}>Готово</button>
      <button onClick={() => setStatus("failed")}>Ошибка</button>
    </nav>}
  </div>;
}
createRoot(document.getElementById("root")!).render(<React.StrictMode><Preview /></React.StrictMode>);
