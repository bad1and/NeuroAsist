from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


MemoryScope = Literal["user_profile", "relationship", "episode", "character"]
MemoryKind = Literal[
    "identity", "preference", "relationship", "goal", "constraint", "skill", "interest",
    "episode", "decision", "correction", "open_loop", "shared_milestone",
]
MemoryStatus = Literal["active", "superseded", "rejected", "deleted", "expired"]


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


class MemoryMerge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    survivor_id: str = Field(min_length=1)
    merged_id: str = Field(min_length=1)


class TopicCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    summary_text: str = Field(default="", max_length=2000)


class TopicPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary_text: str | None = Field(default=None, max_length=2000)
    status: Literal["active", "merged", "superseded", "archived"] | None = None
    user_locked: bool | None = None


class CommitmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["milestone", "promise", "decision", "open_loop"] = "open_loop"
    title: str = Field(min_length=1, max_length=500)
    details: str = Field(default="", max_length=2000)
    status: Literal["open", "completed", "cancelled"] = "open"
    importance: float = Field(default=.6, ge=0, le=1)
    confidence: float = Field(default=.7, ge=0, le=1)


class CommitmentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=500)
    details: str | None = Field(default=None, max_length=2000)
    status: Literal["open", "completed", "cancelled"] | None = None
    importance: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    user_locked: bool | None = None
