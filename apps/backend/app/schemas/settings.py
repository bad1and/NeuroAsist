from pydantic import BaseModel, ConfigDict


class PublicSettingsResponse(BaseModel):
    provider: str
    model: str
    personality: str
    voice_language: str
    voice_stt_model: str
    voice_tts_enabled: bool
    voice_tts_voice: str
    voice_playback_rate: float
    voice_live_playback_prebuffer_segments: int
    voice_live_playback_prebuffer_ms: int
    chat_history_limit: int
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
