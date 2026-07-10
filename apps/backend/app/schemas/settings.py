from pydantic import BaseModel


class PublicSettingsResponse(BaseModel):
    provider: str
    model: str
    personality: str
    voice_language: str
    voice_stt_model: str
    voice_tts_enabled: bool
    voice_tts_voice: str
    chat_history_limit: int
    log_level: str
    api_key_configured: bool
    available_models: list[str]
    available_personalities: list[str]
    available_voice_languages: list[str]
    available_tts_voices: list[str]


class RuntimeSettingsPatch(BaseModel):
    model: str | None = None
    personality: str | None = None
    voice_language: str | None = None
    voice_tts_voice: str | None = None
