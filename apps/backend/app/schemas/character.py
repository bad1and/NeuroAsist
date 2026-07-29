"""Canonical Character Protocol v3 models.

`CharacterTurn` is the one internal representation for both complete chat turns
and live-voice metadata.  Transport adapters may project it to legacy flat
fields, but must not invent a second set of emotion or gesture values.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


CHARACTER_PROTOCOL_VERSION = 3


class Emotion(str, Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    ANNOYED = "annoyed"
    SMIRK = "smirk"
    THINKING = "thinking"
    SURPRISED = "surprised"
    EMBARRASSED = "embarrassed"
    CONCERNED = "concerned"


class Intent(str, Enum):
    CASUAL_CHAT = "casual_chat"
    QUESTION = "question"
    TASK_REQUEST = "task_request"
    UNKNOWN = "unknown"


class Gesture(str, Enum):
    NONE = "none"
    AUTO = "auto"
    TALK = "talk"
    GREETING = "greeting"
    AGREEMENT = "agreement"
    DISAGREEMENT = "disagreement"
    QUESTION = "question"
    EXPLANATION = "explanation"
    THINKING = "thinking"
    SURPRISE = "surprise"
    FRUSTRATION = "frustration"
    FAREWELL = "farewell"
    SHRUG = "shrug"


class ProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AffectCue(ProtocolModel):
    emotion: Emotion = Emotion.NEUTRAL
    intensity: float = Field(default=1.0, ge=0.0, le=1.0)
    valence: float = Field(default=0.0, ge=-1.0, le=1.0)
    arousal: float = Field(default=0.0, ge=0.0, le=1.0)


class GestureCue(ProtocolModel):
    name: Gesture = Gesture.AUTO
    intensity: float = Field(default=1.0, ge=0.0, le=1.0)
    interrupt: bool = True


class DeliveryCue(ProtocolModel):
    pace: str = Field(default="normal", pattern="^(slow|normal|fast)$")
    emphasis: float = Field(default=0.0, ge=0.0, le=1.0)


class ContinuityCue(ProtocolModel):
    referenced_memory_ids: list[str] = Field(default_factory=list, max_length=12)
    referenced_episode_ids: list[str] = Field(default_factory=list, max_length=12)
    closes_open_loop_ids: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("referenced_memory_ids", "referenced_episode_ids", "closes_open_loop_ids")
    @classmethod
    def identifiers_must_not_be_blank(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("continuity identifiers must not be blank")
        return list(dict.fromkeys(cleaned))


class MemoryCandidate(ProtocolModel):
    """A proposed memory, never a direct command to mutate storage."""

    kind: str = Field(min_length=1, max_length=40)
    subject: str = Field(default="user", min_length=1, max_length=200)
    predicate: str = Field(min_length=1, max_length=200)
    value_text: str = Field(min_length=1, max_length=1000)
    importance: float = Field(default=0.6, ge=0.0, le=1.0)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    sensitivity: str = Field(default="normal", pattern="^(normal|sensitive)$")


class MemoryDecisionCue(ProtocolModel):
    """Optional model assessment; MemoryService remains the authority."""

    action: str = Field(pattern="^(accept|reject|clarify)$")
    reason: str = Field(min_length=1, max_length=120)
    predicate: str | None = Field(default=None, max_length=200)
    clarification_id: str | None = Field(default=None, max_length=64)


class CharacterTurn(ProtocolModel):
    """Canonical visible reply plus non-visible character metadata."""

    protocol_version: int = CHARACTER_PROTOCOL_VERSION
    reply: str = Field(min_length=1, max_length=8000)
    intent: Intent = Intent.UNKNOWN
    affect: AffectCue = Field(default_factory=AffectCue)
    gesture: GestureCue = Field(default_factory=GestureCue)
    delivery: DeliveryCue = Field(default_factory=DeliveryCue)
    continuity: ContinuityCue | None = None
    memory_candidates: list[MemoryCandidate] = Field(default_factory=list, max_length=3)
    memory_decisions: list[MemoryDecisionCue] = Field(default_factory=list, max_length=3)

    @field_validator("reply")
    @classmethod
    def reply_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reply must not be blank")
        return stripped

    def metadata_frame(self) -> dict[str, object]:
        """Return avatar metadata only; memory proposals are private to the backend."""
        return self.model_dump(
            mode="json",
            exclude={"reply", "memory_candidates", "memory_decisions"},
        )


class CharacterLLMResponse(ProtocolModel):
    """Legacy v1/v2 shape accepted at the model boundary during migration."""

    reply: str = Field(min_length=1)
    emotion: Emotion
    intent: Intent
    gesture: Gesture = Gesture.AUTO

    @field_validator("reply")
    @classmethod
    def reply_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reply must not be blank")
        return stripped
