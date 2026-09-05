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


_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?…])(?:[\"'»)]*)\s+")


def pause_after_ms(text: str, *, forced_clause_split: bool = False) -> int:
    stripped = text.rstrip()
    if forced_clause_split or stripped.endswith((",", ";", ":")):
        return 60
    if stripped.endswith("…") or stripped.endswith("..."):
        return 160
    if "\n\n" in text:
        return 180
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
    return SpeechSegment(
        text=text.strip(),
        pace=pace,
        tempo=tempo,
        emphasis=emphasis,
        pause_before_ms=35 if emphasis is SpeechEmphasis.LIGHT else 0,
        pause_after_ms=pause_after_ms(text, forced_clause_split=forced_clause_split),
        sequence=sequence,
        motion_gesture=directive.gesture if directive is not None else "auto",
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
    _VOICE_TAG_RE = re.compile(
        r"^\[\[voice\s+pace=(?P<pace>[a-z_]+)\s+emphasis=(?P<emphasis>[a-z_]+)(?:\s+gesture=(?P<gesture>[a-z_]+))?\s*\]\]$",
        re.IGNORECASE,
    )

    def __init__(self, max_directives: int = 16, max_motion_directives: int = 16) -> None:
        self._buffer = ""
        self._discarding_tag = False
        self._max_directives = max(0, max_directives)
        self._max_motion_directives = max(0, max_motion_directives)
        self._accepted = 0
        self._accepted_motion = 0

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

            if raw_tag_lower.startswith("[[avatar"):
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

            if raw_tag_lower.startswith("[[voice"):
                if self._accepted >= self._max_directives:
                    continue
                match = self._VOICE_TAG_RE.match(raw_tag)
                self._accepted += 1
                if match is None:
                    output.append(VoiceDirective())
                    continue
                gesture = (match.group("gesture") or "auto").lower()
                if gesture != "auto":
                    if self._accepted_motion >= self._max_motion_directives:
                        gesture = "auto"
                    else:
                        self._accepted_motion += 1
                output.append(VoiceDirective(
                    coerce_speech_pace(match.group("pace").lower()),
                    coerce_speech_emphasis(match.group("emphasis").lower()),
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
    result = re.sub(r"\[\[(?:avatar|voice)\s+[^\]]+\]\]", "", result, flags=re.IGNORECASE)
    return result.strip()


def resequence(segments: Iterable[SpeechSegment]) -> list[SpeechSegment]:
    return [segment.with_sequence(index) for index, segment in enumerate(segments)]
