"""Generate Baya samples for isolating hiss and rasp artifacts."""

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


OUTPUT_DIR = ROOT / "output" / "tts-model-comparison" / "Baya-Artifact-Comparison"
TEXT = (
    "Привет. Я рядом. Можешь спокойно рассказать, что случилось? "
    "Я всё выслушаю и постараюсь помочь."
)

VARIANTS = [
    {
        "variant_id": "current_48k",
        "label": "48 кГц, текущая обработка",
        "description": "Текущий формат приложения: постобработка и целевая громкость −18 dBFS.",
        "sample_rate": 48000,
        "postprocess": True,
    },
    {
        "variant_id": "native_24k",
        "label": "24 кГц, текущая обработка",
        "description": "Ближе к исходному формату модели; постобработка сохранена.",
        "sample_rate": 24000,
        "postprocess": True,
    },
    {
        "variant_id": "raw_48k",
        "label": "48 кГц, без постобработки",
        "description": "Сырой вывод модели без усиления и фильтров.",
        "sample_rate": 48000,
        "postprocess": False,
    },
    {
        "variant_id": "raw_24k",
        "label": "24 кГц, без постобработки",
        "description": "Сырой вывод в формате 24 кГц.",
        "sample_rate": 24000,
        "postprocess": False,
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
        adaptive_prosody=False,
    )
    started = time.perf_counter()
    await provider.preload()
    load_seconds = time.perf_counter() - started

    rows: list[dict[str, object]] = []
    for variant in VARIANTS:
        provider.sample_rate = int(variant["sample_rate"])
        provider.audio_postprocessing_enabled = bool(variant["postprocess"])
        output_path = OUTPUT_DIR / f"baya_{variant['variant_id']}.wav"
        started = time.perf_counter()
        result = await provider.synthesize(TEXT, "baya", output_path, VoiceStyle.NORMAL)
        generation_seconds = time.perf_counter() - started
        row = {
            "variant_id": variant["variant_id"],
            "label": variant["label"],
            "description": variant["description"],
            "audio": output_path.name,
            "sample_rate": variant["sample_rate"],
            "postprocess": variant["postprocess"],
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
            f"<audio controls preload=\"metadata\" src=\"Baya-Artifact-Comparison/{html.escape(str(row['audio']))}\"></audio>"
            f"<p class=\"muted\">{row['sample_rate']} Гц · RTF {row['rtf']:.3f}</p></article>"
        )
    page = f"""<!doctype html>
<html lang=\"ru\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Baya artifact comparison</title>
<style>body{{max-width:920px;margin:32px auto;padding:0 20px;background:#17131b;color:#f8eef8;font-family:system-ui,sans-serif}}article{{background:#241c28;border:1px solid #4b3850;border-radius:16px;padding:16px;margin:14px 0}}audio{{width:100%}}p{{line-height:1.5}}.muted{{color:#d3c2d4}}</style></head>
<body><h1>Baya: хрип и шипение</h1><p>{html.escape(TEXT)}</p><p>Сравни, где артефактов меньше: это поможет понять, виновата ли обработка или сам голос.</p>{''.join(cards)}</body></html>"""
    page_path = OUTPUT_DIR.parent / "listen_baya_artifacts.html"
    page_path.write_text(page, encoding="utf-8")
    print(f"Listen page: {page_path}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    args = parser.parse_args()
    asyncio.run(main_async(args.device))


if __name__ == "__main__":
    main()
