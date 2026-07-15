from __future__ import annotations

import re
from dataclasses import dataclass


_EMOTIONS = frozenset({"neutral", "happy", "sad", "angry", "annoyed", "smirk", "thinking", "surprised"})
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
    emotion: str = "neutral"
    gesture: str = "auto"
    intensity: float = 1.0


def make_live_directive_expressive(directive: AvatarDirective, user_text: str) -> AvatarDirective:
    """Keep live avatar reactions visible even when a model omits or defaults its directive."""
    text = (user_text or "").lower()
    emotion = directive.emotion
    if emotion == "neutral":
        if any(marker in text for marker in ("бесит", "заеб", "злит", "ненавиж", "туп", "ошибк")):
            emotion = "annoyed"
        elif any(marker in text for marker in ("спасибо", "класс", "круто", "ура", "молодец", "ахах", "смеш")):
            emotion = "happy"
        elif "?" in text or text.startswith(("как ", "почему ", "что ", "кто ", "где ", "когда ", "зачем ")):
            emotion = "thinking"
        else:
            emotion = "neutral"
    gesture = directive.gesture
    if gesture == "auto":
        gesture = {
            "smirk": "shrug",
            "happy": "talk",
            "sad": "shrug",
            "angry": "frustration",
            "annoyed": "frustration",
            "surprised": "surprise",
            "thinking": "question",
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
            emotion=emotion if emotion in _EMOTIONS else "neutral",
            gesture=gesture if gesture in _GESTURES else "auto",
            intensity=max(0.0, min(1.0, intensity)),
        )

    @staticmethod
    def _from_legacy_direction(value: str) -> AvatarDirective:
        text = value.lower()
        if any(word in text for word in ("саркаст", "ухмыл", "усмеш")):
            return AvatarDirective("smirk", "shrug", 0.55)
        if "кива" in text:
            return AvatarDirective("happy", "agreement", 0.7)
        if any(word in text for word in ("удив", "изум")):
            return AvatarDirective("surprised", "surprise", 0.8)
        if any(word in text for word in ("раздраж", "злоб", "серд")):
            return AvatarDirective("annoyed", "frustration", 0.65)
        if any(word in text for word in ("груст", "печал")):
            return AvatarDirective("sad", "auto", 0.65)
        if any(word in text for word in ("задум", "размыш")):
            return AvatarDirective("thinking", "thinking", 0.55)
        if any(word in text for word in ("улыб", "радост")):
            return AvatarDirective("happy", "talk", 0.7)
        return AvatarDirective()


def clean_live_reply(raw_reply: str) -> str:
    """Strip the initial control/directorial prefix before committing the reply to history."""
    parser = LiveDirectiveParser()
    _, parts = parser.feed(raw_reply)
    _, tail = parser.finish()
    return "".join([*parts, *tail]).strip()
