import array
import math
import wave
from pathlib import Path

import pytest

from apps.backend.app.voice.audio import (
    CANONICAL_SAMPLE_RATE,
    StreamingPcm16Normalizer,
    decode_audio_file,
)


def _tone(sample_rate: int, frequency: float, seconds: float, amplitude: float = 0.6) -> bytes:
    values = array.array(
        "h",
        (
            round(math.sin(2 * math.pi * frequency * index / sample_rate) * amplitude * 32767)
            for index in range(round(sample_rate * seconds))
        ),
    )
    return values.tobytes()


def _rms(pcm16: bytes) -> float:
    values = memoryview(pcm16).cast("h")
    return math.sqrt(sum(value * value for value in values) / max(1, len(values))) / 32768


def test_16khz_pcm_is_byte_for_byte_passthrough() -> None:
    pcm16 = _tone(16_000, 1000, .137)
    normalizer = StreamingPcm16Normalizer(16_000)

    output = normalizer.feed(pcm16[:318]) + normalizer.feed(pcm16[318:]) + normalizer.flush()

    assert output == pcm16


@pytest.mark.parametrize("source_rate", [44_100, 48_000])
def test_stateful_resampling_has_no_drift_with_irregular_frames(source_rate: int) -> None:
    pcm16 = _tone(source_rate, 2500, 2.0)
    normalizer = StreamingPcm16Normalizer(source_rate)
    output = bytearray()
    cursor = 0
    sizes = [642, 1918, 376, 2048, 990]
    while cursor < len(pcm16):
        size = sizes[(cursor // 2) % len(sizes)]
        size -= size % 2
        output.extend(normalizer.feed(pcm16[cursor:cursor + size]))
        cursor += size
    output.extend(normalizer.flush())

    assert len(output) // 2 == 2 * CANONICAL_SAMPLE_RATE


def test_resampler_preserves_voice_band_and_filters_aliases() -> None:
    useful = StreamingPcm16Normalizer(48_000)
    useful_output = useful.feed(_tone(48_000, 4000, .5)) + useful.flush()
    ultrasonic = StreamingPcm16Normalizer(48_000)
    ultrasonic_output = ultrasonic.feed(_tone(48_000, 12_000, .5)) + ultrasonic.flush()

    assert _rms(useful_output) > .20
    assert _rms(ultrasonic_output) < .03


def test_uploaded_stereo_wav_is_downmixed_once(tmp_path: Path) -> None:
    path = tmp_path / "stereo.wav"
    left = memoryview(_tone(48_000, 1000, .25)).cast("h")
    right = memoryview(_tone(48_000, 1000, .25, amplitude=0.0)).cast("h")
    interleaved = array.array("h")
    for left_sample, right_sample in zip(left, right):
        interleaved.extend((left_sample, right_sample))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(interleaved.tobytes())

    decoded = decode_audio_file(path)

    assert decoded.sample_rate == 16_000
    assert decoded.channels == 1
    assert decoded.format == "pcm_s16le"
    assert len(decoded.data) // 2 == 4_000
    assert .18 < _rms(decoded.data) < .24
