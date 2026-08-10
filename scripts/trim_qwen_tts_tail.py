"""Trim silence or a partial repeated phrase from a Qwen3-TTS WAV file."""

from __future__ import annotations

import argparse
import re
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel


def tokens(text: str) -> list[str]:
    return re.findall(r"[\wа-яё]+", text.lower(), flags=re.IGNORECASE)


def similarity(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-text", default="")
    parser.add_argument("--model", default="small")
    parser.add_argument("--language", default="ru")
    parser.add_argument("--pad-ms", type=float, default=180.0)
    args = parser.parse_args()

    audio, sample_rate = sf.read(args.input, always_2d=False)
    duration = len(audio) / sample_rate

    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        str(args.input),
        language=args.language,
        beam_size=5,
        vad_filter=False,
        condition_on_previous_text=False,
        word_timestamps=True,
    )
    segments = list(segments)
    if not segments:
        raise RuntimeError("speech recognizer returned no segments")

    expected = tokens(args.expected_text)
    selected = segments
    if expected:
        matching = [
            segment
            for segment in segments
            if similarity(expected, tokens(segment.text)) >= 0.70
        ]
        if matching:
            # Keep the first occurrence of the requested text; a later matching
            # segment is the repeated tail produced by the missing codec EOS.
            selected = [matching[0]]

    words = [word for segment in selected for word in (segment.words or [])]
    if not words:
        raise RuntimeError("speech recognizer returned no word timestamps")

    speech_end = max(float(word.end) for word in words)
    trim_seconds = min(duration, speech_end + args.pad_ms / 1000.0)
    trim_samples = max(1, min(len(audio), round(trim_seconds * sample_rate)))
    trimmed = audio[:trim_samples].copy()

    # Avoid a click when the last word ends away from a zero crossing.
    fade_samples = min(round(0.06 * sample_rate), len(trimmed))
    if fade_samples > 1:
        trimmed[-fade_samples:] *= np.linspace(1.0, 0.0, fade_samples)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(args.output, trimmed, sample_rate, subtype="PCM_16")
    print(
        f"input={args.input} output={args.output} "
        f"original_seconds={duration:.3f} trimmed_seconds={len(trimmed) / sample_rate:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
