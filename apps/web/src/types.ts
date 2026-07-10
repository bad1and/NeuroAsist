export type EventLevel = "debug" | "info" | "warning" | "error" | "critical";

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

export type PublicSettings = {
  provider: string;
  model: string;
  personality: string;
  voice_language: string;
  voice_stt_model: string;
  voice_tts_enabled: boolean;
  voice_tts_voice: string;
  chat_history_limit: number;
  log_level: string;
  api_key_configured: boolean;
  available_models: string[];
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
  ttsStatus?: VoiceTtsStatus;
  ttsError?: string;
};
