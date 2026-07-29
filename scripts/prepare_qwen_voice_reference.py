"""Create the neutral, exactly transcribed Silero baya clone reference once."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.backend.app.core.config import Settings
from apps.backend.app.voice.providers import SileroTTSProvider
from apps.backend.app.voice.style import VoiceStyle


REFERENCE_TEXT = (
    "Привет. Меня зовут Селера. Я говорю спокойно, ясно и естественно, "
    "сохраняя ровный и узнаваемый голос."
)


async def create(output_path: Path) -> None:
    settings = Settings()
    provider = SileroTTSProvider(
        model=settings.voice_silero_model,
        speaker="baya",
        sample_rate=settings.voice_silero_sample_rate,
        device=settings.voice_silero_device,
        timeout_seconds=settings.voice_silero_timeout_seconds,
        adaptive_prosody=True,
        audio_postprocessing_enabled=True,
        loudness_target_dbfs=settings.voice_silero_loudness_target_dbfs,
        peak_ceiling_dbfs=settings.voice_silero_peak_ceiling_dbfs,
        highpass_cutoff_hz=settings.voice_tts_highpass_cutoff_hz,
    )
    provider.set_expression_level("minimal")
    result = await provider.synthesize(
        REFERENCE_TEXT,
        "baya",
        output_path,
        VoiceStyle.CALM,
    )
    payload = result.audio_path.read_bytes()
    manifest = {
        "speaker": "baya",
        "intensity": 3,
        "text": REFERENCE_TEXT,
        "wav": result.audio_path.name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "duration_seconds": result.audio_duration_seconds,
    }
    result.audio_path.with_suffix(".json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/voice-references/qwen-baya-neutral.wav"),
    )
    args = parser.parse_args()
    asyncio.run(create(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
