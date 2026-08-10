"""Generate a listening test for per-sentence Baya speed control."""

from __future__ import annotations

import argparse
import asyncio
import html
import io
import json
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from apps.backend.app.schemas.character import DeliveryCue, DeliveryOverride
from apps.backend.app.voice.delivery import plan_speech
from apps.backend.app.voice.providers import SileroTTSProvider, TTSRequest
from apps.backend.app.voice.style import VoiceStyle


OUTPUT_DIR = ROOT / "output" / "tts-model-comparison" / "Baya-Sentence-Pacing"
TEXT = "Сейчас я скажу это медленно. А эту часть произнесу в обычном темпе. И последнюю фразу скажу быстрее."

CASES = [
    {
        "case_id": "all_normal",
        "label": "Вся реплика в обычном темпе",
        "delivery": DeliveryCue(pace="normal"),
    },
    {
        "case_id": "mixed_precise",
        "label": "Медленно → обычно → быстро",
        "delivery": DeliveryCue(
            pace="normal",
            overrides=[
                DeliveryOverride(segment=1, pace="normal", speed=0.72),
                DeliveryOverride(segment=3, pace="normal", speed=1.28),
            ],
        ),
    },
    {
        "case_id": "mixed_named",
        "label": "Медленно → обычно → быстро по режимам",
        "delivery": DeliveryCue(
            pace="normal",
            overrides=[
                DeliveryOverride(segment=1, pace="slow"),
                DeliveryOverride(segment=3, pace="fast"),
            ],
        ),
    },
]


async def render_case(provider: SileroTTSProvider, delivery: DeliveryCue, output_path: Path) -> list[dict[str, object]]:
    segments = plan_speech(TEXT, delivery)
    parts: list[bytes] = []
    params: tuple[int, int, int] | None = None
    details: list[dict[str, object]] = []
    for segment in segments:
        request = TTSRequest(
            text=segment.text,
            language="ru",
            voice="baya",
            style=VoiceStyle.NORMAL,
            tempo=segment.tempo,
            pause_before_ms=segment.pause_before_ms,
            pause_after_ms=segment.pause_after_ms,
        )
        chunks = [chunk.data async for chunk in provider.stream(request) if chunk.data]
        with wave.open(io.BytesIO(b"".join(chunks)), "rb") as source:
            current = (source.getnchannels(), source.getsampwidth(), source.getframerate())
            if params is None:
                params = current
            if current != params:
                raise RuntimeError("TTS segments use incompatible WAV formats")
            parts.append(source.readframes(source.getnframes()))
        details.append({"text": segment.text, "tempo": segment.tempo})
    assert params is not None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as target:
        target.setnchannels(params[0])
        target.setsampwidth(params[1])
        target.setframerate(params[2])
        target.writeframes(b"".join(parts))
    return details


async def main_async(device: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    provider = SileroTTSProvider(
        speaker="baya",
        sample_rate=48000,
        device=device,
        stress_enabled=True,
        audio_postprocessing_enabled=True,
        adaptive_prosody=False,
    )
    started = time.perf_counter()
    await provider.preload()
    load_seconds = time.perf_counter() - started

    rows: list[dict[str, object]] = []
    for case in CASES:
        output_path = OUTPUT_DIR / f"baya_{case['case_id']}.wav"
        started = time.perf_counter()
        details = await render_case(provider, case["delivery"], output_path)
        generation_seconds = time.perf_counter() - started
        with wave.open(str(output_path), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
        row = {
            "case_id": case["case_id"],
            "label": case["label"],
            "audio": output_path.name,
            "segments": details,
            "generation_seconds": round(generation_seconds, 4),
            "audio_duration_seconds": round(duration, 4),
            "rtf": round(generation_seconds / max(duration, 1e-6), 4),
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    manifest = {
        "provider": "silero",
        "model": provider.model_name,
        "speaker": "baya",
        "device": provider.metadata["device"],
        "stress": provider.metadata["stress"],
        "text": TEXT,
        "load_seconds": round(load_seconds, 4),
        "samples": rows,
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    cards = []
    for row in rows:
        tempo_text = " → ".join(str(item["tempo"]) for item in row["segments"])
        cards.append(
            f"<article><h2>{html.escape(str(row['label']))}</h2>"
            f"<audio controls preload=\"metadata\" src=\"Baya-Sentence-Pacing/{html.escape(str(row['audio']))}\"></audio>"
            f"<p class=\"muted\">Скорости предложений: {html.escape(tempo_text)} · RTF {row['rtf']:.3f}</p></article>"
        )
    page = f"""<!doctype html>
<html lang=\"ru\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Baya sentence pacing</title>
<style>body{{max-width:920px;margin:32px auto;padding:0 20px;background:#17131b;color:#f8eef8;font-family:system-ui,sans-serif}}article{{background:#241c28;border:1px solid #4b3850;border-radius:16px;padding:16px;margin:14px 0}}audio{{width:100%}}p{{line-height:1.5}}.muted{{color:#d3c2d4}}</style></head>
<body><h1>Baya: скорость по предложениям</h1><p>{html.escape(TEXT)}</p><p>Во втором и третьем вариантах темп меняется внутри одной реплики.</p>{''.join(cards)}</body></html>"""
    page_path = OUTPUT_DIR.parent / "listen_baya_sentence_pacing.html"
    page_path.write_text(page, encoding="utf-8")
    print(f"Listen page: {page_path}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    args = parser.parse_args()
    asyncio.run(main_async(args.device))


if __name__ == "__main__":
    main()
