"""Generate a listening pack for reducing perceived Baya roboticness."""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from apps.backend.app.voice.providers import SileroTTSProvider
from apps.backend.app.voice.style import VoiceStyle


OUTPUT_DIR = ROOT / "output" / "tts-model-comparison" / "Baya-Naturalness-Comparison"
TEXT = (
    "Привет. Я рядом. Можешь спокойно рассказать, что случилось? "
    "Я всё выслушаю и постараюсь помочь."
)

VARIANTS = [
    {
        "variant_id": "current",
        "label": "Текущий вариант",
        "description": "Обычный стиль, адаптивная просодия включена.",
        "adaptive_prosody": True,
        "expression_level": "natural",
        "style": VoiceStyle.NORMAL,
    },
    {
        "variant_id": "plain",
        "label": "Ровнее и естественнее",
        "description": "Без дополнительных SSML-пауз между смысловыми частями.",
        "adaptive_prosody": False,
        "expression_level": "natural",
        "style": VoiceStyle.NORMAL,
    },
    {
        "variant_id": "soft",
        "label": "Мягкая подача",
        "description": "Без адаптивных пауз, с более спокойной подачей.",
        "adaptive_prosody": False,
        "expression_level": "minimal",
        "style": VoiceStyle.CALM,
    },
    {
        "variant_id": "calm",
        "label": "Спокойный разговор",
        "description": "Сохранены естественные паузы, но темп подачи спокойнее.",
        "adaptive_prosody": True,
        "expression_level": "minimal",
        "style": VoiceStyle.CALM,
    },
]


async def main_async(device: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    provider = SileroTTSProvider(
        speaker="baya",
        sample_rate=48000,
        device=device,
        stress_enabled=True,
        audio_postprocessing_enabled=True,
        adaptive_prosody=True,
    )
    started = time.perf_counter()
    await provider.preload()
    load_seconds = time.perf_counter() - started

    rows: list[dict[str, object]] = []
    for variant in VARIANTS:
        provider.adaptive_prosody = bool(variant["adaptive_prosody"])
        provider.set_expression_level(str(variant["expression_level"]))
        output_path = OUTPUT_DIR / f"baya_{variant['variant_id']}.wav"
        started = time.perf_counter()
        result = await provider.synthesize(TEXT, "baya", output_path, variant["style"])
        generation_seconds = time.perf_counter() - started
        row = {
            "variant_id": variant["variant_id"],
            "label": variant["label"],
            "description": variant["description"],
            "audio": output_path.name,
            "style": str(variant["style"]),
            "adaptive_prosody": variant["adaptive_prosody"],
            "expression_level": variant["expression_level"],
            "generation_seconds": round(generation_seconds, 4),
            "audio_duration_seconds": round(result.audio_duration_seconds or 0.0, 4),
            "rtf": round(
                generation_seconds / max(result.audio_duration_seconds or 0.0, 1e-6),
                4,
            ),
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
        cards.append(
            f"<article><h2>{html.escape(str(row['label']))}</h2>"
            f"<p>{html.escape(str(row['description']))}</p>"
            f"<audio controls preload=\"metadata\" src=\"Baya-Naturalness-Comparison/{html.escape(str(row['audio']))}\"></audio>"
            f"<p class=\"muted\">{html.escape(str(row['style']))} · RTF {row['rtf']:.3f}</p></article>"
        )
    page = f"""<!doctype html>
<html lang=\"ru\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Baya naturalness comparison</title>
<style>body{{max-width:920px;margin:32px auto;padding:0 20px;background:#17131b;color:#f8eef8;font-family:system-ui,sans-serif}}article{{background:#241c28;border:1px solid #4b3850;border-radius:16px;padding:16px;margin:14px 0}}audio{{width:100%}}p{{line-height:1.5}}.muted{{color:#d3c2d4}}</style></head>
<body><h1>Baya: естественность подачи</h1><p>{html.escape(TEXT)}</p><p>Сравни варианты по роботичности, паузам и живости. Ударения во всех вариантах обрабатываются одинаково.</p>{''.join(cards)}</body></html>"""
    page_path = OUTPUT_DIR.parent / "listen_baya_naturalness.html"
    page_path.write_text(page, encoding="utf-8")
    print(f"Listen page: {page_path}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    args = parser.parse_args()
    asyncio.run(main_async(args.device))


if __name__ == "__main__":
    main()
