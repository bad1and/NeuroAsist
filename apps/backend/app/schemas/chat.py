from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(default="default", min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=8000)
    client_message_id: str | None = Field(default=None, min_length=1, max_length=200)


class ChatResponse(BaseModel):
    reply: str
    emotion: str = "neutral"
    intent: str = "casual_chat"
    voice_request_id: str | None = None
    reply_audio_url: str | None = None
    tts_status: str | None = None
    memory_updates: list[dict[str, str]] = Field(default_factory=list)
    message_id: str | None = None
    assistant_message_id: str | None = None
    turn_id: str | None = None
    generation: int | None = None
