from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from apps.backend.app.conversation.schemas import EventAppraisal


EMOTION_HALF_LIVES_MINUTES: dict[str, float] = {
    "joy": 12.0,
    "interest": 20.0,
    "playfulness": 20.0,
    "irritation": 20.0,
    "anger": 25.0,
    "embarrassment": 15.0,
    "anxiety": 45.0,
    "sadness": 60.0,
    "hurt": 90.0,
    "fatigue": 120.0,
}
RELATIONSHIP_FACETS = {"familiarity", "trust", "warmth", "tension", "playfulness"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, float(value)))


@dataclass
class AffectState:
    valence: float = 0.0
    arousal: float = 0.25
    energy: float = 0.65
    social_openness: float = 0.65
    desire_for_silence: float = 0.1
    joy: float = 0.0
    interest: float = 0.25
    sadness: float = 0.0
    hurt: float = 0.0
    irritation: float = 0.0
    anger: float = 0.0
    anxiety: float = 0.0
    embarrassment: float = 0.0
    playfulness: float = 0.15
    fatigue: float = 0.0
    causes: list[dict[str, object]] = field(default_factory=list)
    updated_at: str = field(default_factory=_now)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class ParticipantState:
    participant_key: str = "primary"
    role: str = "primary"
    familiarity: float = 0.15
    trust: float = 0.0
    warmth: float = 0.15
    tension: float = 0.0
    playfulness: float = 0.1
    evidence_count: int = 0
    updated_at: str = field(default_factory=_now)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class CharacterStateReducer:
    """Deterministic, bounded reducer for affect and relationship state."""

    def decay(self, state: AffectState, *, now: datetime | None = None, recovery: str = "natural") -> AffectState:
        current = now or datetime.now(UTC)
        updated = datetime.fromisoformat(state.updated_at.replace("Z", "+00:00"))
        elapsed_minutes = max(0.0, (current - updated).total_seconds() / 60.0)
        multiplier = {"fast": 0.6, "natural": 1.0, "slow": 1.6}.get(recovery, 1.0)
        for emotion, half_life in EMOTION_HALF_LIVES_MINUTES.items():
            value = getattr(state, emotion)
            setattr(state, emotion, value * math.pow(0.5, elapsed_minutes / (half_life * multiplier)))
        state.valence *= math.pow(0.5, elapsed_minutes / (45.0 * multiplier))
        state.arousal = 0.25 + (state.arousal - 0.25) * math.pow(0.5, elapsed_minutes / (30.0 * multiplier))
        state.energy = 0.65 + (state.energy - 0.65) * math.pow(0.5, elapsed_minutes / (120.0 * multiplier))
        state.social_openness = 0.65 + (state.social_openness - 0.65) * math.pow(
            0.5, elapsed_minutes / (90.0 * multiplier)
        )
        state.desire_for_silence *= math.pow(0.5, elapsed_minutes / (45.0 * multiplier))
        state.updated_at = current.isoformat(timespec="milliseconds")
        return state

    def apply_affect(self, state: AffectState, appraisal: EventAppraisal) -> AffectState:
        strength = appraisal.confidence * appraisal.intensity
        state.valence = _clamp(state.valence + appraisal.valence * strength * 0.18, -1.0, 1.0)
        state.arousal = _clamp(state.arousal + appraisal.arousal * strength * 0.14, 0.0, 1.0)
        for emotion, impulse in appraisal.emotion_impulses.items():
            if emotion in EMOTION_HALF_LIVES_MINUTES:
                setattr(state, emotion, _clamp(getattr(state, emotion) + _clamp(impulse, -1, 1) * strength * 0.18, 0, 1))
        state.social_openness = _clamp(
            state.social_openness + (state.joy + state.interest - state.hurt - state.anger) * 0.025,
            0.0,
            1.0,
        )
        state.desire_for_silence = _clamp(
            state.desire_for_silence + (state.hurt + state.fatigue + state.irritation) * 0.025,
            0.0,
            1.0,
        )
        if appraisal.cause_message_ids and strength >= 0.05:
            state.causes = (
                [{
                    "event_kind": appraisal.event_kind,
                    "message_ids": appraisal.cause_message_ids[:5],
                    "strength": round(strength, 4),
                }] + state.causes
            )[:5]
        state.updated_at = _now()
        return state

    def apply_relationship(
        self,
        state: ParticipantState,
        appraisal: EventAppraisal,
        *,
        serious: bool = False,
        repeated_events: int = 0,
        daily_delta_used: dict[str, float] | None = None,
    ) -> tuple[ParticipantState, dict[str, float]]:
        applied: dict[str, float] = {}
        per_event_cap = 0.10 if serious and appraisal.confidence >= 0.8 else 0.03
        diminishing = math.pow(0.5, max(0, repeated_events))
        used = daily_delta_used or {}
        for facet, raw_delta in appraisal.relationship_impulses.items():
            if facet not in RELATIONSHIP_FACETS:
                continue
            delta = _clamp(raw_delta * appraisal.confidence * appraisal.intensity * diminishing, -per_event_cap, per_event_cap)
            remaining = max(0.0, 0.15 - abs(used.get(facet, 0.0)))
            delta = _clamp(delta, -remaining, remaining)
            lower = -1.0 if facet in {"trust", "warmth"} else 0.0
            current = getattr(state, facet)
            next_value = _clamp(current + delta, lower, 1.0)
            applied[facet] = next_value - current
            setattr(state, facet, next_value)
        if applied:
            state.evidence_count += 1
            state.updated_at = _now()
        return state, applied

    @staticmethod
    def display_emotion(state: AffectState) -> str:
        candidates = {
            "angry": state.anger,
            "concerned": state.anxiety,
            "sad": state.sadness,
            "annoyed": state.irritation,
            "embarrassed": state.embarrassment,
            "happy": state.joy,
            "smirk": state.playfulness,
            "thinking": state.interest * 0.7,
        }
        emotion, activation = max(candidates.items(), key=lambda item: item[1])
        return emotion if activation >= 0.28 else "neutral"
