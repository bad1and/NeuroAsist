import type { AvatarHostStatus, CoreStatus } from "./desktop";
import type { ReadinessResponse } from "./types";

export type StartupStage = 1 | 2 | 3;

export type StartupComponentState = "unknown" | "loading" | "ready" | "failed" | "deferred" | "fallback" | "inactive";
export type StartupComponent = {
  id: string;
  label: string;
  state: StartupComponentState;
  activity: string;
};
export type StartupProgressState = {
  components: StartupComponent[];
  /** Completed checks, not an estimate of loading time or bytes. */
  value: number | null;
  settled: number;
  complete: boolean;
  failed: boolean;
  detail: string;
};

const isSettled = (state: StartupComponentState) => ["ready", "failed", "deferred", "fallback", "inactive"].includes(state);

export function getStartupProgress(
  coreStatus: CoreStatus,
  readiness: ReadinessResponse | null,
  waitingForAvatar: boolean,
  avatar: AvatarHostStatus | null = null,
  readinessUnavailable = false,
): StartupProgressState {
  const failed = coreStatus === "failed" || coreStatus === "crashed";
  // A restarting core must not inherit readiness from the preceding process.
  const snapshot = coreStatus === "ready" ? readiness : null;
  const state = (value: ReadinessResponse["stt"] | ReadinessResponse["vad"] | undefined): StartupComponentState =>
    value === "disabled" ? "deferred" : value ?? "unknown";
  const components: StartupComponent[] = [
    { id: "core", label: "Службы Iris", state: failed ? "failed" : coreStatus === "ready" ? "ready" : "loading", activity: "Подключаю сервисы Iris" },
    { id: "text", label: "Диалог", state: state(snapshot?.text_chat), activity: "Подготавливаю диалог" },
    { id: "stt", label: "Распознавание речи", state: state(snapshot?.stt), activity: "Подготавливаю распознавание речи" },
    { id: "tts", label: "Голос Iris", state: state(snapshot?.tts), activity: "Подготавливаю голос Iris" },
    { id: "vad", label: "Определение речи", state: state(snapshot?.vad), activity: "Подготавливаю определение речи" },
  ];
  if (waitingForAvatar || (avatar?.placement === "in_app" && avatar.visible)) {
    components.push({ id: "avatar", label: "3D-аватар", state: avatar?.phase === "failed" || avatar?.phase === "not_configured" ? "failed"
      : avatar?.phase === "ready" ? "ready" : waitingForAvatar ? "loading" : "inactive",
      activity: avatar?.phase === "warming" ? "Подготавливаю первый кадр аватара" : "Запускаю 3D-аватар" });
  }
  const complete = !failed && coreStatus === "ready"
    && getStartupStage(coreStatus, readiness, waitingForAvatar, readinessUnavailable) === 3;
  const settled = components.filter(component => isSettled(component.state)).length;
  const active = components.filter(component => component.state === "loading");
  let detail = "Подключаю сервисы Iris";
  if (failed) detail = "Запуск прерван";
  else if (coreStatus === "ready") {
    if (!snapshot && !readinessUnavailable) detail = "Проверяю готовность сервисов";
    else if (snapshot?.text_chat === "loading") detail = "Подготавливаю диалог";
    else if (active.length > 1) detail = active.some(component => component.id === "avatar")
      ? "Подготавливаю голос и аватар" : "Подготавливаю голосовые сервисы";
    else if (active.length === 1) detail = active[0].activity;
    else if (!snapshot) detail = "Iris запущена · сведения о сервисах недоступны";
    else if (components.some(component => component.state === "failed")) detail = "Iris готова · часть функций недоступна";
    else detail = "Всё готово к разговору";
  }
  return { components, settled, complete, failed, detail,
    value: snapshot && !failed ? complete ? 1 : settled / components.length : null };
}

// A failed/disabled optional service is settled, not a reason to hide diagnostics.
// An unavailable readiness endpoint uses the desktop health signal as a fallback.
export function getStartupStage(
  coreStatus: CoreStatus,
  readiness: ReadinessResponse | null,
  waitingForAvatar: boolean,
  readinessUnavailable = false,
): StartupStage {
  if (coreStatus !== "ready") return 1;
  if (!readiness && !readinessUnavailable) return 1;
  if (readiness?.text_chat === "loading") return 1;
  if (waitingForAvatar || (readiness && [readiness.stt, readiness.tts, readiness.vad].includes("loading"))) return 2;
  return 3;
}
