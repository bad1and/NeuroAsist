"""Provider-neutral voice style and expression resolution."""

from __future__ import annotations

from enum import StrEnum


class VoiceStyle(StrEnum):
    AUTO = "auto"
    CALM = "calm"
    NORMAL = "normal"
    ENERGETIC = "energetic"
    THOUGHTFUL = "thoughtful"
    ASSERTIVE = "assertive"


class VoiceExpressionLevel(StrEnum):
    MINIMAL = "minimal"
    NATURAL = "natural"
    NOTICEABLE = "noticeable"


def coerce_voice_style(value: str | VoiceStyle | None) -> VoiceStyle:
    try:
        return VoiceStyle(value or VoiceStyle.AUTO)
    except ValueError:
        return VoiceStyle.AUTO


def coerce_voice_expression_level(value: str | VoiceExpressionLevel | None) -> VoiceExpressionLevel:
    try:
        return VoiceExpressionLevel(value or VoiceExpressionLevel.NATURAL)
    except ValueError:
        return VoiceExpressionLevel.NATURAL


def resolve_voice_style(
    requested: str | VoiceStyle | None,
    *,
    emotion: str | None = None,
    pace: str | None = None,
    emphasis: float = 0.0,
) -> VoiceStyle:
    manual = coerce_voice_style(requested)
    if manual is not VoiceStyle.AUTO:
        return manual
    if emotion in {"angry", "annoyed"}:
        return VoiceStyle.ASSERTIVE
    if emotion in {"sad", "embarrassed"}:
        return VoiceStyle.CALM
    if emotion in {"thinking", "concerned"}:
        return VoiceStyle.THOUGHTFUL
    if emotion in {"happy", "surprised", "smirk"} or pace == "fast":
        return VoiceStyle.ENERGETIC
    if pace == "slow":
        return VoiceStyle.CALM
    if emphasis >= 0.65:
        return VoiceStyle.ASSERTIVE
    return VoiceStyle.NORMAL


def resolve_turn_voice_style(requested: str | VoiceStyle | None, turn) -> VoiceStyle:
    if turn is None:
        return resolve_voice_style(requested)
    return resolve_voice_style(
        requested,
        emotion=getattr(getattr(turn, "affect", None), "emotion", None).value
        if getattr(getattr(turn, "affect", None), "emotion", None) is not None else None,
        pace=getattr(getattr(turn, "delivery", None), "pace", None),
        emphasis=float(getattr(getattr(turn, "delivery", None), "emphasis", 0.0) or 0.0),
    )
