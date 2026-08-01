"""Read-only relationship profile derived from canonical evidence."""
from __future__ import annotations

from dataclasses import dataclass

from apps.backend.app.conversation.state import AffectState, ParticipantState


@dataclass(frozen=True)
class RelationshipProfile:
    familiarity_label: str
    trust_label: str
    warmth_label: str
    tension_label: str
    playfulness_label: str
    current_dynamic: str
    unresolved_cause: str | None
    source_event_ids: tuple[str, ...] = ()


class RelationshipProfileBuilder:
    def build(self, state: ParticipantState, affect: AffectState) -> RelationshipProfile:
        label = lambda value, low, high: low if value < .3 else high if value >= .7 else "умеренный"
        dynamic = "напряжённая" if state.tension >= .5 else "тёплая" if state.warmth >= .5 else "спокойная"
        return RelationshipProfile(
            familiarity_label=label(state.familiarity, "начальное", "хорошее"),
            trust_label=label(state.trust + 1 if state.trust < 0 else state.trust, "осторожное", "высокое"),
            warmth_label=label(state.warmth + 1 if state.warmth < 0 else state.warmth, "сдержанная", "тёплая"),
            tension_label="высокое" if state.tension >= .65 else "есть" if state.tension >= .3 else "нет",
            playfulness_label=label(state.playfulness, "низкая", "высокая"),
            current_dynamic=dynamic,
            unresolved_cause=affect.active_cause_labels[0] if affect.active_cause_labels else None,
        )
