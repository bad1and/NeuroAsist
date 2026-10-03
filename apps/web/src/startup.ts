import type { CoreStatus } from "./desktop";
import type { ReadinessResponse } from "./types";

export type StartupStage = 1 | 2 | 3;

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
