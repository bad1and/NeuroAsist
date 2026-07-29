"""Public, deliberately qualitative contracts for Iris's dynamic state."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MoodPublicView(_PublicModel):
    primary_emotion: str = Field(max_length=32)
    expression_strength: str = Field(max_length=16)
    secondary_emotions: list[str] = Field(default_factory=list, max_length=2)


class RelationshipProfilePublicView(_PublicModel):
    familiarity_label: str = Field(max_length=32)
    trust_label: str = Field(max_length=32)
    warmth_label: str = Field(max_length=32)
    tension_label: str = Field(max_length=32)
    playfulness_label: str = Field(max_length=32)
    current_dynamic: str = Field(max_length=64)
    unresolved_cause: str | None = Field(default=None, max_length=160)


class EmotionCausePublicView(_PublicModel):
    label: str = Field(max_length=160)
    status: str = Field(max_length=16)


class CharacterStatePublicView(_PublicModel):
    mood: MoodPublicView
    relationship: RelationshipProfilePublicView
    causes: list[EmotionCausePublicView] = Field(default_factory=list, max_length=8)
    incognito: bool = False
    updated_at: str


class ReflectionSettingsView(_PublicModel):
    enabled: bool
    min_significance: float = Field(ge=.3, le=1.0)


class ReflectionPublicView(_PublicModel):
    id: str
    text: str = Field(max_length=600)
    trigger_kind: str = Field(max_length=64)
    trigger_label: str = Field(max_length=120)
    significance: float = Field(ge=0, le=1)
    primary_emotion: str = Field(max_length=32)
    created_at: str
