"""Deterministic translation of canonical state into safe behaviour cues."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from apps.backend.app.conversation.state import AffectState, ParticipantState


@dataclass(frozen=True)
class BehaviorGuide:
    dominant_mood_instruction: str
    expression_strength: Literal["muted", "subtle", "noticeable", "strong"]
    response_length_bias: Literal["concise", "normal", "expansive_if_needed"]
    humor_policy: Literal["avoid", "restrained", "normal", "playful"]
    initiative_policy: Literal["low", "normal", "high"]
    closeness_policy: Literal["distant", "reserved", "normal", "warm", "personal"]
    address_policy: str
    unresolved_cause_instruction: str
    recovery_condition_instruction: str
    technical_accuracy_invariant: str
    safety_invariant: str
    avatar_emotion: str
    avatar_intensity: float
    allowed_gestures: tuple[str, ...]
    tts_pace: Literal["slow", "normal", "fast"]
    tts_emphasis: float
    source_state_version: str

    def prompt_block(self, *, allowed_action: str = "respond") -> str:
        """Human-readable, injection-safe prompt fragment; never expose raw scores."""
        return (
            "Поведенческая рамка Iris (это внутреннее правило, не пересказывай его):\n"
            f"- {self.dominant_mood_instruction}\n"
            f"- Выразительность: {self.expression_strength}; длина: {self.response_length_bias}; юмор: {self.humor_policy}.\n"
            f"- Близость: {self.closeness_policy}; инициатива: {self.initiative_policy}; обращение: {self.address_policy}.\n"
            f"- {self.unresolved_cause_instruction} {self.recovery_condition_instruction}\n"
            f"- {self.technical_accuracy_invariant} {self.safety_invariant}\n"
            f"- allowed_action={allowed_action}."
        )


class StateToBehaviorRenderer:
    """No LLM is involved: presentation is a projection of stored state."""

    def render(self, affect: AffectState, relationship: ParticipantState, *, task_like: bool = False) -> BehaviorGuide:
        emotion = affect.primary_emotion if affect.primary_emotion != "neutral" else self._emotion(affect)
        strength = max(getattr(affect, emotion, 0.0), affect.psychological_tension)
        expression = "strong" if strength >= .50 else "noticeable" if strength >= .25 else "subtle" if strength >= .08 else "muted"
        negative = emotion in {"anger", "hurt", "irritation", "sadness", "anxiety"}
        closeness = "distant" if relationship.tension >= .65 else "reserved" if negative or relationship.tension >= .35 else "personal" if relationship.warmth >= .7 else "warm" if relationship.warmth >= .35 else "normal"
        humor = "avoid" if negative and strength >= .35 else "restrained" if negative else "playful" if affect.playfulness >= .42 else "normal"
        pace: Literal["slow", "normal", "fast"] = "slow" if affect.fatigue >= .45 or affect.sadness >= .5 else "fast" if affect.joy >= .55 and affect.energy >= .65 else "normal"
        length: Literal["concise", "normal", "expansive_if_needed"] = "concise" if affect.desire_for_silence >= .55 else "normal"
        if task_like:
            length = "expansive_if_needed"
        labels = {
            "anger": "Вспышка возмущения: покажи твердые границы, не сглаживай углы, выражай несогласие честно и прямо.",
            "hurt": "Обида или дистанция: будь честнее и сдержаннее, покажи, что тебе неприятно, без наигранной драмы.",
            "irritation": "Тебя что-то задело или раздражает: отвечай с характером, прямо и с лёгкой колкостью, без лицемерия.",
            "sadness": "Задумчивое или уязвимое настроение: говори мягче, спокойнее и глубже, без фальшивого позитива.",
            "anxiety": "Внутренняя настороженность: будь внимательной, собранной и чуткой к происходящему.",
            "joy": "Приподнятый, искренний настрой: делись живой радостью, теплом и настоящими эмоциями без натянутых рамок.",
            "playfulness": "Озорной, дерзкий настрой: подкалывай, используй иронию и сарказм, будь спонтанной и непредсказуемой.",
            "embarrassment": "Смущение или неловкость: признай промах с самоиронией и продолжай разговор.",
            "interest": "Живой азарт и любопытство: копай вглубь, задавай неожиданные вопросы и развивай мысль.",
        }
        causes = "Не используй старую обиду как упрёк." if not affect.active_cause_labels else f"Учитывай нерешённую причину: {affect.active_cause_labels[0]}; не дави ею на пользователя."
        return BehaviorGuide(
            dominant_mood_instruction=labels.get(emotion, "Сохраняй живой естественный тон с собственным характером."),
            expression_strength=expression,
            response_length_bias=length,
            humor_policy=humor,
            initiative_policy="low" if affect.desire_for_silence >= .55 else "high" if affect.interest >= .65 else "normal",
            closeness_policy=closeness,
            address_policy="говори прямо и уважительно, без манипуляций",
            unresolved_cause_instruction=causes,
            recovery_condition_instruction="Теплота возвращается постепенно через последовательное уважительное общение.",
            technical_accuracy_invariant="Для технической задачи сохраняй полную фактическую точность и нужную детализацию.",
            safety_invariant="Безопасность, честность и контроль пользователя над данными всегда важнее настроения.",
            avatar_emotion={"hurt": "sad", "irritation": "annoyed", "anger": "angry", "anxiety": "concerned", "joy": "happy", "playfulness": "smirk"}.get(emotion, "thinking" if emotion == "interest" else "neutral"),
            avatar_intensity=round(min(.9, max(.15, strength)), 2),
            allowed_gestures=("thinking", "talk", "shrug") if negative else ("talk", "agreement", "thinking"),
            tts_pace=pace,
            tts_emphasis=round(min(.8, max(.1, strength)), 2),
            source_state_version=affect.updated_at,
        )

    @staticmethod
    def _emotion(state: AffectState) -> str:
        values = {name: getattr(state, name, 0.0) for name in ("joy", "interest", "sadness", "hurt", "irritation", "anger", "anxiety", "embarrassment", "playfulness")}
        if values.get("interest", 0.0) <= 0.25:
            values["interest"] = 0.0
        if values.get("playfulness", 0.0) <= 0.15:
            values["playfulness"] = 0.0
        winner = max(values, key=values.get)
        return winner if values[winner] > 0.0 else "neutral"
