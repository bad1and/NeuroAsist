import type { CharacterMetadataFrame, Emotion } from "./generated/character-protocol";

export type EventLevel = "debug" | "info" | "warning" | "error" | "critical";
export type {
  AffectCue,
  CharacterMetadataFrame,
  CharacterTurn,
  ContinuityCue,
  DeliveryCue,
  Emotion,
  Gesture,
  GestureCue,
  Intent,
} from "./generated/character-protocol";

export type BackendEvent = {
  id: string;
  type: string;
  level: EventLevel;
  message: string;
  created_at: string;
  metadata: Record<string, unknown>;
};

export type ChatResponse = {
  reply: string;
  emotion: string;
  intent: string;
  voice_request_id?: string | null;
  reply_audio_url?: string | null;
  tts_status?: VoiceTtsStatus | null;
};

export type VoiceTtsStatus =
  | "queued"
  | "ready"
  | "failed"
  | "browser_fallback"
  | "disabled"
  | "skipped";

export type VoiceChatResponse = ChatResponse & {
  voice_request_id: string;
  transcript: string;
  reply_audio_url?: string | null;
  tts_status: VoiceTtsStatus;
  stt: {
    provider: string;
    model?: string | null;
    language?: string | null;
    duration_ms: number;
  };
  tts: {
    provider: string;
    voice?: string | null;
    duration_ms: number;
  };
};

export type VoiceLiveResponse = {
  session_id: string;
  utterance_id: string;
  voice_request_id: string;
  transcript: string;
  status: "streaming";
};

export type VoiceServerEvent = {
  version: 1;
  type: string;
  session_id: string;
  utterance_id: string;
  segment_id?: number;
  format?: string;
  sample_rate?: number;
  channels?: number;
  delta?: string;
  reply?: string;
  emotion?: string;
  intent?: string;
  gesture?: string;
  gesture_intensity?: number;
  metadata?: CharacterMetadataFrame;
  code?: string;
  message?: string;
};

export type VoiceTtsStatusResponse = {
  voice_request_id: string;
  status: VoiceTtsStatus;
  audio_url?: string | null;
  voice?: string | null;
  duration_ms?: number | null;
  chunks_count?: number | null;
  audio_duration_seconds?: number | null;
  error?: string | null;
  error_type?: string | null;
  recoverable?: boolean | null;
  fallback?: string | null;
};

export type StatusResponse = {
  app_name: string;
  version: string;
  backend: string;
  llm_provider: string;
  llm_model: string;
  api_key_configured: boolean;
  database: string;
};

export type AvatarClientStatus = {
  client_id: string;
  connected_at: string;
  last_heartbeat_at: string;
  client_name?: string | null;
  client_version?: string | null;
  platform?: string | null;
  state: string;
  current_utterance_id?: string | null;
  current_motion_profile?: string | null;
  current_gesture?: string | null;
};

export type AvatarStatusResponse = {
  enabled: boolean;
  protocol_version: number;
  broadcast_policy: string;
  client_count: number;
  clients: AvatarClientStatus[];
  emotion_engine: {
    mapping_valid: boolean;
    mapping_error?: string | null;
    current_emotion: Emotion;
    target_emotion: Emotion;
    intensity: number;
    gesture: string;
    motion_profile: string;
    attack_ms: number;
    minimum_hold_ms: number;
    release_ms: number;
    source_utterance_id?: string | null;
    generation: number;
    speaking: boolean;
  };
};

export type PublicSettings = {
  provider: string;
  model: string;
  personality: string;
  voice_language: string;
  voice_stt_model: string;
  voice_tts_enabled: boolean;
  avatar_enabled: boolean;
  voice_tts_voice: string;
  voice_playback_rate: number;
  voice_live_playback_prebuffer_segments: number;
  voice_live_playback_prebuffer_ms: number;
  chat_history_limit: number;
  episodes_enabled: boolean;
  episode_soft_inactivity_minutes: number;
  episode_hard_inactivity_minutes: number;
  episode_maximum_messages: number;
  episode_maximum_estimated_tokens: number;
  memory_enabled: boolean;
  memory_mode: string;
  memory_incognito: boolean;
  log_level: string;
  api_key_configured: boolean;
  available_personalities: string[];
  available_voice_languages: string[];
  available_tts_voices: string[];
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  emotion?: string;
  intent?: string;
  audioUrl?: string;
  voiceRequestId?: string;
  utteranceId?: string;
  ttsStatus?: VoiceTtsStatus;
  ttsError?: string;
};

export type TimelineMessage = {
  id: string;
  role: "user" | "assistant" | "system_event";
  content: string;
  original_content: string;
  corrected_content?: string | null;
  status: string;
  input_mode: "voice" | "text" | "system";
  created_at: string;
};

export type TimelineJournalItem = {
  id?: string;
  day: string;
  message_count: number;
  started_at: string;
  last_activity_at: string;
  ended_at?: string | null;
  status?: string;
  boundary_reason?: string | null;
  title?: string | null;
};

export type MemoryStatus = "candidate" | "active" | "superseded" | "rejected" | "deleted" | "expired";

export type MemoryItem = {
  id: string;
  scope: string;
  kind: string;
  subject: string;
  predicate: string;
  value_text: string;
  importance: number;
  confidence: number;
  sensitivity: "normal" | "sensitive";
  status: MemoryStatus;
  user_locked: boolean;
  source_episode_id?: string | null;
  source_message_ids: string[];
  created_at: string;
  updated_at: string;
  last_accessed_at?: string | null;
  access_count: number;
};

export type MemoryAuditItem = {
  id: string;
  action: string;
  actor: string;
  reason?: string | null;
  source_message_ids: string[];
  created_at: string;
};
