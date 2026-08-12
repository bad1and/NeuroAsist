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
  memory_updates?: MemoryUpdate[];
  message_id?: string | null;
  assistant_message_id?: string | null;
  turn_id?: string | null;
  generation?: number | null;
};

export type MemoryUpdate = {
  id: string;
  status: MemoryStatus;
  action: "saved" | "updated";
  predicate: string;
};

export type VoiceTtsStatus =
  | "queued"
  | "ready"
  | "failed"
  | "browser_fallback"
  | "disabled"
  | "skipped";

export type VoiceLiveResponse = {
  session_id: string;
  utterance_id: string;
  voice_request_id: string;
  transcript: string;
  raw_transcript?: string | null;
  corrections?: Array<{ source: string; target: string; start: number; end: number }>;
  message_id?: string | null;
  turn_id?: string | null;
  status: "streaming" | "completed" | "interrupted" | "failed";
};

export type CharacterStateView = {
  mood: { primary_emotion: string; expression_strength: string; secondary_emotions: string[] };
  relationship: Record<string, unknown>;
  causes: Array<{ label: string; status: string }>;
  incognito: boolean;
  updated_at: string;
};

export type CharacterStateEvent = { id: string; event_kind: string; created_at: string; confidence: number; intensity: number; delta: Record<string, unknown> };

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
  text?: string;
  pace?: "slow" | "normal" | "fast";
  tempo?: number;
  emphasis?: "none" | "light";
  pause_after_ms?: number;
  provider?: string;
  generation?: number;
  memory_updates?: MemoryUpdate[];
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

export type AvatarOverlaySettings = {
  visible: boolean;
  always_on_top: boolean;
  locked: boolean;
  scale: number;
  monitor: string;
  x: number;
  y: number;
  width: number;
  height: number;
};

export type AvatarPlacement = "desktop_overlay" | "in_app";
export type InterfaceLocale = "ru" | "en";

export type PublicSettings = {
  provider: string;
  model: string;
  personality: string;
  interface_locale: InterfaceLocale;
  voice_language: string;
  voice_microphone_profile: "headset" | "balanced" | "speakers";
  voice_input_device_id: string;
  voice_output_device_id: string;
  voice_vad: {
    configured_provider: string;
    active_provider: string;
    ready: boolean;
    fallback: boolean;
    fallback_reason?: string | null;
    sample_rate?: number;
    window_samples?: number | null;
    model?: string | null;
    version?: string | null;
  };
  voice_input_diagnostic_audio_enabled: boolean;
  voice_stt_model: string;
  voice_tts_enabled: boolean;
  voice_tts_provider: string;
  voice_tts_model: string | null;
  voice_tts_device: string | null;
  avatar_enabled: boolean;
  avatar_placement: AvatarPlacement;
  avatar_in_app_visible: boolean;
  voice_tts_voice: string;
  voice_tts_style: string;
  voice_tts_expression_level: string;
  voice_playback_rate: number;
  voice_live_playback_prebuffer_segments: number;
  voice_live_playback_prebuffer_ms: number;
  voice_live_playback_start_lead_ms: number;
  chat_history_limit: number;
  episodes_enabled: boolean;
  episode_soft_inactivity_minutes: number;
  episode_hard_inactivity_minutes: number;
  episode_maximum_messages: number;
  episode_maximum_estimated_tokens: number;
  memory_enabled: boolean;
  memory_mode: string;
  memory_incognito: boolean;
  conversation_diagnostics_enabled: boolean;
  live_conversation_enabled: boolean;
  live_conversation_participant_mode: "one_to_one" | "group";
  live_conversation_engagement: "low" | "balanced" | "high";
  live_conversation_initiative: "off" | "rare" | "balanced";
  live_conversation_address_strictness: "relaxed" | "balanced" | "strict";
  live_conversation_interruption_sensitivity: "low" | "balanced" | "high";
  live_conversation_pause_tolerance: "short" | "natural" | "patient";
  live_conversation_emotion_expression: "subtle" | "natural" | "strong";
  live_conversation_mood_recovery: "slow" | "natural" | "fast";
  live_conversation_recent_event_weight: "light" | "balanced" | "strong";
  live_conversation_echo_mode: "auto" | "half_duplex";
  log_level: string;
  api_key_configured: boolean;
  coding_api_key_configured: boolean;
  coding_agent_enabled: boolean;
  coding_model: "deepseek-v4-flash" | "deepseek-v4-pro";
  coding_project_root: string;
  coding_workspace_name: string;
  coding_auto_delegate: boolean;
  coding_available_models: Array<"deepseek-v4-flash" | "deepseek-v4-pro">;
  coding_allowed_project_roots: string[];
  available_personalities: string[];
  available_voice_languages: string[];
  available_tts_voices: string[];
};

export type CodingTaskStatus =
  | "pending"
  | "running"
  | "waiting_for_input"
  | "review_ready"
  | "failed"
  | "cancelled"
  | "applied"
  | "conflicted";

export type CodingTaskEvent = {
  id: number;
  task_id: string;
  type: string;
  level: EventLevel;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type CodingTask = {
  id: string;
  objective: string;
  model: string;
  project_root: string;
  workspace_name: string;
  status: CodingTaskStatus;
  cancellation_requested: boolean;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  workspace_path?: string | null;
  context_files: string[];
  base_manifest: Record<string, unknown>;
  result: Record<string, unknown>;
  patch_text?: string | null;
  error_text?: string | null;
  events: CodingTaskEvent[];
  instructions: Array<{ id: number; text: string; status: string; created_at: string; consumed_at?: string | null }>;
};

export type CodingStatus = {
  enabled: boolean;
  configured_enabled: boolean;
  available: boolean;
  availability_reason?: string | null;
  model: string;
  available_models: string[];
  project_root: string;
  allowed_project_roots: string[];
  workspace_name: string;
  workspace_root: string;
  auto_delegate: boolean;
  active_task_id?: string | null;
  active_task_status?: CodingTaskStatus | null;
  queued_count: number;
};

export type ManagedModel = {
  id: string;
  name: string;
  version: string;
  installed: boolean;
  size_bytes: number;
  location?: string | null;
  sha256: string;
  restart_required: boolean;
  status: "not_installed" | "downloading" | "installed" | "failed";
  downloaded_bytes: number;
  total_bytes: number;
  error?: string | null;
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
  speakerLabel?: string;
};

export type ConversationDebug = {
  phase: string;
  generation: number;
  last_decision_source?: string;
  last_speaker_estimate?: {
    role: string;
    confidence: number;
    reasons: string[];
  } | null;
  last_decision?: {
    action: string;
    reason: string;
    confidence: number;
  } | null;
  speech_budget?: {
    initiative_count_10m: number;
    iris_share_2m: number;
    cooldown_active: boolean;
    budget_exceeded: boolean;
  };
  deferred_reactions?: Array<{ id: string; topic_key: string; attempts: number }>;
  active_tasks?: Array<{ name: string; generation: number; reason: string }>;
  turn_detector?: {
    provider: string;
    ready: boolean;
    fallback: boolean;
    error?: string | null;
  };
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

export type MemoryStatus = "active" | "superseded" | "rejected" | "deleted" | "expired";

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
  source_count?: number;
  replacement?: {
    id: string;
    predicate: string;
    value_text: string;
    status: MemoryStatus;
  } | null;
  created_at: string;
  updated_at: string;
  last_accessed_at?: string | null;
  access_count: number;
  slot_key?: string | null;
  object_key?: string | null;
  normalization_version?: number | null;
};

export type MemoryAuditItem = {
  id: string;
  action: string;
  actor: string;
  reason?: string | null;
  source_message_ids: string[];
  created_at: string;
};

export type MemoryTopic = {
  id: string;
  title: string;
  summary_text: string;
  status: string;
  user_locked: boolean;
  links: Array<{ entity_type: string; entity_id: string }>;
  evidence: Array<{ message_id?: string | null; source_role: string; source_quality: number }>;
};

export type MemoryCommitment = {
  id: string;
  kind: string;
  title: string;
  details: string;
  status: "open" | "completed" | "cancelled";
  importance: number;
  confidence: number;
  user_locked: boolean;
};

export type CharacterReflection = {
  id: string;
  text: string;
  trigger_kind: string;
  trigger_label: string;
  significance: number;
  primary_emotion: string;
  created_at: string;
};

export type MemoryDiagnosticRun = {
  id: string;
  type: string;
  status: string;
  attempts: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  result: {
    outcome?: "applied" | "partial" | "no_candidates" | "invalid_output" | "failed";
    proposed?: number;
    saved?: number;
    discarded?: number;
    counts?: Record<string, number>;
  };
  diagnostics: {
    model?: string;
    pipeline_version?: string;
    error_codes?: string[];
  };
};

export type MemoryDiagnostics = {
  queue: Record<string, number>;
  runs: MemoryDiagnosticRun[];
  active_by_namespace?: Record<string, number>;
  repair?: {
    repair_key: string;
    status: string;
    created_at: string;
    completed_at?: string | null;
    result: Record<string, number | boolean | string>;
  } | null;
  integrity?: {
    state: "healthy" | "degraded";
    active_conflicts: number;
    noncanonical_active: number;
    provenance_missing: number;
    source_count_mismatches: number;
    candidate_count?: number;
    guards_installed: boolean;
  };
  autonomy?: {
    candidate_count: number;
    open_clarifications: number;
    clarifications: Record<string, number>;
    decisions: Record<string, number>;
  };
  index_health?: {
    state: "healthy" | "degraded" | "rebuilding";
    semantic_enabled: boolean;
    degraded_reason?: string | null;
    missing_ids: string[];
    stale_ids: string[];
    namespaces: Record<string, {
      count?: number;
      source_count: number;
      fingerprint?: string;
      source_fingerprint: string;
      last_successful_sync?: string | null;
      error?: string;
    }>;
  };
};
