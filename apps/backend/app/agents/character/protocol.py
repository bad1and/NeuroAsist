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
    """Keep a valid reply when model metadata is absent or invalid."""
    intent = classify_intent(user_text)
    from apps.backend.app.voice.directives import infer_animation_directive
    inferred = infer_animation_directive(user_text, reply)
    action_gestures = (
        "greeting_right", "farewell_right", "nod", "disagreement", "shrug",
        "surprise", "frustration", "head_scratch", "clapping", "laughing",
        "thumbs_up", "facepalm", "pointing", "bow",
    )
    if inferred.gesture in action_gestures:
        try:
            gesture = Gesture(inferred.gesture)
            return CharacterTurn(
                reply=reply,
                intent=intent,
                affect=AffectCue(emotion=inferred.emotion),
                gesture=GestureCue(name=gesture),
                delivery=DeliveryCue(),
            )
        except ValueError:
            pass

    if intent == Intent.QUESTION:
        emotion = Emotion.THINKING
        gesture = Gesture.QUESTION
    elif intent == Intent.TASK_REQUEST:
        emotion = Emotion.THINKING
        gesture = Gesture.EXPLANATION
    else:
        lower = reply.lower()
        if any(w in lower for w in ("привет", "здравствуй", "добрый", "хай", "hello", "hey")):
            emotion = Emotion.HAPPY
            gesture = Gesture.GREETING_RIGHT
        elif any(w in lower for w in ("пока", "до свидания", "до встречи", "bye")):
            emotion = Emotion.NEUTRAL
            gesture = Gesture.FAREWELL_RIGHT
        elif any(w in lower for w in ("да", "конечно", "согласна", "точно", "именно")):
            emotion = Emotion.HAPPY
            gesture = Gesture.AGREEMENT
        elif any(w in lower for w in ("нет", "не согласна", "не думаю", "нельзя")):
            emotion = Emotion.SKEPTICAL
            gesture = Gesture.DISAGREEMENT
        elif "?" in reply:
            emotion = Emotion.CURIOUS
            gesture = Gesture.QUESTION
        else:
            emotion = Emotion.NEUTRAL
            gesture = Gesture.TALK

    return CharacterTurn(
        reply=reply,
        intent=intent,
        affect=AffectCue(emotion=emotion),
        gesture=GestureCue(name=gesture),
        delivery=DeliveryCue(),
    )


def classify_intent(user_text: str) -> Intent:
    text = (user_text or "").lower().strip()
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
    payload_copy = dict(payload)
    if "emotion" in payload_copy and "affect" not in payload_copy and ("delivery" in payload_copy or "memory_candidates" in payload_copy or isinstance(payload_copy.get("gesture"), dict)):
        raw_emo = payload_copy.pop("emotion")
        if isinstance(raw_emo, str):
            payload_copy["affect"] = {"emotion": raw_emo}

    if (
        "affect" in payload_copy
        or "delivery" in payload_copy
        or "memory_candidates" in payload_copy
        or "coding_delegation" in payload_copy
        or isinstance(payload_copy.get("gesture"), dict)
    ):
        try:
            turn = CharacterTurn.model_validate(payload_copy)
            from apps.backend.app.voice.directives import infer_animation_directive
            inferred = infer_animation_directive(user_text, turn.reply)
            action_gestures = (
                "greeting_right", "farewell_right", "nod", "disagreement", "shrug",
                "surprise", "frustration", "head_scratch", "clapping", "laughing",
                "thumbs_up", "facepalm", "pointing", "bow",
            )
            if inferred.gesture in action_gestures:
                if turn.gesture.name in (Gesture.AUTO, Gesture.TALK, Gesture.NONE) or turn.affect.emotion == Emotion.NEUTRAL:
                    try:
                        resolved_gesture = Gesture(inferred.gesture)
                        turn = turn.model_copy(update={
                            "gesture": GestureCue(name=resolved_gesture, intensity=turn.gesture.intensity),
                            "affect": AffectCue(emotion=inferred.emotion if turn.affect.emotion == Emotion.NEUTRAL else turn.affect.emotion, intensity=turn.affect.intensity),
                        })
                    except ValueError:
                        pass
            return turn, True, None
        except ValidationError as exc:
            reply = payload_copy.get("reply")
            if isinstance(reply, str) and reply.strip():
                return deterministic_turn(reply.strip(), user_text), False, "invalid_metadata"
            raise exc

    # v1/v2 used top-level emotion/gesture. Retain it while only this adapter exists.
    legacy = CharacterLLMResponse.model_validate(payload_copy)
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
        result["intensity"] = turn.affect.intensity
        result["valence"] = turn.affect.valence
        result["arousal"] = turn.affect.arousal
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
