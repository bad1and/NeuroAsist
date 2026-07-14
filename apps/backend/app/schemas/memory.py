from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


MemoryScope = Literal["user_profile", "relationship", "episode", "character"]
MemoryKind = Literal[
    "identity", "preference", "relationship", "goal", "constraint", "skill", "interest",
    "episode", "decision", "correction", "open_loop", "shared_milestone",
]
MemoryStatus = Literal["candidate", "active", "superseded", "rejected", "deleted", "expired"]


class MemoryCreate(BaseModel):
    scope: MemoryScope = "user_profile"
    kind: MemoryKind = "preference"
    subject: str = Field(default="user", min_length=1, max_length=200)
    predicate: str = Field(min_length=1, max_length=200)
    value_text: str = Field(min_length=1, max_length=2000)
    importance: float = Field(default=0.6, ge=0, le=1)
    confidence: float = Field(default=1, ge=0, le=1)
    sensitivity: Literal["normal", "sensitive"] = "normal"
    source_message_ids: list[str] = Field(default_factory=list, max_length=20)


class MemoryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value_text: str | None = Field(default=None, min_length=1, max_length=2000)
    importance: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    user_locked: bool | None = None
    expires_at: str | None = None


class MemoryClear(BaseModel):
    status: MemoryStatus | None = None
