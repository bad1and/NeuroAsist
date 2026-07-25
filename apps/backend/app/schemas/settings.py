from pydantic import BaseModel, ConfigDict


class PublicSettingsResponse(BaseModel):
    provider: str
    model: str
    personality: str
    voice_language: str
    voice_stt_model: str
    voice_tts_enabled: bool
    voice_tts_provider: str
    voice_tts_model: str | None = None
    voice_tts_device: str | None = None
    avatar_enabled: bool
    voice_tts_voice: str
    voice_tts_style: str
    voice_tts_expression_level: str
    voice_playback_rate: float
    voice_live_playback_prebuffer_segments: int
    voice_live_playback_prebuffer_ms: int
    chat_history_limit: int
    episodes_enabled: bool
    episode_soft_inactivity_minutes: int
    episode_hard_inactivity_minutes: int
    episode_maximum_messages: int
    episode_maximum_estimated_tokens: int
    memory_enabled: bool
    memory_mode: str
    memory_incognito: bool
    log_level: str
    api_key_configured: bool
    available_personalities: list[str]
    available_voice_languages: list[str]
    available_tts_voices: list[str]


class RuntimeSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personality: str | None = None
    voice_language: str | None = None
    voice_tts_voice: str | None = None
    voice_playback_rate: float | None = None
    voice_live_playback_prebuffer_segments: int | None = None
    voice_live_playback_prebuffer_ms: int | None = None
    memory_mode: str | None = None
    memory_incognito: bool | None = None


class VoiceStylePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_tts_style: str


class VoiceExpressionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_tts_expression_level: str


class PronunciationsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pronunciations: dict[str, str]
