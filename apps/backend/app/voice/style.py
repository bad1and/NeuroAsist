from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class VoiceStyleProfile:
    intensity: int
    rate: str | None = None
    pitch: str | None = None
    pause_ms: int = 120


_PROFILES: dict[VoiceStyle, VoiceStyleProfile] = {
    VoiceStyle.CALM: VoiceStyleProfile(intensity=1, rate="slow", pitch="x-low", pause_ms=190),
    VoiceStyle.NORMAL: VoiceStyleProfile(intensity=3, pause_ms=120),
    VoiceStyle.ENERGETIC: VoiceStyleProfile(intensity=5, rate="fast", pitch="x-high", pause_ms=80),
    VoiceStyle.THOUGHTFUL: VoiceStyleProfile(intensity=2, rate="slow", pause_ms=170),
    VoiceStyle.ASSERTIVE: VoiceStyleProfile(intensity=4, pitch="x-low", pause_ms=130),
}


def coerce_voice_style(value: str | VoiceStyle | None) -> VoiceStyle:
    try:
        return VoiceStyle(value or VoiceStyle.AUTO)
    except ValueError:
        return VoiceStyle.AUTO


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


def profile_for(style: str | VoiceStyle) -> VoiceStyleProfile:
    return _PROFILES[resolve_voice_style(style)]


def make_silero_ssml(text: str, style: str | VoiceStyle) -> str:
    """Create only backend-owned SSML; source text is always escaped first."""
    profile = profile_for(style)
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
