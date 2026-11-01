import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { MaterialButtonContours } from "./components/MaterialButtonContours";
import { StartupScreen } from "./components/StartupScreen";
import type { AvatarHostStatus } from "./desktop";
import type { ReadinessResponse } from "./types";
import { getStartupProgress, getStartupStage } from "./startup";
import "./tokens.css";
import "./styles.css";
import "./components/StartupScreen.css";
import "./components/MaterialButton.css";
import "./components/FieldMaterial.css";

// Isolated review harness. Production startup receives backend readiness only.
const ready: ReadinessResponse = { phase: "ready", text_chat: "ready", stt: "ready", tts: "ready", vad: "ready", live_ready: true, errors: [] };
const warming: AvatarHostStatus = { placement: "in_app", running: true, embedded: false, visible: true, ready: false, phase: "warming", error: null };
const SCENARIOS = [
  ["core", "Запуск"], ["dialogue", "Диалог"], ["voice", "Голос"], ["avatar", "Аватар"],
  ["degraded", "Часть функций недоступна"], ["deferred", "Без предзагрузки"],
  ["unavailable", "Нет /readiness"], ["ready", "Готово"], ["failed", "Ошибка"],
] as const;
type Scenario = typeof SCENARIOS[number][0];

function StartupPreview() {
  const params = new URLSearchParams(window.location.search);
  const review = params.get("review") === "1";
  const initial = params.get("scenario") ?? "core";
  const [scenario, setScenario] = useState<Scenario>(SCENARIOS.some(([key]) => key === initial) ? initial as Scenario : "core");
  const [attempt, setAttempt] = useState(0);
  const [done, setDone] = useState(false);
  const [revealRequested, setRevealRequested] = useState(false);
  const [playing, setPlaying] = useState(false);
  const appRef = useRef<HTMLDivElement>(null);
  const reset = (next: Scenario = "core", play = false) => {
    setAttempt((value) => value + 1);
    setScenario(next);
    setDone(false);
    setRevealRequested(false);
    setPlaying(play);
  };
  useEffect(() => {
    if (!playing) return;
    const timers = (["dialogue", "voice", "avatar", "ready"] as const).map((next, index) =>
      window.setTimeout(() => setScenario(next), 1800 + index * 1700));
    return () => { timers.forEach(window.clearTimeout); };
  }, [playing, attempt]);
  const status = scenario === "core" ? "starting" : scenario === "failed" ? "failed" : "ready";
  const readiness: ReadinessResponse | null = scenario === "core" || scenario === "unavailable" ? null
    : scenario === "dialogue" ? { ...ready, phase: "starting", text_chat: "loading", stt: "loading", tts: "loading", live_ready: false }
    : scenario === "voice" ? { ...ready, phase: "text_ready", stt: "loading", tts: "loading", live_ready: false }
    : scenario === "degraded" ? { ...ready, phase: "degraded", tts: "failed", live_ready: false, errors: ["Preview voice failure"] }
    : scenario === "deferred" ? { ...ready, phase: "text_ready", stt: "disabled", tts: "disabled", vad: "fallback", live_ready: false }
    : ready;
  const waiting = scenario === "avatar" || scenario === "unavailable";
  const avatar = waiting ? warming : null;
  const stage = getStartupStage(status, readiness, waiting, scenario === "unavailable");
  const progress = getStartupProgress(status, readiness, waiting, avatar, scenario === "unavailable");
  return <>
    <MaterialButtonContours />
    {(revealRequested || done) && <div ref={appRef} inert={!done || undefined}
      aria-hidden={!done || undefined} style={done ? undefined : { opacity: 0 }}><App /></div>}
    {!done && <StartupScreen key={attempt} status={status} stage={stage} progress={progress} subdetail={progress.detail} revealTarget={appRef}
      onReveal={() => setRevealRequested(true)}
      onComplete={review ? undefined : () => { setDone(true); setPlaying(false); }} onRetry={() => reset("core", true)} />}
    {!review && <aside aria-label="Проверка анимации" style={{ position: "fixed", zIndex: 200, top: 38,
      left: "50%", transform: "translateX(-50%)", display: "flex", flexWrap: "wrap",
      justifyContent: "center", gap: 8, width: "min(560px, calc(100% - 24px))", padding: 12,
      borderRadius: 16, background: "var(--color-base-deep)", color: "var(--color-text)", fontSize: 12 }}>
      <button type="button" onClick={() => reset("core", true)}>Воспроизвести</button>
      {SCENARIOS.map(([key, label]) => <button key={key} type="button" onClick={() => reset(key)}>{label}</button>)}
    </aside>}
  </>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><StartupPreview /></React.StrictMode>);
