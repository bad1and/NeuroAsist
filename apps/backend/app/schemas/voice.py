from pydantic import BaseModel, Field


class VoiceProviderStats(BaseModel):
    provider: str
    model: str | None = None
    language: str | None = None
    voice: str | None = None
    duration_ms: int


class VoiceChatResponse(BaseModel):
    voice_request_id: str
    transcript: str
    reply: str
    emotion: str = "neutral"
    intent: str = "casual_chat"
    reply_audio_url: str | None = None
    tts_status: str = "queued"
    stt: VoiceProviderStats
    tts: VoiceProviderStats
    memory_updates: list[dict[str, str]] = []


class VoiceTTSStatusResponse(BaseModel):
    voice_request_id: str
    status: str
    audio_url: str | None = None
    voice: str | None = None
    duration_ms: int | None = None
    chunks_count: int | None = None
    audio_duration_seconds: float | None = None
    error: str | None = None
    error_type: str | None = None
    recoverable: bool | None = None
    fallback: str | None = None


class VoiceLiveResponse(BaseModel):
    session_id: str
    utterance_id: str
    voice_request_id: str
    transcript: str
    status: str = "streaming"


class VoiceInterruptRequest(BaseModel):
    session_id: str = Field(default="default", min_length=1, max_length=200)
    utterance_id: str | None = Field(default=None, max_length=200)
