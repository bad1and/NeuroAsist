from __future__ import annotations

import re
from dataclasses import dataclass

from apps.backend.app.schemas.character import Emotion


_EMOTIONS = frozenset(item.value for item in Emotion)
_GESTURES = frozenset({
    "none", "auto", "talk", "talk_right", "talk_left",
    "greeting", "greeting_right", "greeting_left", "greeting_casual",
    "agreement", "disagreement", "question", "question_right", "question_left",
    "explanation", "explanation_right", "explanation_left",
    "thinking", "thinking_right", "thinking_left",
    "surprise", "frustration",
    "farewell", "farewell_right", "farewell_left", "farewell_casual",
    "shrug", "nod",
})
_HEADER_RE = re.compile(
    r"^\[\[avatar\s+emotion=(?P<emotion>[a-z_]+)\s+gesture=(?P<gesture>[a-z_]+)\s+intensity=(?P<intensity>0(?:\.\d+)?|1(?:\.0+)?)\s*\]\]",
    re.IGNORECASE,
)
_LEADING_DIRECTION_RE = re.compile(r"^\s*\((?P<direction>[^()\n]{1,160})\)\s*", re.DOTALL)


@dataclass(frozen=True)
class AvatarDirective:
    emotion: Emotion = Emotion.NEUTRAL
    gesture: str = "auto"
    intensity: float = 1.0


def parse_avatar_directive(tag_text: str) -> AvatarDirective:
    """Parse [[avatar ...]] tag with arbitrary attribute ordering and partial attributes."""
    inner = tag_text.strip()
    if inner.startswith("[[") and inner.endswith("]]"):
        inner = inner[2:-2].strip()
    if inner.lower().startswith("avatar"):
        inner = inner[6:].strip()
    attrs = dict(re.findall(r'([a-zA-Z_]+)\s*=\s*([^\s\]]+)', inner))
    raw_emotion = attrs.get("emotion", "").lower().replace("-", "_")
    raw_gesture = attrs.get("gesture", "").lower().replace("-", "_")
    raw_intensity = attrs.get("intensity")

    if raw_emotion in ("tongue", "tongue_out"):
        emotion = Emotion.TEASING
    elif raw_emotion in _EMOTIONS:
        emotion = Emotion(raw_emotion)
    else:
        emotion = Emotion.NEUTRAL

    gesture = raw_gesture if raw_gesture in _GESTURES else "auto"
    try:
        intensity = float(raw_intensity) if raw_intensity is not None else 1.0
        intensity = max(0.0, min(1.0, intensity))
    except (ValueError, TypeError):
        intensity = 1.0
    return AvatarDirective(emotion=emotion, gesture=gesture, intensity=intensity)


def make_live_directive_expressive(directive: AvatarDirective, user_text: str) -> AvatarDirective:
    """Respect the neural LLM directive directly without artificial keyword overrides."""
    return directive


class LiveDirectiveParser:
    """Consumes only a leading avatar directive and never releases it as spoken text."""

    _MAX_PREFIX = 192

    def __init__(self) -> None:
        self._buffer = ""
        self._resolved = False

    def feed(self, delta: str) -> tuple[AvatarDirective | None, list[str]]:
        if not delta:
            return None, []
        if self._resolved:
            return None, [delta]
        self._buffer += delta
        return self._resolve(final=False)

    def finish(self) -> tuple[AvatarDirective | None, list[str]]:
        if self._resolved:
            return None, []
        return self._resolve(final=True)

    def _resolve(self, *, final: bool) -> tuple[AvatarDirective | None, list[str]]:
        source = self._buffer
        stripped = source.lstrip()
        leading_space = source[: len(source) - len(stripped)]

        if stripped.startswith("[["):
            end = stripped.find("]]", 2)
            if end >= 0:
                header = stripped[: end + 2]
                remainder = leading_space + stripped[end + 2 :]
                self._resolved = True
                self._buffer = ""
                directive = parse_avatar_directive(header)
                return directive, self._parts(remainder)
            if not final and len(stripped) <= self._MAX_PREFIX:
                return None, []
            self._resolved = True
            self._buffer = ""
            # A malformed machine header is never user-facing speech.
            return AvatarDirective(), []

        if stripped.startswith("("):
            match = _LEADING_DIRECTION_RE.match(source)
            if match is not None:
                self._resolved = True
                self._buffer = ""
                return self._from_legacy_direction(match.group("direction")), self._parts(source[match.end() :])
            if not final and len(stripped) <= self._MAX_PREFIX:
                return None, []

        self._resolved = True
        self._buffer = ""
        return AvatarDirective(), self._parts(source)

    @staticmethod
    def _parts(value: str) -> list[str]:
        return [value] if value.strip() else []

    @staticmethod
    def _from_header(match: re.Match[str] | None) -> AvatarDirective:
        if match is None:
            return AvatarDirective()
        return parse_avatar_directive(match.group(0))

    @staticmethod
    def _from_legacy_direction(value: str) -> AvatarDirective:
        text = value.lower()
        if any(word in text for word in ("саркаст", "ухмыл", "усмеш")):
            return AvatarDirective(Emotion.SMIRK, "shrug", 0.55)
        if "кива" in text:
            return AvatarDirective(Emotion.HAPPY, "agreement", 0.7)
        if any(word in text for word in ("удив", "изум")):
            return AvatarDirective(Emotion.SURPRISED, "surprise", 0.8)
        if any(word in text for word in ("раздраж", "злоб", "серд")):
            return AvatarDirective(Emotion.ANNOYED, "frustration", 0.65)
        if any(word in text for word in ("груст", "печал")):
            return AvatarDirective(Emotion.SAD, "auto", 0.65)
        if any(word in text for word in ("задум", "размыш")):
            return AvatarDirective(Emotion.THINKING, "thinking", 0.55)
        if any(word in text for word in ("улыб", "радост")):
            return AvatarDirective(Emotion.HAPPY, "talk", 0.7)
        return AvatarDirective()


def clean_live_reply(raw_reply: str) -> str:
    """Strip the initial control/directorial prefix before committing the reply to history."""
    from apps.backend.app.voice.delivery import clean_voice_directives
    parser = LiveDirectiveParser()
    _, parts = parser.feed(raw_reply)
    _, tail = parser.finish()
    cleaned = clean_voice_directives("".join([*parts, *tail]))
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" ([.,!?:;…])", r"\1", cleaned)
    return cleaned.strip()
