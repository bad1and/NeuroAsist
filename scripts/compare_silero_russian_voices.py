"""Generate a listening pack for the existing Russian Silero TTS stack."""

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

from apps.backend.app.voice.providers import SileroTTSProvider


OUTPUT_DIR = ROOT / "output" / "tts-model-comparison" / "Silero-Russian-Comparison"
CASES = [
    (
        "greeting",
        "Мягкое приветствие",
        "Привет. Я рядом. Расскажешь, как у тебя дела?",
    ),
    (
        "stress",
        "Русские ударения и омографы",
        "Я поняла, что он купил новый замок, а потом взял муку. Мука закончилась, а мука осталась на столе.",
    ),
    (
        "technical",
        "Техническая фраза",
        "Проверка завершена 5 августа 2026 года в 21:45. Видеокарта GTX 1660 SUPER имеет 6 гигабайт VRAM; API ответил за 187 миллисекунд, а версия приложения — 0.5.3.",
    ),
]
VOICES = ("xenia", "baya", "kseniya")


async def main_async(device: str) -> None:
    parser_output = OUTPUT_DIR
    parser_output.mkdir(parents=True, exist_ok=True)
    provider = SileroTTSProvider(
        speaker="xenia",
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
    for voice in VOICES:
        for case_id, label, text in CASES:
            output_path = parser_output / f"{voice}_{case_id}.wav"
            started = time.perf_counter()
            result = await provider.synthesize(text, voice, output_path)
            generation_seconds = time.perf_counter() - started
            rows.append(
                {
                    "voice": voice,
                    "case_id": case_id,
                    "label": label,
                    "text": text,
                    "audio": output_path.name,
                    "generation_seconds": round(generation_seconds, 4),
                    "audio_duration_seconds": round(result.audio_duration_seconds or 0.0, 4),
                    "rtf": round(
                        generation_seconds / max(result.audio_duration_seconds or 0.0, 1e-6),
                        4,
                    ),
                    "provider_metadata": provider.metadata,
                }
            )
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)

    manifest = {
        "provider": "silero",
        "model": provider.model_name,
        "device": provider.metadata["device"],
        "load_seconds": round(load_seconds, 4),
        "stress": provider.metadata["stress"],
        "samples": rows,
    }
    (parser_output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    cards = []
    for row in rows:
        cards.append(
            f"<article><h2>{html.escape(str(row['voice']))} — {html.escape(str(row['label']))}</h2>"
            f"<audio controls preload=\"metadata\" src=\"Silero-Russian-Comparison/{html.escape(str(row['audio']))}\"></audio>"
            f"<p>{html.escape(str(row['text']))}</p>"
            f"<p class=\"muted\">RTF {row['rtf']:.3f} · {row['audio_duration_seconds']:.2f} с аудио</p></article>"
        )
    page = f"""<!doctype html>
<html lang=\"ru\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Silero Russian voices</title>
<style>body{{max-width:920px;margin:32px auto;padding:0 20px;background:#17131b;color:#f8eef8;font-family:system-ui,sans-serif}}article{{background:#241c28;border:1px solid #4b3850;border-radius:16px;padding:16px;margin:14px 0}}audio{{width:100%}}p{{line-height:1.5}}.muted{{color:#d3c2d4}}</style></head>
<body><h1>Silero: русские женские голоса</h1><p>Здесь работает штатная нормализация русского текста и stress accentor проекта. Сравни возраст, естественность и ударения.</p>{''.join(cards)}</body></html>"""
    page_path = parser_output.parent / "listen_silero_russian_voices.html"
    page_path.write_text(page, encoding="utf-8")
    print(f"Listen page: {page_path}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    args = parser.parse_args()
    asyncio.run(main_async(args.device))


if __name__ == "__main__":
    main()
