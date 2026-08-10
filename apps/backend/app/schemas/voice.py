from pydantic import BaseModel, Field


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
    raw_transcript: str | None = None
    corrections: list[dict[str, object]] = Field(default_factory=list)
    message_id: str | None = None
    turn_id: str | None = None
    status: str = "streaming"


class VoiceInterruptRequest(BaseModel):
    session_id: str = Field(default="default", min_length=1, max_length=200)
    utterance_id: str | None = Field(default=None, max_length=200)
