import type {
  AvatarStatusResponse,
  AvatarOverlaySettings,
  BackendEvent,
  ChatResponse,
  PublicSettings,
  StatusResponse,
  VoiceChatResponse,
  VoiceLiveResponse,
  VoiceTtsStatusResponse,
  TimelineJournalItem,
  TimelineMessage,
  MemoryAuditItem,
  MemoryItem,
} from "./types";

const DESKTOP_RUNTIME =
  typeof window === "undefined" ? undefined : window.__NEUROASIST_DESKTOP_CONFIG__;

export const API_BASE_URL =
  DESKTOP_RUNTIME?.apiBaseUrl
  ?? import.meta.env.VITE_API_BASE_URL
  ?? "http://127.0.0.1:8000";

export function isDesktopManaged(): boolean {
  return Boolean(DESKTOP_RUNTIME && window.__TAURI_INTERNALS__);
}

async function invokeDesktop<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  if (!window.__TAURI_INTERNALS__) {
    throw new Error("This action is available only in the installed desktop app.");
  }
  return window.__TAURI_INTERNALS__.invoke<T>(command, args);
}

export function saveDesktopApiKey(apiKey: string): Promise<unknown> {
  return invokeDesktop("save_api_key", { apiKey });
}

export const WS_EVENTS_URL =
  DESKTOP_RUNTIME?.wsEventsUrl
  ?? import.meta.env.VITE_WS_EVENTS_URL
  ?? `${API_BASE_URL.replace(/^http/, "ws")}/ws/events`;

export function voiceWebSocketUrl(sessionId: string): string {
  const base = API_BASE_URL.replace(/^http/, "ws");
  const token = DESKTOP_RUNTIME?.apiToken;
  return `${base}/ws/voice/${encodeURIComponent(sessionId)}?version=1${token ? `&token=${encodeURIComponent(token)}` : ""}`;
}

export function voiceInputWebSocketUrl(sessionId: string): string {
  const base = API_BASE_URL.replace(/^http/, "ws");
  const token = DESKTOP_RUNTIME?.apiToken;
  return `${base}/ws/voice-input/${encodeURIComponent(sessionId)}?version=1${token ? `&token=${encodeURIComponent(token)}` : ""}`;
}

function audioExtensionForMime(mimeType: string): string {
  const normalized = mimeType.split(";")[0].trim().toLowerCase();
  if (normalized === "audio/ogg" || normalized === "application/ogg") {
    return ".ogg";
  }
  if (normalized === "audio/mp4" || normalized === "audio/x-m4a") {
    return ".m4a";
  }
  if (normalized === "audio/wav" || normalized === "audio/x-wav") {
    return ".wav";
  }
  if (normalized === "audio/mpeg") {
    return ".mp3";
  }
  return ".webm";
}

async function requestJson<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    ...(DESKTOP_RUNTIME?.apiToken
      ? { "X-NeuroAsist-Token": DESKTOP_RUNTIME.apiToken }
      : {}),
    ...(options.headers as Record<string, string> | undefined),
  };

  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers,
    ...options,
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") {
        detail = payload.detail;
      }
    } catch {
      // Keep the status-only error.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<T>;
}

export function getStatus(): Promise<StatusResponse> {
  return requestJson<StatusResponse>("/status");
}

export function getSettings(): Promise<PublicSettings> {
  return requestJson<PublicSettings>("/settings/public");
}

export function updateRuntimeSettings(payload: {
  personality?: string;
  voice_language?: string;
  voice_tts_voice?: string;
  voice_playback_rate?: number;
  voice_live_playback_prebuffer_segments?: number;
  voice_live_playback_prebuffer_ms?: number;
  memory_mode?: string;
  memory_incognito?: boolean;
}): Promise<PublicSettings> {
  return requestJson<PublicSettings>("/settings/runtime", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function getEvents(limit = 100): Promise<{ events: BackendEvent[] }> {
  return requestJson<{ events: BackendEvent[] }>(`/events?limit=${limit}`);
}

export function getVoiceTtsStatus(
  voiceRequestId: string,
): Promise<VoiceTtsStatusResponse> {
  return requestJson<VoiceTtsStatusResponse>(`/voice/tts/${voiceRequestId}`);
}

export function sendChatMessage(
  sessionId: string,
  message: string,
): Promise<ChatResponse> {
  return requestJson<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      message,
    }),
  });
}

export function sendLiveTextMessage(
  sessionId: string,
  message: string,
): Promise<VoiceLiveResponse> {
  return requestJson<VoiceLiveResponse>("/chat/live", {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      message,
    }),
  });
}

export async function sendVoiceMessage(
  sessionId: string,
  audio: Blob,
  language: string,
  live = false,
  endOfSpeechUnixMs?: number,
): Promise<VoiceChatResponse | VoiceLiveResponse> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 90000);
  const form = new FormData();
  form.append("session_id", sessionId);
  form.append("language", language);
  form.append("live", String(live));
  if (endOfSpeechUnixMs !== undefined) form.append("client_end_of_speech_unix_ms", String(endOfSpeechUnixMs));
  form.append("audio", audio, `voice-message${audioExtensionForMime(audio.type)}`);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/voice/chat`, {
      method: "POST",
      body: form,
      headers: DESKTOP_RUNTIME?.apiToken
        ? { "X-NeuroAsist-Token": DESKTOP_RUNTIME.apiToken }
        : undefined,
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("Voice request timed out");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") {
        detail = payload.detail;
      }
    } catch {
      // Keep the status-only error.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<VoiceChatResponse | VoiceLiveResponse>;
}

export function getModels(): Promise<{ models: import("./types").ManagedModel[] }> {
  return requestJson("/models");
}

export function installModel(modelId: string): Promise<import("./types").ManagedModel> {
  return requestJson(`/models/${encodeURIComponent(modelId)}/install`, { method: "POST" });
}

export function removeModel(modelId: string): Promise<import("./types").ManagedModel> {
  return requestJson(`/models/${encodeURIComponent(modelId)}`, { method: "DELETE" });
}

export function getBackups(): Promise<Array<{ name: string; size_bytes: number; created_at: string }>> {
  return requestJson("/backups");
}

export function createBackup(): Promise<{ name: string; size_bytes: number; created_at: string }> {
  return requestJson("/backups", { method: "POST" });
}

export function getTimelineMessages(limit = 50): Promise<{ items: TimelineMessage[]; next_offset: number | null }> {
  return requestJson(`/timeline/messages?limit=${limit}`);
}

export function getTimelineJournal(): Promise<{ items: TimelineJournalItem[] }> {
  return requestJson("/timeline/journal");
}

export function searchTimeline(query: string): Promise<{ items: TimelineMessage[] }> {
  return requestJson(`/timeline/search?q=${encodeURIComponent(query)}`);
}

export function deleteTimelineRange(before: string): Promise<{ deleted: number }> {
  return requestJson(`/timeline/range?before=${encodeURIComponent(before)}`, { method: "DELETE" });
}

export function getMemories(status?: string, query?: string): Promise<{ items: MemoryItem[] }> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (query) params.set("q", query);
  return requestJson(`/memory${params.size ? `?${params}` : ""}`);
}

export function createMemory(payload: { predicate: string; value_text: string; source_message_ids: string[]; kind?: string }): Promise<{ memory: MemoryItem }> {
  return requestJson("/memory", { method: "POST", body: JSON.stringify(payload) });
}

export function updateMemory(memoryId: string, payload: { value_text?: string; user_locked?: boolean }): Promise<{ memory: MemoryItem }> {
  return requestJson(`/memory/${encodeURIComponent(memoryId)}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function confirmMemory(memoryId: string): Promise<{ memory: MemoryItem }> {
  return requestJson(`/memory/${encodeURIComponent(memoryId)}/confirm`, { method: "POST" });
}

export function rejectMemory(memoryId: string): Promise<{ memory: MemoryItem }> {
  return requestJson(`/memory/${encodeURIComponent(memoryId)}/reject`, { method: "POST" });
}

export function deleteMemory(memoryId: string): Promise<{ memory: MemoryItem }> {
  return requestJson(`/memory/${encodeURIComponent(memoryId)}`, { method: "DELETE" });
}

export function restoreMemory(memoryId: string): Promise<{ memory: MemoryItem }> {
  return requestJson(`/memory/${encodeURIComponent(memoryId)}/restore`, { method: "POST" });
}

export function getMemoryAudit(memoryId: string): Promise<{ items: MemoryAuditItem[] }> {
  return requestJson(`/memory/${encodeURIComponent(memoryId)}/audit`);
}

export function clearMemories(): Promise<{ deleted: number }> {
  return requestJson("/memory/clear", { method: "POST", body: JSON.stringify({}) });
}

export function resetAllCompanionData(): Promise<{ messages: number; memories: number; episodes: number; chroma_cleanup_pending?: number }> {
  return requestJson("/memory/reset-all", { method: "POST" });
}

export function reindexMemories(): Promise<{ indexed: number }> {
  return requestJson("/memory/reindex", { method: "POST" });
}

export function getAvatarStatus(): Promise<AvatarStatusResponse> {
  return requestJson<AvatarStatusResponse>("/avatar/status");
}

export function getAvatarOverlay(): Promise<AvatarOverlaySettings> {
  return requestJson<AvatarOverlaySettings>("/avatar/overlay");
}

export function updateAvatarOverlay(payload: Partial<AvatarOverlaySettings>): Promise<AvatarOverlaySettings> {
  return requestJson<AvatarOverlaySettings>("/avatar/overlay", { method: "PUT", body: JSON.stringify(payload) });
}

export function sendAvatarTestPhrase(payload: { text: string; emotion: string }): Promise<{ voice_request_id: string; status: string }> {
  return requestJson("/avatar/test/speak", { method: "POST", body: JSON.stringify(payload) });
}

export function sendAvatarTestEmotion(payload: { emotion: string; intensity: number }): Promise<{ sent: number; skipped: boolean }> {
  return requestJson("/avatar/test/emotion", { method: "POST", body: JSON.stringify(payload) });
}

export function sendAvatarTestGesture(payload: { gesture: string; intensity: number; interrupt?: boolean }): Promise<{ gesture: string; sent: number; skipped: boolean }> {
  return requestJson("/avatar/test/gesture", { method: "POST", body: JSON.stringify(payload) });
}

export function stopAvatar(): Promise<{ sent: number; skipped: boolean }> {
  return requestJson("/avatar/stop", { method: "POST", body: JSON.stringify({}) });
}

export function resolveApiUrl(path: string): string {
  return path.startsWith("http") ? path : `${API_BASE_URL}${path}`;
}
