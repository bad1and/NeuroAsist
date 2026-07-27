from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConversationAction(StrEnum):
    WAIT_MORE = "wait_more"
    OBSERVE = "observe"
    AVATAR_REACTION = "avatar_reaction"
    BACKCHANNEL = "backchannel"
    RESPOND = "respond"
    DEFER = "defer"


class DecisionReason(StrEnum):
    INCOMPLETE_TURN = "incomplete_turn"
    DIRECT_ADDRESS = "direct_address"
    INVITED = "invited"
    AMBIENT_SPEECH = "ambient_speech"
    SELF_TALK = "self_talk"
    OTHER_PERSON = "other_person"
    RELEVANT_OPENING = "relevant_opening"
    EMOTIONAL_EVENT = "emotional_event"
    COOLDOWN = "cooldown"
    SPEECH_BUDGET = "speech_budget"
    ECHO = "echo"
    LOW_CONFIDENCE = "low_confidence"


class ConversationPhase(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    ENDPOINT_PENDING = "endpoint_pending"
    TRANSCRIBING = "transcribing"
    DECIDING = "deciding"
    GENERATING = "generating"
    SPEAKING = "speaking"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class SpeakerRole(StrEnum):
    PRIMARY = "primary"
    OTHER = "other"
    UNKNOWN = "unknown"
    ASSISTANT_ECHO = "assistant_echo"


class SpeakerRoleEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: SpeakerRole
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: list[
        Literal[
            "one_to_one_prior",
            "group_unknown_prior",
            "direct_address",
            "third_person_conversation",
            "recent_primary_continuity",
            "playback_similarity",
            "insufficient_evidence",
        ]
    ] = Field(default_factory=list, max_length=5)


class ConversationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    action: ConversationAction
    reason: DecisionReason
    confidence: float = Field(ge=0.0, le=1.0)
    addressedness: float = Field(ge=0.0, le=1.0)
    relevance: float = Field(ge=0.0, le=1.0)
    significance: float = Field(ge=0.0, le=1.0)
    reaction_emotion: str = "neutral"
    defer_for_ms: int | None = Field(default=None, ge=0)
    expires_in_ms: int | None = Field(default=None, ge=0)


class EventAppraisal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    event_kind: Literal[
        "support",
        "apology",
        "insult",
        "teasing",
        "interruption",
        "praise",
        "disagreement",
        "promise",
        "important_news",
        "neutral",
    ] = "neutral"
    target_participant: str = "primary"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    intensity: float = Field(default=0.0, ge=0.0, le=1.0)
    valence: float = Field(default=0.0, ge=-1.0, le=1.0)
    arousal: float = Field(default=0.0, ge=0.0, le=1.0)
    emotion_impulses: dict[str, float] = Field(default_factory=dict)
    relationship_impulses: dict[str, float] = Field(default_factory=dict)
    cause_message_ids: list[str] = Field(default_factory=list, max_length=5)


class ConversationAdjudicationV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    decision: ConversationDecision
    appraisal: EventAppraisal


class ConversationObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str
    session_id: str
    turn_id: str
    utterance_id: str
    generation: int = Field(ge=0)
    transcript: str
    corrected_content: str | None = None
    speaker_role: SpeakerRole = SpeakerRole.UNKNOWN
    speaker_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    addressedness: float = Field(default=0.0, ge=0.0, le=1.0)
    addressed_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    end_of_turn_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    significance: float = Field(default=0.0, ge=0.0, le=1.0)
    assistant_echo: bool = False
    stt_uncertain: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="milliseconds"))


class ConversationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    session_id: str
    generation: int
    turn_id: str
    utterance_id: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="milliseconds"))
    payload: dict[str, object] = Field(default_factory=dict)
