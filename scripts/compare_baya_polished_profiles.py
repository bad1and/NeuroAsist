"""Compare polished Baya profiles: artifact cleanup plus restrained delivery changes."""

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

import numpy as np
from scipy.signal import butter, sosfiltfilt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from apps.backend.app.voice.providers import SileroTTSProvider, apply_wav_delivery
from apps.backend.app.voice.style import VoiceStyle


OUTPUT_DIR = ROOT / "output" / "tts-model-comparison" / "Baya-Polished-Comparison"
TEXT = (
    "Привет. Я рядом. Можешь спокойно рассказать, что случилось? "
    "Я всё выслушаю и постараюсь помочь."
)

VARIANTS = [
    {
        "variant_id": "balanced",
        "label": "Чистый и ровный",
        "description": "Без искусственных смысловых пауз, темп 1.0.",
        "adaptive_prosody": False,
        "expression_level": "natural",
        "style": VoiceStyle.NORMAL,
        "tempo": 1.0,
    },
    {
        "variant_id": "slow_soft",
        "label": "Чистый и мягкий",
        "description": "Чуть медленнее и спокойнее, без лишней театральности.",
        "adaptive_prosody": False,
        "expression_level": "minimal",
        "style": VoiceStyle.CALM,
        "tempo": 0.98,
    },
    {
        "variant_id": "natural_pauses",
        "label": "С естественными паузами",
        "description": "Сохранены адаптивные паузы, но сипение убрано.",
        "adaptive_prosody": True,
        "expression_level": "natural",
        "style": VoiceStyle.NORMAL,
        "tempo": 1.0,
    },
    {
        "variant_id": "lively",
        "label": "Чуть живее",
        "description": "Немного быстрее, чтобы убрать ощущение монотонности.",
        "adaptive_prosody": True,
        "expression_level": "natural",
        "style": VoiceStyle.NORMAL,
        "tempo": 1.02,
    },
]


def filter_wav(wav_bytes: bytes, cutoff_hz: int = 12000) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as source:
        sample_rate = source.getframerate()
        samples = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    sos = butter(4, cutoff_hz / (sample_rate / 2), btype="lowpass", output="sos")
    filtered = sosfiltfilt(sos, samples).astype(np.float32)
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes((np.clip(filtered, -1.0, 1.0) * 32767).astype("<i2").tobytes())
    return output.getvalue()


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
    for variant in VARIANTS:
        provider.adaptive_prosody = bool(variant["adaptive_prosody"])
        provider.set_expression_level(str(variant["expression_level"]))
        temp_path = OUTPUT_DIR / f"_{variant['variant_id']}.wav"
        output_path = OUTPUT_DIR / f"baya_{variant['variant_id']}.wav"
        started = time.perf_counter()
        await provider.synthesize(TEXT, "baya", temp_path, variant["style"])
        source_bytes = temp_path.read_bytes()
        delivered = apply_wav_delivery(source_bytes, tempo=float(variant["tempo"]))
        output_path.write_bytes(filter_wav(delivered))
        temp_path.unlink(missing_ok=True)
        generation_seconds = time.perf_counter() - started
        duration = len(delivered) / 2 / 48000
        row = {
            "variant_id": variant["variant_id"],
            "label": variant["label"],
            "description": variant["description"],
            "audio": output_path.name,
            "tempo": variant["tempo"],
            "style": str(variant["style"]),
            "adaptive_prosody": variant["adaptive_prosody"],
            "expression_level": variant["expression_level"],
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
        "filter_cutoff_hz": 12000,
        "text": TEXT,
        "load_seconds": round(load_seconds, 4),
        "samples": rows,
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    cards = []
    for row in rows:
        cards.append(
            f"<article><h2>{html.escape(str(row['label']))}</h2>"
            f"<p>{html.escape(str(row['description']))}</p>"
            f"<audio controls preload=\"metadata\" src=\"Baya-Polished-Comparison/{html.escape(str(row['audio']))}\"></audio>"
            f"<p class=\"muted\">темп {row['tempo']} · RTF {row['rtf']:.3f}</p></article>"
        )
    page = f"""<!doctype html>
<html lang=\"ru\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Baya polished profiles</title>
<style>body{{max-width:920px;margin:32px auto;padding:0 20px;background:#17131b;color:#f8eef8;font-family:system-ui,sans-serif}}article{{background:#241c28;border:1px solid #4b3850;border-radius:16px;padding:16px;margin:14px 0}}audio{{width:100%}}p{{line-height:1.5}}.muted{{color:#d3c2d4}}</style></head>
<body><h1>Baya: чистый и более естественный голос</h1><p>{html.escape(TEXT)}</p><p>Во всех вариантах сохранены одинаковые ударения и убраны верхние сипящие артефакты.</p>{''.join(cards)}</body></html>"""
    page_path = OUTPUT_DIR.parent / "listen_baya_polished.html"
    page_path.write_text(page, encoding="utf-8")
    print(f"Listen page: {page_path}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    args = parser.parse_args()
    asyncio.run(main_async(args.device))


if __name__ == "__main__":
    main()
