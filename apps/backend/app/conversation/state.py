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
    schema_version: int = 2
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
    primary_emotion: str = "neutral"
    primary_emotion_since: str | None = None
    secondary_emotions: list[str] = field(default_factory=list)
    psychological_tension: float = 0.0
    interaction_load: float = 0.0
    last_decay_at: str | None = None
    cooling_down_turns: int = 0
    mood_epoch: int = 0
    updated_at: str = field(default_factory=_now)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    @property
    def active_cause_labels(self) -> list[str]:
        return [str(cause.get("display_label") or cause.get("event_kind")) for cause in self.causes if cause.get("status", "active") == "active"]


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
    last_positive_event_at: str | None = None
    last_negative_event_at: str | None = None
    last_repair_event_at: str | None = None
    relationship_epoch: int = 0
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
        for cause in state.causes:
            if cause.get("status", "active") != "active":
                continue
            half_life = max(1.0, float(cause.get("half_life_minutes", EMOTION_HALF_LIVES_MINUTES.get(str(cause.get("emotion")), 45.0))))
            strength = float(cause.get("current_strength", cause.get("strength", 0.0)))
            decayed = strength * math.pow(0.5, elapsed_minutes / (half_life * multiplier))
            cause["current_strength"] = round(decayed, 6)
            cause["last_decayed_at"] = current.isoformat(timespec="milliseconds")
            if decayed < .02:
                cause["status"] = "expired"
        state.causes = [cause for cause in state.causes if cause.get("status", "active") == "active"][:8]
        self._derive_emotions(state, current)
        state.last_decay_at = current.isoformat(timespec="milliseconds")
        state.updated_at = current.isoformat(timespec="milliseconds")
        return state

    def apply_affect(self, state: AffectState, appraisal: EventAppraisal) -> AffectState:
        strength = appraisal.confidence * appraisal.intensity
        state.valence = _clamp(state.valence + appraisal.valence * strength * 0.45, -1.0, 1.0)
        state.arousal = _clamp(state.arousal + appraisal.arousal * strength * 0.14, 0.0, 1.0)
        for emotion, impulse in appraisal.emotion_impulses.items():
            if emotion in EMOTION_HALF_LIVES_MINUTES:
                setattr(state, emotion, _clamp(getattr(state, emotion) + _clamp(impulse, -1, 1) * strength * 0.45, 0, 1))
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
        if appraisal.cause_message_ids and strength >= 0.05 and appraisal.event_kind not in {"neutral", "interruption"}:
            fingerprint = f"{appraisal.target_participant}:{appraisal.event_kind}:{','.join(sorted(appraisal.cause_message_ids))}"
            existing = next((item for item in state.causes if item.get("fingerprint") == fingerprint and item.get("status", "active") == "active"), None)
            dominant = max(appraisal.emotion_impulses, key=appraisal.emotion_impulses.get, default="interest")
            if existing is not None:
                existing["current_strength"] = round(min(1.0, float(existing.get("current_strength", 0.0)) + strength * .35), 6)
                existing["last_reinforced_at"] = _now()
            else:
                state.causes.insert(0, {
                    "id": fingerprint,
                    "fingerprint": fingerprint,
                    "event_kind": appraisal.event_kind,
                    "emotion": dominant,
                    "message_ids": appraisal.cause_message_ids[:5],
                    "display_label": appraisal.event_kind.replace("_", " "),
                    "initial_strength": round(strength, 4),
                    "current_strength": round(strength, 4),
                    "half_life_minutes": EMOTION_HALF_LIVES_MINUTES.get(dominant, 45.0),
                    "status": "active",
                    "created_at": _now(),
                })
                state.causes = state.causes[:8]
        if appraisal.event_kind == "apology":
            state.hurt = round(max(0.0, state.hurt * 0.35 - 0.1), 4)
            state.anger = round(max(0.0, state.anger * 0.3 - 0.1), 4)
            state.irritation = round(max(0.0, state.irritation * 0.35 - 0.1), 4)
            state.valence = _clamp(state.valence + 0.35, -1.0, 1.0)
            state.social_openness = _clamp(state.social_openness + 0.25, 0.0, 1.0)
            state.desire_for_silence = _clamp(state.desire_for_silence - 0.35, 0.0, 1.0)
            for cause in state.causes:
                if cause.get("event_kind") in {"insult", "broken_promise", "important_negative_event"}:
                    cause["current_strength"] = round(float(cause.get("current_strength", 0.0)) * .35, 6)
                    cause["resolution_kind"] = "apology_repair"
                    cause["resolved_by_event_id"] = appraisal.cause_message_ids[0] if appraisal.cause_message_ids else None
        self._derive_emotions(state, datetime.now(UTC))
        state.updated_at = _now()
        return state

    def resolve_forgiveness(self, state: AffectState) -> AffectState:
        """Fully resolves conflict causes and clears lingering hurt when Iris forgives or reconciles."""
        state.hurt = 0.0
        state.anger = 0.0
        state.irritation = 0.0
        state.psychological_tension = 0.0
        state.valence = _clamp(max(0.1, state.valence + 0.25), -1.0, 1.0)
        state.desire_for_silence = 0.0
        state.cooling_down_turns = 0
        for cause in state.causes:
            if cause.get("resolution_kind") == "apology_repair" or cause.get("event_kind") in {"insult", "broken_promise", "important_negative_event", "apology"}:
                cause["status"] = "resolved"
                cause["current_strength"] = 0.0
        state.causes = [c for c in state.causes if c.get("status", "active") == "active"]
        self._derive_emotions(state, datetime.now(UTC))
        state.updated_at = _now()
        return state

    @staticmethod
    def _derive_emotions(state: AffectState, now: datetime) -> None:
        scores = {name: getattr(state, name) for name in EMOTION_HALF_LIVES_MINUTES}
        if scores["interest"] < .28:
            scores["interest"] = 0.0
        if scores["playfulness"] < .20:
            scores["playfulness"] = 0.0
        if scores["hurt"] < .08:
            scores["hurt"] = 0.0
        if scores["irritation"] < .08:
            scores["irritation"] = 0.0
        if scores["anger"] < .08:
            scores["anger"] = 0.0
        winner, score = max(scores.items(), key=lambda item: item[1])
        current_score = scores.get(state.primary_emotion, 0.0)
        # Hysteresis prevents avatar/prompt flicker on nearby values.
        # Acute negative reactions (irritation, anger, hurt) immediately break positive hysteresis.
        has_acute_negative = scores["anger"] >= 0.10 or scores["irritation"] >= 0.10 or scores["hurt"] >= 0.10
        if score < .02:
            winner = "neutral"
        elif state.primary_emotion != "neutral" and not has_acute_negative and current_score >= score - .08 and current_score > 0.0:
            winner = state.primary_emotion
        if winner != state.primary_emotion:
            state.primary_emotion = winner
            state.primary_emotion_since = now.isoformat(timespec="milliseconds")
        state.secondary_emotions = [name for name, value in sorted(scores.items(), key=lambda item: item[1], reverse=True) if name != winner and value >= .18][:2]
        state.psychological_tension = _clamp(state.hurt * .55 + state.anxiety * .35 + state.anger * .4 + state.irritation * .2, 0.0, 1.0)
        state.interaction_load = _clamp(state.fatigue * .7 + state.desire_for_silence * .3, 0.0, 1.0)

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
        if state.primary_emotion and state.primary_emotion != "neutral":
            return {"joy": "happy", "irritation": "annoyed", "anxiety": "concerned", "playfulness": "smirk", "interest": "thinking"}.get(state.primary_emotion, state.primary_emotion)
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
