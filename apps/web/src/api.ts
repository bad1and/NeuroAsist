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
  ConversationUsage,
  CharacterStateView,
  CharacterStateEvent,
  CodingStatus,
  CodingTask,
  ReadinessResponse,
  TokenUsageStats,
  TokenRecordsResponse,
  MemeCard,
  IrisOpinion,
  OpinionRevision,
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

export function saveDesktopCodingApiKey(apiKey: string): Promise<unknown> {
  return invokeDesktop("save_coding_api_key", { apiKey });
}

export function removeDesktopApiKey(): Promise<unknown> {
  return invokeDesktop("remove_api_key");
}

export function removeDesktopCodingApiKey(): Promise<unknown> {
  return invokeDesktop("remove_coding_api_key");
}

export type SearchApiProvider = "brave" | "tavily" | "serper";

export function saveDesktopSearchApiKey(provider: SearchApiProvider, apiKey: string): Promise<unknown> {
  return invokeDesktop("save_search_api_key", { provider, apiKey });
}

export function removeDesktopSearchApiKey(provider: SearchApiProvider): Promise<unknown> {
  return invokeDesktop("remove_search_api_key", { provider });
}

export function checkSearchProvider(provider: SearchApiProvider): Promise<{ provider: string; status: string; results_count?: number; quota?: { used?: number; limit?: number } | null }> {
  return requestJson("/environment/search/check", { method: "POST", body: JSON.stringify({ provider }) });
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

export async function requestJson<T>(
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

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function getStatus(): Promise<StatusResponse> {
  return requestJson<StatusResponse>("/status");
}

export function getReadiness(): Promise<ReadinessResponse> {
  return requestJson<ReadinessResponse>("/readiness");
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

export type ConversationBoundaryReason = "new_dialog" | "manual_reset";

export function resetConversationSession(
  boundaryReason: ConversationBoundaryReason = "new_dialog",
): Promise<{ session_id: string; messages: number; episodes: number }> {
  return requestJson("/conversation/session/reset", {
    method: "POST",
    body: JSON.stringify({ boundary_reason: boundaryReason }),
  });
}

export function getConversationSession(): Promise<{ session_id: string; created: boolean }> {
  return requestJson("/conversation/session", { method: "POST" });
}

export function updateRuntimeSettings(payload: {
  personality?: string;
  interface_locale?: PublicSettings["interface_locale"];
  background_conversation_notifications_enabled?: boolean;
  developer_mode_enabled?: boolean;
  voice_language?: string;
  voice_microphone_profile?: PublicSettings["voice_microphone_profile"];
  voice_input_device_id?: string;
  voice_output_device_id?: string;
  voice_tts_voice?: string;
  voice_tts_style?: string;
  voice_tts_expression_level?: string;
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
  avatar_in_app_quality?: PublicSettings["avatar_in_app_quality"];
  avatar_desktop_quality?: PublicSettings["avatar_desktop_quality"];
  coding_agent_enabled?: boolean;
  coding_model?: PublicSettings["coding_model"];
  coding_project_root?: string;
  coding_workspace_name?: string;
  coding_auto_delegate?: boolean;
  location_mode?: PublicSettings["location_mode"];
  location_city?: PublicSettings["location_city"];
  weather_enabled?: PublicSettings["weather_enabled"];
  news_enabled?: PublicSettings["news_enabled"];
  web_search_enabled?: PublicSettings["web_search_enabled"];
  web_search_notifications_enabled?: PublicSettings["web_search_notifications_enabled"];
  web_search_provider?: PublicSettings["web_search_provider"];
  news_category?: PublicSettings["news_category"];
}): Promise<PublicSettings> {
  return requestJson<PublicSettings>("/settings/runtime", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function getEnvironmentStatus(): Promise<import("./types").EnvironmentStatus> {
  return requestJson<import("./types").EnvironmentStatus>("/environment/status");
}

export function getCodingStatus(refresh = false): Promise<CodingStatus> {
  return requestJson(`/coding/status${refresh ? "?refresh=true" : ""}`);
}

export function getCodingTasks(limit = 100): Promise<CodingTask[]> {
  return requestJson(`/coding/tasks?limit=${limit}`);
}

export function clearCodingTasks(): Promise<{ removed_tasks: number; preserved_workspaces: boolean }> {
  return requestJson("/coding/tasks", { method: "DELETE" });
}

export function getCodingTask(taskId: string): Promise<CodingTask> {
  return requestJson(`/coding/tasks/${encodeURIComponent(taskId)}`);
}

export function createCodingTask(payload: { objective: string; session_id?: string; project_root?: string; context_files?: string[] }): Promise<CodingTask> {
  return requestJson("/coding/tasks", { method: "POST", body: JSON.stringify(payload) });
}

export function addCodingInstruction(taskId: string, text: string): Promise<CodingTask> {
  return requestJson(`/coding/tasks/${encodeURIComponent(taskId)}/instructions`, { method: "POST", body: JSON.stringify({ text }) });
}

export function cancelCodingTask(taskId: string): Promise<CodingTask> {
  return requestJson(`/coding/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" });
}

export function retryCodingTask(taskId: string): Promise<CodingTask> {
  return requestJson(`/coding/tasks/${encodeURIComponent(taskId)}/retry`, { method: "POST" });
}

export function applyCodingTask(taskId: string): Promise<CodingTask> {
  return requestJson(`/coding/tasks/${encodeURIComponent(taskId)}/apply`, { method: "POST" });
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

export function getModels(): Promise<{ models: import("./types").ManagedModel[]; directory?: string }> {
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
  episodeId?: string,
  offset = 0,
): Promise<{ items: TimelineMessage[]; next_offset: number | null }> {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  if (offset > 0) params.set("offset", String(offset));
  if (sessionId) params.set("session_id", sessionId);
  if (episodeId) params.set("episode_id", episodeId);
  return requestJson(`/timeline/messages?${params.toString()}`);
}

export function getTimelineJournal(): Promise<{ items: TimelineJournalItem[] }> {
  return requestJson("/timeline/journal");
}

export function getConversationUsage(): Promise<ConversationUsage> {
  return requestJson("/conversation/usage");
}

export function searchTimeline(query: string): Promise<{ items: TimelineMessage[] }> {
  return requestJson(`/timeline/search?q=${encodeURIComponent(query)}`);
}

export function deleteTimelineRange(before: string): Promise<{ deleted: number }> {
  return requestJson(`/timeline/range?before=${encodeURIComponent(before)}`, { method: "DELETE" });
}

export const cancelModel = (modelId: string) => requestJson(`/models/${encodeURIComponent(modelId)}/cancel`, { method: "POST" });
export const deleteBackup = (name: string) => requestJson(`/backups/${encodeURIComponent(name)}`, { method: "DELETE" });
export const registerCodingProject = (path: string) => requestJson<{ allowed_project_roots: string[] }>("/coding/projects", { method: "POST", body: JSON.stringify({ path }) });
export type CodingImageState = { status: string; output: string; error: string | null };
export const getCodingImage = () => requestJson<CodingImageState>("/coding/image");
export const prepareCodingImage = () => requestJson<CodingImageState>("/coding/image/prepare", { method: "POST" });
export const cancelCodingImage = () => requestJson<CodingImageState>("/coding/image/cancel", { method: "POST" });

export function deleteTimelineEpisode(episodeId: string): Promise<{ deleted_messages: number }> {
  return requestJson(`/episodes/${encodeURIComponent(episodeId)}`, { method: "DELETE" });
}

export function clearTimelineHistory(): Promise<{ deleted: number }> {
  return requestJson("/timeline/history", { method: "DELETE" });
}

export function getMemories(status?: string, query?: string, offset = 0): Promise<{ items: MemoryItem[]; next_offset?: number | null }> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (query) params.set("q", query);
  if (offset > 0) params.set("offset", String(offset));
  return requestJson(`/memory${params.size ? `?${params}` : ""}`);
}

export async function getVoicePreview(signal: AbortSignal): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/voice/preview`, { method: "POST", signal,
    headers: DESKTOP_RUNTIME?.apiToken ? { "X-NeuroAsist-Token": DESKTOP_RUNTIME.apiToken } : {} });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === "string" ? error.detail : "Проба голоса недоступна");
  }
  return response.blob();
}

export function getMemeLibrary(): Promise<{ items: MemeCard[]; limit: number }> {
  return requestJson("/meme-library");
}

export function getOpinions(): Promise<{ items: IrisOpinion[]; limit: number }> {
  return requestJson("/opinions");
}
export function getOpinionHistory(id: string): Promise<{ items: OpinionRevision[] }> {
  return requestJson(`/opinions/${encodeURIComponent(id)}/history`);
}
export function saveOpinion(fields: { topic: string; stance: string; reason: string; aliases: string[]; id: string | null; expected_revision: number }): Promise<{ item: IrisOpinion }> {
  return requestJson("/opinions", { method: "POST", body: JSON.stringify(fields) });
}
export function toggleOpinion(id: string, enabled: boolean, revision: number): Promise<{ updated: boolean }> {
  return requestJson(`/opinions/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ enabled, revision }) });
}

export function saveMemeCard(id: string | null, fields: Partial<Pick<MemeCard, "name" | "summary" | "tags" | "source" | "enabled">>): Promise<{ item: MemeCard }> {
  return requestJson(`/meme-library${id ? `/${encodeURIComponent(id)}` : ""}`, {
    method: id ? "PATCH" : "POST", body: JSON.stringify(fields),
  });
}

export function deleteMemeCard(id: string): Promise<{ deleted: boolean }> {
  return requestJson(`/meme-library/${encodeURIComponent(id)}`, { method: "DELETE" });
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

export function purgeMemory(memoryId: string): Promise<{ memory: { id: string; purged: boolean } }> {
  return requestJson(`/memory/${encodeURIComponent(memoryId)}/purge`, { method: "DELETE" });
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

export function getMemoryTopics(query?: string): Promise<{ items: MemoryTopic[] }> {
  return requestJson(`/memory/topics${query ? `?q=${encodeURIComponent(query)}` : ""}`);
}

export function getMemoryCommitments(status?: string, query?: string): Promise<{ items: MemoryCommitment[] }> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (query) params.set("q", query);
  return requestJson(`/memory/commitments${params.size ? `?${params}` : ""}`);
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

export function sendAvatarTestPhrase(payload: {
  text: string;
  emotion?: string;
  intent?: string;
  gesture?: string;
  gesture_intensity?: number;
  interrupt?: boolean;
}): Promise<{ voice_request_id: string; status: string }> {
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

export function getLlmTokenStats(timeframe: string = "24h"): Promise<TokenUsageStats> {
  return requestJson<TokenUsageStats>(`/debug/llm/stats?timeframe=${encodeURIComponent(timeframe)}`);
}

export function getLlmTokenRecords(
  limit: number = 50,
  offset: number = 0,
  purpose?: string,
): Promise<TokenRecordsResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (purpose) {
    params.set("purpose", purpose);
  }
  return requestJson<TokenRecordsResponse>(`/debug/llm/records?${params.toString()}`);
}

export function resetLlmTokenStats(): Promise<{ status: string; cleared_records: number }> {
  return requestJson<{ status: string; cleared_records: number }>("/debug/llm/reset", {
    method: "POST",
  });
}
