"""Canonical PCM16 helpers shared by live input, uploads and STT."""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

import av

CANONICAL_SAMPLE_RATE = 16_000
CANONICAL_CHANNELS = 1
CANONICAL_SAMPLE_WIDTH = 2
CANONICAL_FORMAT = "pcm_s16le"


@dataclass(frozen=True)
class Pcm16Audio:
    data: bytes
    sample_rate: int = CANONICAL_SAMPLE_RATE
    channels: int = CANONICAL_CHANNELS

    def __post_init__(self) -> None:
        if self.sample_rate != CANONICAL_SAMPLE_RATE or self.channels != CANONICAL_CHANNELS:
            raise ValueError("STT audio must be mono PCM16 at exactly 16 kHz")
        if len(self.data) % CANONICAL_SAMPLE_WIDTH:
            raise ValueError("PCM16 data has an odd byte length")

    @property
    def duration_seconds(self) -> float:
        return len(self.data) / (self.sample_rate * CANONICAL_SAMPLE_WIDTH)

    @property
    def format(self) -> str:
        return CANONICAL_FORMAT


def _frame_pcm16_bytes(frame: av.AudioFrame) -> bytes:
    """Return the meaningful packed mono bytes without plane padding."""
    return bytes(frame.planes[0])[: frame.samples * CANONICAL_SAMPLE_WIDTH]


class StreamingPcm16Normalizer:
    """Stateful libswresample adapter.

    The resampler instance is deliberately session-scoped so fractional phase
    survives arbitrary WebSocket frame boundaries. Native 16 kHz PCM takes a
    byte-for-byte fast path and is never resampled.
    """

    def __init__(self, source_sample_rate: int) -> None:
        if not 8_000 <= source_sample_rate <= 96_000:
            raise ValueError("PCM source sample rate must be between 8 and 96 kHz")
        self.source_sample_rate = source_sample_rate
        self._passthrough = source_sample_rate == CANONICAL_SAMPLE_RATE
        self._resampler = None if self._passthrough else av.AudioResampler(
            format="s16",
            layout="mono",
            rate=CANONICAL_SAMPLE_RATE,
        )
        self._closed = False

    @property
    def passthrough(self) -> bool:
        return self._passthrough

    def feed(self, pcm16: bytes) -> bytes:
        if self._closed:
            raise RuntimeError("Audio normalizer is already closed")
        if len(pcm16) % CANONICAL_SAMPLE_WIDTH:
            raise ValueError("PCM16 frame has an odd byte length")
        if not pcm16:
            return b""
        if self._passthrough:
            return pcm16
        frame = av.AudioFrame(
            format="s16",
            layout="mono",
            samples=len(pcm16) // CANONICAL_SAMPLE_WIDTH,
        )
        frame.sample_rate = self.source_sample_rate
        frame.planes[0].update(pcm16)
        return b"".join(_frame_pcm16_bytes(item) for item in self._resampler.resample(frame))

    def flush(self) -> bytes:
        if self._closed:
            return b""
        self._closed = True
        if self._passthrough:
            return b""
        return b"".join(_frame_pcm16_bytes(item) for item in self._resampler.resample(None))


def decode_audio_file(path: Path) -> Pcm16Audio:
    """Decode an uploaded audio file and resample it exactly once."""
    output = bytearray()
    resampler = av.AudioResampler(
        format="s16",
        layout="mono",
        rate=CANONICAL_SAMPLE_RATE,
    )
    try:
        with av.open(str(path), mode="r") as container:
            streams = [stream for stream in container.streams if stream.type == "audio"]
            if not streams:
                raise ValueError("Uploaded file does not contain an audio stream")
            for frame in container.decode(streams[0]):
                for normalized in resampler.resample(frame):
                    output.extend(_frame_pcm16_bytes(normalized))
            for normalized in resampler.resample(None):
                output.extend(_frame_pcm16_bytes(normalized))
    except (av.error.FFmpegError, OSError, ValueError) as exc:
        raise RuntimeError("Could not decode uploaded audio") from exc
    if not output:
        raise RuntimeError("Decoded audio is empty")
    return Pcm16Audio(bytes(output))


def write_pcm16_wav(path: Path, audio: Pcm16Audio) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as target:
        target.setnchannels(audio.channels)
        target.setsampwidth(CANONICAL_SAMPLE_WIDTH)
        target.setframerate(audio.sample_rate)
        target.writeframes(audio.data)
