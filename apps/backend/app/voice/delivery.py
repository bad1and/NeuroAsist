"""Provider-independent, restrained speech delivery planning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class SpeechPace(StrEnum):
    SLOW = "slow"
    NORMAL = "normal"
    FAST = "fast"


class SpeechEmphasis(StrEnum):
    NONE = "none"
    LIGHT = "light"
    STRONG = "strong"


BASE_TEMPO = {
    SpeechPace.SLOW: 0.98,
    SpeechPace.NORMAL: 1.0,
    SpeechPace.FAST: 1.02,
}
MIN_SPEECH_TEMPO = 0.70
MAX_SPEECH_TEMPO = 1.30
OVERRIDE_TEMPO = {
    SpeechPace.SLOW: 0.95,
    SpeechPace.NORMAL: 1.0,
    SpeechPace.FAST: 1.05,
}


def coerce_speech_pace(value: object) -> SpeechPace:
    try:
        return SpeechPace(str(value or SpeechPace.NORMAL))
    except ValueError:
        return SpeechPace.NORMAL


def coerce_speech_emphasis(value: object) -> SpeechEmphasis:
    try:
        return SpeechEmphasis(str(value or SpeechEmphasis.NONE))
    except ValueError:
        return SpeechEmphasis.NONE


@dataclass(frozen=True, slots=True)
class VoiceDirective:
    pace: SpeechPace = SpeechPace.NORMAL
    emphasis: SpeechEmphasis = SpeechEmphasis.NONE
    speed: float | None = None
    pause_before_ms: int | None = None
    pause_after_ms: int | None = None
    gesture: str = "auto"
    emotion: str | None = None
    emotion_intensity: float | None = None


@dataclass(frozen=True, slots=True)
class SpeechSegment:
    text: str
    pace: SpeechPace = SpeechPace.NORMAL
    tempo: float = 1.0
    emphasis: SpeechEmphasis = SpeechEmphasis.NONE
    pause_after_ms: int = 100
    sequence: int = 0
    pause_before_ms: int = 0
    motion_gesture: str = "auto"
    emotion: str | None = None
    emotion_intensity: float | None = None

    def with_sequence(self, sequence: int) -> "SpeechSegment":
        return SpeechSegment(
            text=self.text,
            pace=self.pace,
            tempo=self.tempo,
            emphasis=self.emphasis,
            pause_after_ms=self.pause_after_ms,
            sequence=sequence,
            pause_before_ms=self.pause_before_ms,
            motion_gesture=self.motion_gesture,
            emotion=self.emotion,
            emotion_intensity=self.emotion_intensity,
        )


_SENTENCE_BOUNDARY_RE = re.compile(r"(?:(?<=[.!?…])(?:[\"'»)]*)[ \t]+|\n+)")
_MAX_EXPLICIT_PAUSE_MS = 1_200
_NAMED_PAUSES_MS = {"none": 0, "short": 180, "medium": 350, "long": 650}


def pause_after_ms(text: str, *, forced_clause_split: bool = False) -> int:
    stripped = text.rstrip()
    if "\n\n" in text:
        return 220
    if stripped.endswith(("…", "...")):
        return 220
    if stripped.endswith(("—", "–", ";")):
        return 130
    if stripped.endswith(":"):
        return 105
    if forced_clause_split or stripped.endswith(","):
        return 75
    if stripped.endswith(("?", "!")):
        return 145
    if stripped.endswith("."):
        return 120
    return 100


def split_spoken_sentences(text: str) -> list[str]:
    """Split only at stable sentence boundaries while retaining punctuation."""
    normalized = re.sub(r"[ \t]+", " ", text).strip()
    if not normalized:
        return []
    return [part.strip() for part in _SENTENCE_BOUNDARY_RE.split(normalized) if part.strip()]


def make_speech_segment(
    text: str,
    *,
    sequence: int = 0,
    base_pace: SpeechPace | str = SpeechPace.NORMAL,
    directive: VoiceDirective | None = None,
    forced_clause_split: bool = False,
) -> SpeechSegment:
    pace = directive.pace if directive is not None else coerce_speech_pace(base_pace)
    emphasis = directive.emphasis if directive is not None else SpeechEmphasis.NONE
    tempo = (
        max(MIN_SPEECH_TEMPO, min(MAX_SPEECH_TEMPO, float(directive.speed)))
        if directive is not None and directive.speed is not None
        else OVERRIDE_TEMPO[pace] if directive is not None else BASE_TEMPO[pace]
    )
    if directive is not None and directive.speed is None:
        if emphasis is SpeechEmphasis.LIGHT:
            tempo *= 0.97
        elif emphasis is SpeechEmphasis.STRONG:
            tempo *= 0.92
    tempo = max(MIN_SPEECH_TEMPO, min(MAX_SPEECH_TEMPO, tempo))
    motion_gesture = directive.gesture if directive is not None and directive.gesture and directive.gesture != "auto" else None
    if motion_gesture is None:
        if directive is not None and directive.emotion in ("pouting", "wink", "wink_left", "teasing", "sleepy"):
            motion_gesture = "none"
        else:
            from apps.backend.app.voice.directives import infer_animation_directive
            inferred = infer_animation_directive(None, text)
            if inferred.gesture and inferred.gesture not in ("auto", "talk_right", "talk"):
                motion_gesture = inferred.gesture
            else:
                motion_gesture = "talk_right" if sequence == 0 else "none"

    return SpeechSegment(
        text=text.strip(),
        pace=pace,
        tempo=tempo,
        emphasis=emphasis,
        pause_before_ms=(
            directive.pause_before_ms
            if directive is not None and directive.pause_before_ms is not None
            else 80 if emphasis is SpeechEmphasis.STRONG else 35 if emphasis is SpeechEmphasis.LIGHT else 0
        ),
        pause_after_ms=(
            directive.pause_after_ms
            if directive is not None and directive.pause_after_ms is not None
            else pause_after_ms(text, forced_clause_split=forced_clause_split)
        ),
        sequence=sequence,
        motion_gesture=motion_gesture,
        emotion=directive.emotion if directive is not None else None,
        emotion_intensity=directive.emotion_intensity if directive is not None else None,
    )


def plan_speech(text: str, delivery=None) -> list[SpeechSegment]:
    """Build a deterministic batch plan from Character Protocol delivery cues and inline directives."""
    # First extract any inline directives
    parser = LiveVoiceDirectiveParser(max_directives=64, max_motion_directives=64)
    tokens = [*parser.feed(text), *parser.finish()]

    # Collect sentences while associating with the current active directive
    sentences_with_directives: list[tuple[str, VoiceDirective | None]] = []
    current_directive: VoiceDirective | None = None

    for item in tokens:
        if isinstance(item, VoiceDirective):
            current_directive = item
        elif isinstance(item, str) and item.strip():
            for sentence in split_spoken_sentences(item):
                sentences_with_directives.append((sentence, current_directive))

    if not sentences_with_directives:
        clean = clean_voice_directives(text)
        sentences = split_spoken_sentences(clean)
        sentences_with_directives = [(s, None) for s in sentences]

    if not sentences_with_directives:
        return []

    base_pace = coerce_speech_pace(getattr(delivery, "pace", SpeechPace.NORMAL))
    overrides = {
        int(item.segment): VoiceDirective(
            coerce_speech_pace(item.pace),
            coerce_speech_emphasis(item.emphasis),
            getattr(item, "speed", None),
            getattr(item, "pause_before_ms", None),
            getattr(item, "pause_after_ms", None),
        )
        for item in list(getattr(delivery, "overrides", ()) or ())[:3]
        if 1 <= int(item.segment) <= len(sentences_with_directives)
    }

    segments: list[SpeechSegment] = []
    for index, (sentence, directive) in enumerate(sentences_with_directives, start=1):
        override = overrides.get(index)
        effective_directive = directive
        if override is not None:
            effective_directive = VoiceDirective(
                pace=override.pace,
                emphasis=override.emphasis,
                speed=override.speed,
                pause_before_ms=override.pause_before_ms,
                pause_after_ms=override.pause_after_ms,
                gesture=directive.gesture if directive is not None else "auto",
                emotion=directive.emotion if directive is not None else None,
                emotion_intensity=directive.emotion_intensity if directive is not None else None,
            )
        segments.append(
            make_speech_segment(
                sentence,
                sequence=index - 1,
                base_pace=base_pace,
                directive=effective_directive,
            )
        )
    return segments


class LiveVoiceDirectiveParser:
    """Strip interleaved voice and avatar tags and emit fragment-safe control events."""

    _START = "[["
    _MAX_TAG = 192
    _VOICE_TAG_RE = re.compile(r"^\[\[voice(?P<body>(?:\s+[a-z_]+=[a-z0-9_.-]+)*)\s*\]\]$", re.IGNORECASE)
    _VOICE_ATTR_RE = re.compile(r"(?P<key>[a-z_]+)=(?P<value>[a-z0-9_.-]+)", re.IGNORECASE)
    _VOICE_KEYS = frozenset({
        "pace", "emphasis", "speed", "pause", "pause_before", "pause_after", "gesture",
    })

    def __init__(self, max_directives: int = 16, max_motion_directives: int = 16) -> None:
        self._buffer = ""
        self._discarding_tag = False
        self._max_directives = max(0, max_directives)
        self._max_motion_directives = max(0, max_motion_directives)
        self._accepted = 0
        self._accepted_motion = 0

    @staticmethod
    def _parse_speed(value: str | None) -> float | None:
        if value is None:
            return None
        try:
            speed = float(value)
        except ValueError:
            return None
        return max(MIN_SPEECH_TEMPO, min(MAX_SPEECH_TEMPO, speed))

    @staticmethod
    def _parse_pause(value: str | None) -> int | None:
        if value is None:
            return None
        named = _NAMED_PAUSES_MS.get(value.lower())
        if named is not None:
            return named
        try:
            milliseconds = int(value)
        except ValueError:
            return None
        return max(0, min(_MAX_EXPLICIT_PAUSE_MS, milliseconds))

    @classmethod
    def _parse_voice_tag(cls, raw_tag: str) -> VoiceDirective:
        match = cls._VOICE_TAG_RE.match(raw_tag)
        if match is None:
            return VoiceDirective()
        body = match.group("body").strip()
        pairs = list(cls._VOICE_ATTR_RE.finditer(body))
        if body and " ".join(item.group(0) for item in pairs) != " ".join(body.split()):
            return VoiceDirective()
        attributes = {item.group("key").lower(): item.group("value") for item in pairs}
        if not set(attributes).issubset(cls._VOICE_KEYS):
            return VoiceDirective()
        pause_before = cls._parse_pause(attributes.get("pause_before"))
        if pause_before is None:
            pause_before = cls._parse_pause(attributes.get("pause"))
        return VoiceDirective(
            pace=coerce_speech_pace(attributes.get("pace")),
            emphasis=coerce_speech_emphasis(attributes.get("emphasis")),
            speed=cls._parse_speed(attributes.get("speed")),
            pause_before_ms=pause_before,
            pause_after_ms=cls._parse_pause(attributes.get("pause_after")),
            gesture=(attributes.get("gesture") or "auto").lower(),
        )

    def feed(self, delta: str) -> list[str | VoiceDirective]:
        if not delta:
            return []
        self._buffer += delta
        return self._drain(final=False)

    def finish(self) -> list[str | VoiceDirective]:
        return self._drain(final=True)

    def _drain(self, *, final: bool) -> list[str | VoiceDirective]:
        output: list[str | VoiceDirective] = []
        while self._buffer:
            if self._discarding_tag:
                end = self._buffer.find("]]")
                if end < 0:
                    self._buffer = ""
                    break
                self._buffer = self._buffer[end + 2 :]
                self._discarding_tag = False
                continue

            lowered = self._buffer.lower()
            start = lowered.find(self._START)
            if start < 0:
                # Retain a possible split prefix such as `[` or `[[` at end of buffer
                keep = 0
                if not final:
                    if self._buffer.endswith("["):
                        keep = 1
                    if keep:
                        visible = self._buffer[:-keep]
                        if visible:
                            output.append(visible)
                        self._buffer = self._buffer[-keep:]
                        break
                output.append(self._buffer)
                self._buffer = ""
                break

            if start > 0:
                output.append(self._buffer[:start])
                self._buffer = self._buffer[start:]
                continue

            # Buffer starts with "[["
            end = self._buffer.find("]]", len(self._START))
            if end < 0:
                if not final and len(self._buffer) <= self._MAX_TAG:
                    break
                # A malformed or overlong machine tag is never visible/spoken
                self._buffer = ""
                self._discarding_tag = not final
                continue

            raw_tag = self._buffer[: end + 2]
            self._buffer = self._buffer[end + 2 :]
            raw_tag_lower = raw_tag.lower()

            if any(raw_tag_lower.startswith(p) for p in ("[[avatar", "[avatar", "[[anim", "[anim", "[[gesture", "[gesture")):
                from apps.backend.app.voice.directives import parse_avatar_directive
                avatar_dir = parse_avatar_directive(raw_tag)
                if self._accepted < self._max_directives:
                    self._accepted += 1
                    gesture = avatar_dir.gesture
                    if gesture != "auto":
                        if self._accepted_motion >= self._max_motion_directives:
                            gesture = "auto"
                        else:
                            self._accepted_motion += 1
                    output.append(VoiceDirective(
                        gesture=gesture,
                        emotion=avatar_dir.emotion.value,
                        emotion_intensity=avatar_dir.intensity,
                    ))
                continue

            if raw_tag_lower.startswith("[[voice") or raw_tag_lower.startswith("[voice"):
                if self._accepted >= self._max_directives:
                    continue
                self._accepted += 1
                directive = self._parse_voice_tag(raw_tag)
                gesture = directive.gesture
                if gesture != "auto":
                    if self._accepted_motion >= self._max_motion_directives:
                        gesture = "auto"
                    else:
                        self._accepted_motion += 1
                output.append(VoiceDirective(
                    pace=directive.pace,
                    emphasis=directive.emphasis,
                    speed=directive.speed,
                    pause_before_ms=directive.pause_before_ms,
                    pause_after_ms=directive.pause_after_ms,
                    gesture=gesture,
                ))
                continue

            # Any other [[...]] machine tag is dropped from speech/display
            continue
        return [item for item in output if not isinstance(item, str) or item]


def clean_voice_directives(text: str) -> str:
    parser = LiveVoiceDirectiveParser(max_directives=99, max_motion_directives=99)
    parts = [*parser.feed(text), *parser.finish()]
    result = "".join(item for item in parts if isinstance(item, str))
    result = re.sub(r"\[\[?(?:avatar|voice|anim|gesture)\b[^\]]+\]\]?", "", result, flags=re.IGNORECASE)
    return result.strip()


def resequence(segments: Iterable[SpeechSegment]) -> list[SpeechSegment]:
    return [segment.with_sequence(index) for index, segment in enumerate(segments)]
