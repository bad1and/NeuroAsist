import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { MaterialButtonContours } from "./components/MaterialButtonContours";
import { StartupScreen } from "./components/StartupScreen";
import type { CoreStatus } from "./desktop";
import type { StartupStage } from "./startup";
import "./fonts/proxima-nova.css";
import "./tokens.css";
import "./styles.css";
import "./components/StartupScreen.css";
import "./components/MaterialButton.css";
import "./components/FieldMaterial.css";

// Isolated review harness. Production startup receives backend readiness only.
function StartupPreview() {
  const readyOnMount = new URLSearchParams(window.location.search).get("scenario") === "ready";
  const [attempt, setAttempt] = useState(0);
  const [stage, setStage] = useState<StartupStage>(readyOnMount ? 3 : 1);
  const [status, setStatus] = useState<CoreStatus>(readyOnMount ? "ready" : "starting");
  const [done, setDone] = useState(false);
  const [revealRequested, setRevealRequested] = useState(false);
  const [playing, setPlaying] = useState(false);
  const appRef = useRef<HTMLDivElement>(null);
  const reset = (play = false) => {
    setAttempt((value) => value + 1);
    setStage(1);
    setStatus("starting");
    setDone(false);
    setRevealRequested(false);
    setPlaying(play);
  };
  useEffect(() => {
    if (!playing) return;
    const model = window.setTimeout(() => setStage(2), 2000);
    const services = window.setTimeout(() => setStage(3), 4000);
    const ready = window.setTimeout(() => setStatus("ready"), 5600);
    return () => { [model, services, ready].forEach(window.clearTimeout); };
  }, [playing, attempt]);
  return <>
    <MaterialButtonContours />
    {(revealRequested || done) && <div ref={appRef} inert={!done || undefined}
      aria-hidden={!done || undefined} style={done ? undefined : { opacity: 0 }}><App /></div>}
    {!done && <StartupScreen key={attempt} status={status} stage={stage} revealTarget={appRef}
      onReveal={() => setRevealRequested(true)}
      onComplete={() => { setDone(true); setPlaying(false); }} onRetry={() => reset(true)} />}
    <aside aria-label="Проверка анимации" style={{ position: "fixed", zIndex: 200, bottom: 12,
      left: "50%", transform: "translateX(-50%)", display: "flex", flexWrap: "wrap",
      justifyContent: "center", gap: 8, width: "min(560px, calc(100% - 24px))", padding: 12,
      borderRadius: 16, background: "var(--color-base-deep)", color: "var(--color-text)", fontSize: 12 }}>
      <button type="button" onClick={() => reset(true)}>Воспроизвести</button>
      <button type="button" onClick={() => reset()}>Сначала</button>
      <button type="button" onClick={() => { reset(); setStage(3); setStatus("ready"); }}>Быстрый запуск</button>
      <button type="button" onClick={() => { setPlaying(false); setStage(2); }}>Модель</button>
      <button type="button" onClick={() => { setPlaying(false); setStage(3); }}>Сервисы</button>
      <button type="button" onClick={() => { setPlaying(false); setStage(3); setStatus("ready"); }}>Готово</button>
      <button type="button" onClick={() => { setPlaying(false); setStatus("failed"); }}>Ошибка</button>
    </aside>
  </>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><StartupPreview /></React.StrictMode>);
