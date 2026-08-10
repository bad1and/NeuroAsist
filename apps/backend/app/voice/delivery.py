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


@dataclass(frozen=True, slots=True)
class SpeechSegment:
    text: str
    pace: SpeechPace = SpeechPace.NORMAL
    tempo: float = 1.0
    emphasis: SpeechEmphasis = SpeechEmphasis.NONE
    pause_after_ms: int = 100
    sequence: int = 0
    pause_before_ms: int = 0

    def with_sequence(self, sequence: int) -> "SpeechSegment":
        return SpeechSegment(
            text=self.text,
            pace=self.pace,
            tempo=self.tempo,
            emphasis=self.emphasis,
            pause_after_ms=self.pause_after_ms,
            sequence=sequence,
            pause_before_ms=self.pause_before_ms,
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
    )


def plan_speech(text: str, delivery=None) -> list[SpeechSegment]:
    """Build a deterministic batch plan from Character Protocol delivery cues."""
    sentences = split_spoken_sentences(text)
    if not sentences:
        return []
    base_pace = coerce_speech_pace(getattr(delivery, "pace", SpeechPace.NORMAL))
    overrides = {
        int(item.segment): VoiceDirective(
            coerce_speech_pace(item.pace),
            coerce_speech_emphasis(item.emphasis),
            getattr(item, "speed", None),
        )
        for item in list(getattr(delivery, "overrides", ()) or ())[:3]
        if 1 <= int(item.segment) <= len(sentences)
    }
    return [
        make_speech_segment(
            sentence,
            sequence=index - 1,
            base_pace=base_pace,
            directive=overrides.get(index),
        )
        for index, sentence in enumerate(sentences, start=1)
    ]


class LiveVoiceDirectiveParser:
    """Strip interleaved voice tags and emit fragment-safe control events."""

    _START = "[[voice"
    _MAX_TAG = 128
    _TAG_RE = re.compile(
        r"^\[\[voice\s+pace=(?P<pace>[a-z_]+)\s+emphasis=(?P<emphasis>[a-z_]+)\s*\]\]$",
        re.IGNORECASE,
    )

    def __init__(self, max_directives: int = 3) -> None:
        self._buffer = ""
        self._discarding_tag = False
        self._max_directives = max(0, max_directives)
        self._accepted = 0

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
                # Retain a possible split prefix such as ``[[voi``.
                keep = 0
                if not final:
                    for size in range(1, min(len(self._buffer), len(self._START) - 1) + 1):
                        if self._START.startswith(lowered[-size:]):
                            keep = size
                    if keep:
                        visible = self._buffer[:-keep]
                        if visible:
                            output.append(visible)
                        self._buffer = self._buffer[-keep:]
                        break
                output.append(self._buffer)
                self._buffer = ""
                break
            if start:
                output.append(self._buffer[:start])
                self._buffer = self._buffer[start:]
                continue
            end = self._buffer.find("]]", len(self._START))
            if end < 0:
                if not final and len(self._buffer) <= self._MAX_TAG:
                    break
                # A malformed or overlong machine tag is never visible/spoken.
                self._buffer = ""
                self._discarding_tag = not final
                continue
            raw_tag = self._buffer[: end + 2]
            self._buffer = self._buffer[end + 2 :]
            if self._accepted >= self._max_directives:
                continue
            match = self._TAG_RE.match(raw_tag)
            self._accepted += 1
            if match is None:
                output.append(VoiceDirective())
                continue
            output.append(
                VoiceDirective(
                    coerce_speech_pace(match.group("pace").lower()),
                    coerce_speech_emphasis(match.group("emphasis").lower()),
                )
            )
        return [item for item in output if not isinstance(item, str) or item]


def clean_voice_directives(text: str) -> str:
    parser = LiveVoiceDirectiveParser()
    parts = [*parser.feed(text), *parser.finish()]
    return "".join(item for item in parts if isinstance(item, str)).strip()


def resequence(segments: Iterable[SpeechSegment]) -> list[SpeechSegment]:
    return [segment.with_sequence(index) for index, segment in enumerate(segments)]
