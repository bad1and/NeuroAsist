from __future__ import annotations

import re
from dataclasses import dataclass

from apps.backend.app.schemas.character import Emotion


_EMOTIONS = frozenset(item.value for item in Emotion)
_GESTURES = frozenset({
    "none", "auto", "talk", "greeting", "agreement", "disagreement", "question",
    "explanation", "thinking", "surprise", "frustration", "farewell", "shrug",
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


def make_live_directive_expressive(directive: AvatarDirective, user_text: str) -> AvatarDirective:
    """Keep live avatar reactions visible even when a model omits or defaults its directive."""
    text = (user_text or "").lower()
    emotion = directive.emotion
    if emotion == Emotion.NEUTRAL:
        if any(marker in text for marker in ("бесит", "заеб", "злит", "ненавиж", "туп", "ошибк")):
            emotion = Emotion.ANNOYED
        elif any(marker in text for marker in ("спасибо", "класс", "круто", "ура", "молодец", "ахах", "смеш")):
            emotion = Emotion.HAPPY
        elif "?" in text or text.startswith(("как ", "почему ", "что ", "кто ", "где ", "когда ", "зачем ")):
            emotion = Emotion.THINKING
        else:
            emotion = Emotion.NEUTRAL
    gesture = directive.gesture
    if gesture == "auto":
        gesture = {
            Emotion.SMIRK: "shrug",
            Emotion.HAPPY: "talk",
            Emotion.SAD: "shrug",
            Emotion.ANGRY: "frustration",
            Emotion.ANNOYED: "frustration",
            Emotion.SURPRISED: "surprise",
            Emotion.THINKING: "question",
        }.get(emotion, "talk")
    return AvatarDirective(emotion, gesture, max(.45, directive.intensity))


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
                match = _HEADER_RE.match(header)
                return (self._from_header(match) if match else AvatarDirective()), self._parts(remainder)
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
        emotion = match.group("emotion").lower()
        gesture = match.group("gesture").lower()
        intensity = float(match.group("intensity"))
        return AvatarDirective(
            emotion=Emotion(emotion) if emotion in _EMOTIONS else Emotion.NEUTRAL,
            gesture=gesture if gesture in _GESTURES else "auto",
            intensity=max(0.0, min(1.0, intensity)),
        )

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
    parser = LiveDirectiveParser()
    _, parts = parser.feed(raw_reply)
    _, tail = parser.finish()
    return "".join([*parts, *tail]).strip()
