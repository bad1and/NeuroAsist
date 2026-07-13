from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


PROTOCOL_VERSION = 1
GESTURE_TAGS = frozenset({
    "none", "auto", "talk", "greeting", "agreement", "disagreement",
    "question", "explanation", "thinking", "surprise", "frustration",
    "farewell", "shrug",
})


def normalize_gesture(value: object) -> str:
    """Keep transport forwards-compatible: unsupported semantic tags become auto."""
    normalized = str(value or "auto").strip().lower()
    return normalized if normalized in GESTURE_TAGS else "auto"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Envelope(ProtocolModel):
    protocol_version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    type: str
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=utc_now)
    session_id: str = "default"


class SpeakPayload(ProtocolModel):
    utterance_id: str
    text: str = Field(min_length=1, max_length=8000)
    audio_url: str = Field(min_length=1, max_length=2048)
    emotion: str = "neutral"
    intent: str = "casual_chat"
    gesture: str = "auto"
    gesture_intensity: float = Field(default=1.0, ge=0.0, le=1.0)
    interrupt: bool = True

    _normalize_gesture = field_validator("gesture", mode="before")(normalize_gesture)


class EmotionPayload(ProtocolModel):
    emotion: str
    intensity: float = Field(default=1.0, ge=0.0, le=1.0)


class StopPayload(ProtocolModel):
    utterance_id: str | None = None


class GesturePayload(ProtocolModel):
    gesture: str = "auto"
    intensity: float = Field(default=1.0, ge=0.0, le=1.0)
    interrupt: bool = True

    _normalize_gesture = field_validator("gesture", mode="before")(normalize_gesture)


class StatePayload(ProtocolModel):
    state: str


class PingPayload(ProtocolModel):
    sent_at: datetime = Field(default_factory=utc_now)


class ErrorPayload(ProtocolModel):
    code: str
    message: str


class OutgoingMessage(Envelope):
    payload: dict[str, Any]


class HelloPayload(ProtocolModel):
    client_name: str = Field(min_length=1, max_length=256)
    client_version: str = Field(min_length=1, max_length=64)
    supported_protocol_versions: list[int] = Field(min_length=1, max_length=10)
    platform: str | None = Field(default=None, max_length=128)


class PongPayload(ProtocolModel):
    reply_to: str | None = None


class AckPayload(ProtocolModel):
    reply_to: str
    accepted: bool
    error: str | None = Field(default=None, max_length=512)


class PlaybackPayload(ProtocolModel):
    utterance_id: str
    reply_to: str | None = None
    reason: str | None = Field(default=None, max_length=512)


class ClientStatePayload(ProtocolModel):
    state: str = Field(min_length=1, max_length=64)


class MotionProfilePayload(ProtocolModel):
    profile: str = Field(min_length=1, max_length=64)


class IncomingMessage(Envelope):
    payload: dict[str, Any]


class AvatarStatusClient(ProtocolModel):
    client_id: str
    connected_at: datetime
    last_heartbeat_at: datetime
    client_name: str | None = None
    client_version: str | None = None
    platform: str | None = None
    state: str = "Idle"
    current_utterance_id: str | None = None
    current_motion_profile: str | None = None
    current_gesture: str | None = None


class AvatarStatusResponse(ProtocolModel):
    enabled: bool
    protocol_version: int = PROTOCOL_VERSION
    broadcast_policy: str = "all_connected_clients"
    client_count: int
    clients: list[AvatarStatusClient]


class AvatarTestSpeakRequest(ProtocolModel):
    text: str = Field(min_length=1, max_length=1200)
    emotion: str = "neutral"
    intent: str = "test"
    gesture: str = "auto"
    gesture_intensity: float = Field(default=1.0, ge=0.0, le=1.0)
    session_id: str = "default"
    interrupt: bool = True

    _normalize_gesture = field_validator("gesture", mode="before")(normalize_gesture)


class AvatarTestEmotionRequest(ProtocolModel):
    emotion: str = Field(min_length=1, max_length=64)
    intensity: float = Field(default=1.0, ge=0.0, le=1.0)
    session_id: str = "default"


class AvatarTestGestureRequest(GesturePayload):
    session_id: str = "default"


class AvatarStopRequest(ProtocolModel):
    utterance_id: str | None = None
    session_id: str = "default"
