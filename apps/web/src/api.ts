import type {
  AvatarStatusResponse,
  AvatarOverlaySettings,
  AvatarPlacement,
  BackendEvent,
  ChatResponse,
  PublicSettings,
  StatusResponse,
  VoiceLiveResponse,
  VoiceTtsStatusResponse,
  TimelineJournalItem,
  TimelineMessage,
  MemoryAuditItem,
  MemoryItem,
  MemoryTopic,
  MemoryCommitment,
  ConversationDebug,
  CharacterStateView,
  CharacterStateEvent,
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

/** Avatar commands use their own bidirectional protocol, not the events feed. */
export function avatarWebSocketUrl(): string {
  const base = API_BASE_URL.replace(/^http/, "ws");
  const token = DESKTOP_RUNTIME?.apiToken;
  return `${base}/ws/avatar?version=2${token ? `&token=${encodeURIComponent(token)}` : ""}`;
}

export function voiceWebSocketUrl(sessionId: string): string {
  const base = API_BASE_URL.replace(/^http/, "ws");
  const token = DESKTOP_RUNTIME?.apiToken;
  return `${base}/ws/voice/${encodeURIComponent(sessionId)}?version=1${token ? `&token=${encodeURIComponent(token)}` : ""}`;
}

export function voiceInputWebSocketUrl(sessionId: string, version: 3 = 3): string {
  const base = API_BASE_URL.replace(/^http/, "ws");
  const token = DESKTOP_RUNTIME?.apiToken;
  return `${base}/ws/voice-input/${encodeURIComponent(sessionId)}?version=${version}${token ? `&token=${encodeURIComponent(token)}` : ""}`;
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

export function getConversationDebug(sessionId: string): Promise<ConversationDebug> {
  return requestJson<ConversationDebug>(
    `/conversation/debug/${encodeURIComponent(sessionId)}`,
  );
}

export function getCharacterState(): Promise<CharacterStateView> { return requestJson("/conversation/state"); }
export function getCharacterStateEvents(): Promise<{ events: CharacterStateEvent[] }> { return requestJson("/conversation/state/events"); }
export function resetCharacterState(scope: "mood" | "relationship"): Promise<CharacterStateView> { return requestJson("/conversation/state/reset", { method: "POST", body: JSON.stringify({ scope }) }); }
export function getCharacterReflections(): Promise<{ reflections: import("./types").CharacterReflection[] }> { return requestJson("/conversation/state/reflections"); }
export function deleteCharacterReflection(id: string): Promise<{ deleted: boolean }> { return requestJson(`/conversation/state/reflections/${encodeURIComponent(id)}`, { method: "DELETE" }); }
export type ReflectionSettings = { enabled: boolean; min_significance: number };
export function getReflectionSettings(): Promise<ReflectionSettings> { return requestJson("/conversation/state/reflections/settings"); }
export function updateReflectionSettings(payload: ReflectionSettings): Promise<ReflectionSettings> { return requestJson("/conversation/state/reflections/settings", { method: "PATCH", body: JSON.stringify(payload) }); }

export function resetConversationSession(): Promise<{ session_id: string; messages: number; episodes: number }> {
  return requestJson("/conversation/session/reset", { method: "POST" });
}

export function getConversationSession(): Promise<{ session_id: string; created: boolean }> {
  return requestJson("/conversation/session", { method: "POST" });
}

export function updateRuntimeSettings(payload: {
  personality?: string;
  interface_locale?: PublicSettings["interface_locale"];
  voice_language?: string;
  voice_microphone_profile?: PublicSettings["voice_microphone_profile"];
  voice_input_device_id?: string;
  voice_output_device_id?: string;
  voice_tts_voice?: string;
  voice_playback_rate?: number;
  voice_live_playback_prebuffer_segments?: number;
  voice_live_playback_prebuffer_ms?: number;
  memory_mode?: string;
  memory_incognito?: boolean;
  live_conversation_enabled?: boolean;
  live_conversation_participant_mode?: PublicSettings["live_conversation_participant_mode"];
  live_conversation_engagement?: PublicSettings["live_conversation_engagement"];
  live_conversation_initiative?: PublicSettings["live_conversation_initiative"];
  live_conversation_address_strictness?: PublicSettings["live_conversation_address_strictness"];
  live_conversation_interruption_sensitivity?: PublicSettings["live_conversation_interruption_sensitivity"];
  live_conversation_pause_tolerance?: PublicSettings["live_conversation_pause_tolerance"];
  live_conversation_emotion_expression?: PublicSettings["live_conversation_emotion_expression"];
  live_conversation_mood_recovery?: PublicSettings["live_conversation_mood_recovery"];
  live_conversation_recent_event_weight?: PublicSettings["live_conversation_recent_event_weight"];
  live_conversation_echo_mode?: PublicSettings["live_conversation_echo_mode"];
  avatar_placement?: AvatarPlacement;
  avatar_in_app_visible?: boolean;
}): Promise<PublicSettings> {
  return requestJson<PublicSettings>("/settings/runtime", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function updateVoiceStyle(voice_tts_style: string): Promise<PublicSettings> {
  return requestJson<PublicSettings>("/settings/voice-style", {
    method: "PATCH",
    body: JSON.stringify({ voice_tts_style }),
  });
}

export function updateVoiceExpression(voice_tts_expression_level: string): Promise<PublicSettings> {
  return requestJson<PublicSettings>("/settings/voice-expression", {
    method: "PATCH",
    body: JSON.stringify({ voice_tts_expression_level }),
  });
}

export function getPronunciations(): Promise<{ pronunciations: Record<string, string> }> {
  return requestJson("/settings/pronunciations");
}

export function updatePronunciations(pronunciations: Record<string, string>): Promise<{ pronunciations: Record<string, string> }> {
  return requestJson("/settings/pronunciations", {
    method: "PUT",
    body: JSON.stringify({ pronunciations }),
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
  clientMessageId?: string,
): Promise<ChatResponse> {
  return requestJson<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      message,
      client_message_id: clientMessageId,
    }),
  });
}

export function sendLiveTextMessage(
  sessionId: string,
  message: string,
  clientMessageId?: string,
): Promise<VoiceLiveResponse> {
  return requestJson<VoiceLiveResponse>("/chat/live", {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      message,
      client_message_id: clientMessageId,
    }),
  });
}

export function interruptVoiceSession(
  sessionId: string,
  utteranceId?: string,
): Promise<{ status: string }> {
  return requestJson<{ status: string }>("/voice/interrupt", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, utterance_id: utteranceId }),
  });
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

export function getTimelineMessages(
  limit = 50,
  sessionId?: string,
): Promise<{ items: TimelineMessage[]; next_offset: number | null }> {
  const session = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
  return requestJson(`/timeline/messages?limit=${limit}${session}`);
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

export function getSttTerms(): Promise<{ terms: Record<string, string[]> }> {
  return requestJson("/settings/stt-terms");
}

export function updateSttTerms(terms: Record<string, string[]>): Promise<{ terms: Record<string, string[]> }> {
  return requestJson("/settings/stt-terms", {
    method: "PUT",
    body: JSON.stringify({ terms }),
  });
}

export function getMemoryTopics(): Promise<{ items: MemoryTopic[] }> {
  return requestJson("/memory/topics");
}

export function getMemoryCommitments(status?: string): Promise<{ items: MemoryCommitment[] }> {
  return requestJson(`/memory/commitments${status ? `?status=${encodeURIComponent(status)}` : ""}`);
}

export function closeMemoryCommitment(id: string): Promise<{ commitment: MemoryCommitment }> {
  return requestJson(`/memory/commitments/${encodeURIComponent(id)}/close`, { method: "POST" });
}

export function getMemoryConflicts(): Promise<{ items: Array<{ id: string; reason: string; status: string }> }> {
  return requestJson("/memory/conflicts");
}

export function getMemoryDiagnostics(): Promise<import("./types").MemoryDiagnostics> {
  return requestJson("/memory/diagnostics");
}

export function getMemoryProfile(): Promise<{ facts: MemoryItem[]; topics: MemoryTopic[]; commitments: MemoryCommitment[] }> {
  return requestJson("/memory/profile");
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
