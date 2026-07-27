from __future__ import annotations

import asyncio
import json
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.backend.app.voice.providers import SileroTTSProvider

OUTPUT = ROOT / "tests" / "fixtures" / "live_audio"
SAMPLE_RATE = 16_000

CASES = (
    ("complete_question_ru", "Ирис, что ты думаешь об этом?", True, "finished Russian question"),
    ("incomplete_clause_ru", "Я хотел сказать тебе, что", False, "unfinished Russian clause"),
    ("complete_statement_ru", "Сегодня я закончил важную работу.", True, "finished statement"),
    ("no_punctuation_ru", "кажется сегодня будет дождь", True, "complete meaning without punctuation"),
    ("quiet_ending_ru", "Ты меня слышишь?", True, "quiet question ending"),
    ("noisy_question_ru", "Ирис, ответь мне, пожалуйста.", True, "speech with deterministic noise"),
    ("english_question", "Iris, what do you think about it?", True, "English control"),
    ("assistant_echo_ru", "Да, я здесь и внимательно слушаю.", True, "synthetic Iris playback echo"),
)


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as source:
        rate = source.getframerate()
        channels = source.getnchannels()
        width = source.getsampwidth()
        if width != 2:
            raise RuntimeError(f"Expected PCM16 WAV, got sample width {width}")
        samples = np.frombuffer(source.readframes(source.getnframes()), dtype=np.int16)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return samples, rate


def resample(samples: np.ndarray, source_rate: int) -> np.ndarray:
    if source_rate == SAMPLE_RATE:
        return samples
    length = max(1, round(len(samples) * SAMPLE_RATE / source_rate))
    positions = np.linspace(0, len(samples) - 1, length)
    return np.interp(positions, np.arange(len(samples)), samples).astype(np.int16)


def write_wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(SAMPLE_RATE)
        target.writeframes(samples.astype("<i2").tobytes())


async def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    provider = SileroTTSProvider(
        speaker="xenia",
        sample_rate=24_000,
        device="cpu",
        warmup=False,
        stress_enabled=False,
        cmudict_enabled=False,
        audio_postprocessing_enabled=False,
    )
    await provider.preload()
    manifest: list[dict[str, object]] = []
    rendered: dict[str, np.ndarray] = {}
    for name, transcript, complete, purpose in CASES:
        temporary = OUTPUT / f".{name}.source.wav"
        await provider.synthesize(transcript, "xenia", temporary)
        samples, rate = read_wav(temporary)
        temporary.unlink(missing_ok=True)
        samples = resample(samples, rate)
        if name == "quiet_ending_ru":
            fade = np.ones(len(samples), dtype=np.float32)
            tail = min(len(samples), SAMPLE_RATE)
            fade[-tail:] = np.linspace(1.0, 0.12, tail)
            samples = (samples * fade).astype(np.int16)
        if name == "noisy_question_ru":
            rng = np.random.default_rng(7301)
            noise = rng.normal(0, 350, len(samples))
            samples = np.clip(samples.astype(np.float32) + noise, -32768, 32767).astype(np.int16)
        rendered[name] = samples
        write_wav(OUTPUT / f"{name}.wav", samples)
        manifest.append(
            {
                "id": name,
                "file": f"{name}.wav",
                "transcript": transcript,
                "sample_rate": SAMPLE_RATE,
                "expected_complete": complete,
                "purpose": purpose,
                "synthetic": True,
            }
        )

    pause = np.zeros(round(0.35 * SAMPLE_RATE), dtype=np.int16)
    islands = np.concatenate(
        [rendered["incomplete_clause_ru"], pause, rendered["complete_statement_ru"]]
    )
    write_wav(OUTPUT / "short_pause_continuation_ru.wav", islands)
    manifest.append(
        {
            "id": "short_pause_continuation_ru",
            "file": "short_pause_continuation_ru.wav",
            "transcript": "Я хотел сказать тебе, что сегодня я закончил важную работу.",
            "sample_rate": SAMPLE_RATE,
            "expected_complete": True,
            "prefix_expected_complete": False,
            "prefix_samples": len(rendered["incomplete_clause_ru"]),
            "purpose": "two speech islands joined across a 350 ms pause",
            "synthetic": True,
        }
    )
    (OUTPUT / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "generator": "Silero v5.5 ru/xenia",
                "limitations": "Synthetic speech does not cover room acoustics or microphone AEC.",
                "fixtures": manifest,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Generated {len(manifest)} fixtures in {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
