from pydantic import BaseModel, ConfigDict, Field


class PublicSettingsResponse(BaseModel):
    provider: str
    model: str
    personality: str
    voice_language: str
    voice_microphone_profile: str
    voice_input_device_id: str
    voice_output_device_id: str
    voice_vad: dict[str, object]
    voice_input_diagnostic_audio_enabled: bool
    voice_stt_model: str
    voice_tts_enabled: bool
    voice_tts_provider: str
    voice_tts_model: str | None = None
    voice_tts_device: str | None = None
    avatar_enabled: bool
    avatar_placement: str
    avatar_in_app_visible: bool
    voice_tts_voice: str
    voice_tts_style: str
    voice_tts_expression_level: str
    voice_playback_rate: float
    voice_live_playback_prebuffer_segments: int
    voice_live_playback_prebuffer_ms: int
    voice_live_playback_start_lead_ms: int
    chat_history_limit: int
    episodes_enabled: bool
    episode_soft_inactivity_minutes: int
    episode_hard_inactivity_minutes: int
    episode_maximum_messages: int
    episode_maximum_estimated_tokens: int
    memory_enabled: bool
    memory_mode: str
    memory_incognito: bool
    reflections_enabled: bool
    reflection_min_significance: float
    conversation_diagnostics_enabled: bool
    live_conversation_enabled: bool
    live_conversation_participant_mode: str
    live_conversation_engagement: str
    live_conversation_initiative: str
    live_conversation_address_strictness: str
    live_conversation_interruption_sensitivity: str
    live_conversation_pause_tolerance: str
    live_conversation_emotion_expression: str
    live_conversation_mood_recovery: str
    live_conversation_recent_event_weight: str
    live_conversation_echo_mode: str
    log_level: str
    api_key_configured: bool
    available_personalities: list[str]
    available_voice_languages: list[str]
    available_tts_voices: list[str]


class RuntimeSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personality: str | None = None
    voice_language: str | None = None
    voice_microphone_profile: str | None = None
    voice_input_device_id: str | None = Field(default=None, max_length=2048)
    voice_output_device_id: str | None = Field(default=None, max_length=2048)
    voice_tts_voice: str | None = None
    voice_playback_rate: float | None = None
    voice_live_playback_prebuffer_segments: int | None = None
    voice_live_playback_prebuffer_ms: int | None = None
    memory_mode: str | None = None
    memory_incognito: bool | None = None
    reflections_enabled: bool | None = None
    reflection_min_significance: float | None = None
    live_conversation_enabled: bool | None = None
    live_conversation_participant_mode: str | None = None
    live_conversation_engagement: str | None = None
    live_conversation_initiative: str | None = None
    live_conversation_address_strictness: str | None = None
    live_conversation_interruption_sensitivity: str | None = None
    live_conversation_pause_tolerance: str | None = None
    live_conversation_emotion_expression: str | None = None
    live_conversation_mood_recovery: str | None = None
    live_conversation_recent_event_weight: str | None = None
    live_conversation_echo_mode: str | None = None
    avatar_placement: str | None = None
    avatar_in_app_visible: bool | None = None


class VoiceStylePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_tts_style: str


class VoiceExpressionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_tts_expression_level: str


class PronunciationsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pronunciations: dict[str, str]


class SttTermsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terms: dict[str, list[str]]
