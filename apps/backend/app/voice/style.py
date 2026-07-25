from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from html import escape
import re


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


@dataclass(frozen=True)
class VoiceStyleProfile:
    intensity: int
    rate: str | None = None
    pitch: str | None = None
    pause_ms: int = 120


_PROFILES: dict[VoiceStyle, VoiceStyleProfile] = {
    # Silero's prosody tags noticeably distort Baya at their extreme values.
    # Keep profiles close to the natural voice and differentiate with the
    # model-native intensity plus short, conversational sentence pauses.
    VoiceStyle.CALM: VoiceStyleProfile(intensity=2, pause_ms=155),
    VoiceStyle.NORMAL: VoiceStyleProfile(intensity=3, pause_ms=120),
    VoiceStyle.ENERGETIC: VoiceStyleProfile(intensity=4, pause_ms=95),
    VoiceStyle.THOUGHTFUL: VoiceStyleProfile(intensity=2, pause_ms=165),
    VoiceStyle.ASSERTIVE: VoiceStyleProfile(intensity=4, pause_ms=115),
}


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
    return VoiceStyle.NORMAL


def resolve_turn_voice_style(requested: str | VoiceStyle | None, turn) -> VoiceStyle:
    if turn is None:
        return resolve_voice_style(requested)
    return resolve_voice_style(
        requested,
        emotion=getattr(getattr(turn, "affect", None), "emotion", None).value
        if getattr(getattr(turn, "affect", None), "emotion", None) is not None else None,
        pace=getattr(getattr(turn, "delivery", None), "pace", None),
    )


def profile_for(
    style: str | VoiceStyle,
    expression_level: str | VoiceExpressionLevel = VoiceExpressionLevel.NATURAL,
) -> VoiceStyleProfile:
    profile = _PROFILES[resolve_voice_style(style)]
    weight = {
        VoiceExpressionLevel.MINIMAL: 0.45,
        VoiceExpressionLevel.NATURAL: 1.0,
        VoiceExpressionLevel.NOTICEABLE: 1.6,
    }[coerce_voice_expression_level(expression_level)]
    return replace(
        profile,
        intensity=max(1, min(5, round(3 + (profile.intensity - 3) * weight))),
        pause_ms=round(120 + (profile.pause_ms - 120) * weight),
    )


def make_silero_ssml(
    text: str,
    style: str | VoiceStyle,
    expression_level: str | VoiceExpressionLevel = VoiceExpressionLevel.NATURAL,
) -> str:
    """Create only backend-owned SSML; source text is always escaped first."""
    profile = profile_for(style, expression_level)
    rendered = escape(text, quote=False)
    rendered = re.sub(
        r"([.!?…])(?:\s+|$)",
        lambda match: f'{match.group(1)}<break time="{profile.pause_ms}ms"/> ',
        rendered,
    ).strip()
    if profile.rate or profile.pitch:
        attributes = " ".join(
            f'{name}="{value}"'
            for name, value in (("rate", profile.rate), ("pitch", profile.pitch))
            if value is not None
        )
        rendered = f"<prosody {attributes}>{rendered}</prosody>"
    return f"<speak>{rendered}</speak>"
