"""Strict structured contracts for background memory consolidation.

The model is allowed to propose records only.  ``MemoryService`` remains the
policy gate which validates provenance, locks and cardinality before writing.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FactProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=64)
    subject: str = Field(default="user", min_length=1, max_length=200)
    predicate: str = Field(min_length=1, max_length=200)
    value_text: str = Field(min_length=1, max_length=2000)
    importance: float = Field(default=0.6, ge=0, le=1)
    confidence: float = Field(default=0.7, ge=0, le=1)
    sensitivity: Literal["normal", "sensitive"] = "normal"
    source_message_ids: list[str] = Field(default_factory=list, max_length=20)
    cardinality: Literal["single", "multi"] = "multi"
    temporal_semantics: Literal["atemporal", "current", "period"] = "atemporal"


class TopicProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    summary_text: str = Field(default="", max_length=2000)
    topic_id: str | None = None
    source_message_ids: list[str] = Field(default_factory=list, max_length=20)


class CommitmentProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["milestone", "promise", "decision", "open_loop"] = "open_loop"
    title: str = Field(min_length=1, max_length=500)
    details: str = Field(default="", max_length=2000)
    status: Literal["open", "completed", "cancelled"] = "open"
    importance: float = Field(default=0.6, ge=0, le=1)
    confidence: float = Field(default=0.7, ge=0, le=1)
    source_message_ids: list[str] = Field(default_factory=list, max_length=20)


class ConflictProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    existing_id: str | None = None
    proposed_kind: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=1000)
    resolution: Literal["supersede", "review", "coexist"] = "review"


class MemoryDecisionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["accept", "reject", "clarify"]
    reason: str = Field(min_length=1, max_length=200)
    predicate: str | None = Field(default=None, max_length=200)
    clarification_id: str | None = Field(default=None, max_length=64)


class ConsolidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[FactProposal] = Field(default_factory=list, max_length=30)
    topics: list[TopicProposal] = Field(default_factory=list, max_length=12)
    commitments: list[CommitmentProposal] = Field(default_factory=list, max_length=20)
    conflicts: list[ConflictProposal] = Field(default_factory=list, max_length=20)
    decisions: list[MemoryDecisionProposal] = Field(default_factory=list, max_length=30)
