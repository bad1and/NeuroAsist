"""Deterministic emotion and gesture arbitration for the avatar renderer.

The engine intentionally does not animate pixels.  It owns the renderer-neutral
state that a Unity/VRM client needs to perform smooth transitions safely.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from apps.backend.app.schemas.character import Emotion, Gesture


class _MappingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmotionMapping(_MappingModel):
    expression: str = Field(min_length=1, max_length=80)
    weight: float = Field(ge=0.0, le=1.0)
    motion_profile: str = Field(min_length=1, max_length=80)
    allowed_gestures: list[Gesture] = Field(min_length=1)
    attack_ms: int = Field(default=180, ge=0, le=10_000)
    minimum_hold_ms: int = Field(default=450, ge=0, le=30_000)
    release_ms: int = Field(default=260, ge=0, le=10_000)


def _default_mapping() -> dict[Emotion, EmotionMapping]:
    expressive = [Gesture.AUTO, Gesture.TALK, Gesture.GREETING, Gesture.AGREEMENT]
    mapping: dict[Emotion, EmotionMapping] = {
        emotion: EmotionMapping(
            expression=emotion.value,
            weight=.7 if emotion is not Emotion.NEUTRAL else .35,
            motion_profile="idle" if emotion is Emotion.NEUTRAL else "conversational",
            allowed_gestures=expressive,
        )
        for emotion in Emotion
    }
    mapping[Emotion.THINKING] = mapping[Emotion.THINKING].model_copy(
        update={"motion_profile": "thoughtful", "allowed_gestures": [Gesture.AUTO, Gesture.THINKING, Gesture.QUESTION, Gesture.EXPLANATION]}
    )
    mapping[Emotion.ANGRY] = mapping[Emotion.ANGRY].model_copy(
        update={"motion_profile": "tense", "allowed_gestures": [Gesture.AUTO, Gesture.TALK, Gesture.FRUSTRATION, Gesture.DISAGREEMENT]}
    )
    mapping[Emotion.ANNOYED] = mapping[Emotion.ANNOYED].model_copy(
        update={"motion_profile": "tense", "allowed_gestures": [Gesture.AUTO, Gesture.TALK, Gesture.FRUSTRATION, Gesture.SHRUG]}
    )
    mapping[Emotion.SAD] = mapping[Emotion.SAD].model_copy(
        update={"motion_profile": "calm", "allowed_gestures": [Gesture.AUTO, Gesture.TALK, Gesture.SHRUG]}
    )
    mapping[Emotion.SMIRK] = mapping[Emotion.SMIRK].model_copy(
        update={"motion_profile": "playful", "allowed_gestures": [Gesture.AUTO, Gesture.TALK, Gesture.SHRUG]}
    )
    mapping[Emotion.SURPRISED] = mapping[Emotion.SURPRISED].model_copy(
        update={"motion_profile": "alert", "allowed_gestures": [Gesture.AUTO, Gesture.SURPRISE, Gesture.TALK]}
    )
    return mapping


@dataclass(frozen=True)
class EmotionState:
    current_emotion: Emotion
    target_emotion: Emotion
    intensity: float
    gesture: Gesture
    motion_profile: str
    attack_ms: int
    minimum_hold_ms: int
    release_ms: int
    source_utterance_id: str | None
    generation: int
    speaking: bool


class EmotionEngine:
    """State machine that rejects obsolete stop/gesture operations."""

    _GESTURE_PRIORITIES = {
        Gesture.AUTO: 0, Gesture.NONE: 0, Gesture.TALK: 1, Gesture.EXPLANATION: 2,
        Gesture.QUESTION: 2, Gesture.SHRUG: 2, Gesture.AGREEMENT: 2,
        Gesture.DISAGREEMENT: 2, Gesture.THINKING: 2, Gesture.GREETING: 3,
        Gesture.SURPRISE: 3, Gesture.FRUSTRATION: 3, Gesture.FAREWELL: 3,
    }

    def __init__(self, mapping: dict[Emotion, EmotionMapping] | None = None, *, mapping_valid: bool = True, mapping_error: str | None = None) -> None:
        self.mapping = mapping or _default_mapping()
        self.mapping_valid = mapping_valid
        self.mapping_error = mapping_error
        neutral = self.mapping[Emotion.NEUTRAL]
        self._state = EmotionState(
            current_emotion=Emotion.NEUTRAL, target_emotion=Emotion.NEUTRAL,
            intensity=neutral.weight, gesture=Gesture.AUTO, motion_profile=neutral.motion_profile,
            attack_ms=neutral.attack_ms, minimum_hold_ms=neutral.minimum_hold_ms,
            release_ms=neutral.release_ms, source_utterance_id=None, generation=0, speaking=False,
        )

    @classmethod
    def from_path(cls, path: Path) -> "EmotionEngine":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("mapping root must be an object")
            mapping = {Emotion(name): EmotionMapping.model_validate(value) for name, value in raw.items()}
            missing = set(Emotion) - set(mapping)
            if missing:
                raise ValueError(f"mapping misses emotions: {', '.join(item.value for item in sorted(missing, key=lambda item: item.value))}")
            return cls(mapping)
        except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            return cls(mapping_valid=False, mapping_error=str(exc))

    @property
    def state(self) -> EmotionState:
        return self._state

    def apply_metadata(self, *, emotion: Emotion, gesture: Gesture, intensity: float, utterance_id: str | None) -> EmotionState:
        """Apply one metadata frame. Repeated frames for the same utterance are idempotent."""
        if utterance_id and self._state.source_utterance_id == utterance_id:
            return self._state
        mapping = self.mapping[emotion]
        selected_gesture = gesture if gesture in mapping.allowed_gestures else Gesture.AUTO
        self._state = EmotionState(
            current_emotion=self._state.current_emotion,
            target_emotion=emotion,
            intensity=max(0.0, min(1.0, intensity)),
            gesture=selected_gesture,
            motion_profile=mapping.motion_profile,
            attack_ms=mapping.attack_ms,
            minimum_hold_ms=mapping.minimum_hold_ms,
            release_ms=mapping.release_ms,
            source_utterance_id=utterance_id,
            generation=self._state.generation + 1,
            speaking=utterance_id is not None,
        )
        return self._state

    def apply_gesture(self, gesture: Gesture, *, intensity: float = 1.0, interrupt: bool = True) -> EmotionState:
        allowed = self.mapping[self._state.target_emotion].allowed_gestures
        if gesture not in allowed:
            gesture = Gesture.AUTO
        if not interrupt and self._GESTURE_PRIORITIES[gesture] < self._GESTURE_PRIORITIES[self._state.gesture]:
            return self._state
        self._state = EmotionState(**{**self._state.__dict__, "gesture": gesture, "intensity": max(0.0, min(1.0, intensity))})
        return self._state

    def stop(self, utterance_id: str | None = None) -> EmotionState:
        """Only the active generation may reset the face to its neutral baseline."""
        if utterance_id is not None and utterance_id != self._state.source_utterance_id:
            return self._state
        neutral = self.mapping[Emotion.NEUTRAL]
        self._state = EmotionState(
            current_emotion=self._state.target_emotion,
            target_emotion=Emotion.NEUTRAL,
            intensity=neutral.weight,
            gesture=Gesture.AUTO,
            motion_profile=neutral.motion_profile,
            attack_ms=neutral.attack_ms,
            minimum_hold_ms=neutral.minimum_hold_ms,
            release_ms=neutral.release_ms,
            source_utterance_id=None,
            generation=self._state.generation + 1,
            speaking=False,
        )
        return self._state

    def status(self) -> dict[str, Any]:
        return {
            "mapping_valid": self.mapping_valid,
            "mapping_error": self.mapping_error,
            "current_emotion": self._state.current_emotion.value,
            "target_emotion": self._state.target_emotion.value,
            "intensity": self._state.intensity,
            "gesture": self._state.gesture.value,
            "motion_profile": self._state.motion_profile,
            "attack_ms": self._state.attack_ms,
            "minimum_hold_ms": self._state.minimum_hold_ms,
            "release_ms": self._state.release_ms,
            "source_utterance_id": self._state.source_utterance_id,
            "generation": self._state.generation,
            "speaking": self._state.speaking,
        }
