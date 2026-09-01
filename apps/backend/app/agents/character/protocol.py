"""Character Protocol v3 adapters and deterministic metadata fallbacks."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from apps.backend.app.schemas.character import (
    AffectCue,
    CharacterLLMResponse,
    CharacterTurn,
    DeliveryCue,
    Emotion,
    Gesture,
    GestureCue,
    Intent,
)


def deterministic_turn(reply: str, user_text: str = "") -> CharacterTurn:
    """Keep a valid reply when model metadata is absent or invalid.

    This deliberately has no model dependency, which makes metadata degradation
    predictable for batch and live paths alike.
    """
    text = (user_text or "").lower()
    if any(marker in text for marker in ("бесит", "заеб", "злит", "ненавиж", "ошибк")):
        emotion, gesture = Emotion.ANNOYED, Gesture.FRUSTRATION
    elif any(marker in text for marker in ("спасибо", "класс", "круто", "ура", "молодец", "ахах", "смеш")):
        emotion, gesture = Emotion.HAPPY, Gesture.TALK
    elif "?" in text or text.startswith(("как ", "почему ", "что ", "кто ", "где ", "когда ", "зачем ")):
        emotion, gesture = Emotion.THINKING, Gesture.QUESTION
    else:
        emotion, gesture = Emotion.NEUTRAL, Gesture.AUTO
    return CharacterTurn(
        reply=reply,
        intent=classify_intent(user_text),
        affect=AffectCue(emotion=emotion),
        gesture=GestureCue(name=gesture),
        delivery=DeliveryCue(),
    )


def classify_intent(user_text: str) -> Intent:
    text = user_text.strip().lower()
    if not text:
        return Intent.UNKNOWN
    task_markers = (
        "сделай", "создай", "запусти", "открой", "покажи", "напиши",
        "помоги", "please", "create", "make", "run", "open", "write",
    )
    if any(marker in text for marker in task_markers):
        return Intent.TASK_REQUEST
    if "?" in text or text.startswith(("кто ", "что ", "где ", "когда ", "как ", "почему ", "why ", "how ", "what ", "who ")):
        return Intent.QUESTION
    return Intent.CASUAL_CHAT


def parse_turn(payload: dict[str, Any], *, user_text: str = "") -> tuple[CharacterTurn, bool, str | None]:
    """Parse v3 natively and v1/v2 through a lossless compatibility adapter."""
    if (
        "affect" in payload
        or "delivery" in payload
        or "memory_candidates" in payload
        or "coding_delegation" in payload
        or isinstance(payload.get("gesture"), dict)
    ):
        try:
            return CharacterTurn.model_validate(payload), True, None
        except ValidationError as exc:
            reply = payload.get("reply")
            if isinstance(reply, str) and reply.strip():
                return deterministic_turn(reply.strip(), user_text), False, "invalid_metadata"
            raise exc

    # v1/v2 used top-level emotion/gesture. Retain it while only this adapter exists.
    legacy = CharacterLLMResponse.model_validate(payload)
    return CharacterTurn(
        reply=legacy.reply,
        intent=legacy.intent,
        affect=AffectCue(emotion=legacy.emotion),
        gesture=GestureCue(name=legacy.gesture),
        delivery=DeliveryCue(),
    ), True, "legacy_adapter"


def legacy_result(
    turn: CharacterTurn, *, include_metadata: bool = False, include_gesture: bool = True
) -> dict[str, Any]:
    """v1/v2 flat projection for existing REST, TTS and browser callers."""
    result: dict[str, Any] = {
        "reply": turn.reply,
        "emotion": turn.affect.emotion.value,
        "intent": turn.intent.value,
    }
    if include_gesture:
        result["gesture"] = turn.gesture.name.value
    if include_metadata:
        result["gesture_intensity"] = turn.gesture.intensity
        result["metadata"] = turn.metadata_frame()
    return result


def metadata_frame(*, intent: str, emotion: str, gesture: str, intensity: float) -> dict[str, object]:
    """Build a v3 metadata-only frame for a streamed character turn."""
    turn = CharacterTurn(
        reply="metadata",
        intent=Intent(intent),
        affect=AffectCue(emotion=Emotion(emotion), intensity=intensity),
        gesture=GestureCue(name=Gesture(gesture), intensity=intensity),
        delivery=DeliveryCue(),
    )
    return turn.metadata_frame()
