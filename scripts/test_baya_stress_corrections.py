"""Generate a Baya listening pack for automatic vs context-corrected stress."""

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

from apps.backend.app.voice.providers import SileroTTSProvider, normalize_russian_tts_text


OUTPUT_DIR = ROOT / "output" / "tts-model-comparison" / "Baya-Stress-Corrections"

CASES = [
    {
        "case_id": "lock",
        "label": "Замок на двери — нужен замок",
        "text": "На двери новый замок.",
        "override": {"На двери новый замок": "На двери новый з+амок"},
    },
    {
        "case_id": "castle",
        "label": "Старинный замок — нужен замок",
        "text": "На горе стоял старый замок.",
        "override": {"На горе стоял старый замок": "На горе стоял старый зам+ок"},
    },
    {
        "case_id": "flour",
        "label": "Продукт — нужна мука́",
        "text": "Мука закончилась.",
        "override": {"Мука закончилась": "Мук+а закончилась"},
    },
    {
        "case_id": "torment",
        "label": "Страдание — нужна му́ка",
        "text": "Он терпел страшную муку.",
        "override": {"Он терпел страшную муку": "Он терпел страшную м+уку"},
    },
]


def marked_text(provider: SileroTTSProvider, text: str, pronunciations: dict[str, str]) -> str:
    return normalize_russian_tts_text(
        text,
        transliterate_latin=False,
        pronunciations=pronunciations,
        stress_accentor=provider._stress_accentor.accent,
    )


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
    for case in CASES:
        provider.set_pronunciations({})
        automatic_path = OUTPUT_DIR / f"baya_{case['case_id']}_automatic.wav"
        started = time.perf_counter()
        automatic_result = await provider.synthesize(case["text"], "baya", automatic_path)
        automatic_seconds = time.perf_counter() - started
        automatic_marked = marked_text(provider, case["text"], {})

        provider.set_pronunciations(case["override"])
        corrected_path = OUTPUT_DIR / f"baya_{case['case_id']}_corrected.wav"
        started = time.perf_counter()
        corrected_result = await provider.synthesize(case["text"], "baya", corrected_path)
        corrected_seconds = time.perf_counter() - started
        corrected_marked = marked_text(provider, case["text"], case["override"])

        rows.append(
            {
                "case_id": case["case_id"],
                "label": case["label"],
                "text": case["text"],
                "automatic_audio": automatic_path.name,
                "corrected_audio": corrected_path.name,
                "automatic_marked": automatic_marked,
                "corrected_marked": corrected_marked,
                "automatic_rtf": round(
                    automatic_seconds / max(automatic_result.audio_duration_seconds or 0.0, 1e-6),
                    4,
                ),
                "corrected_rtf": round(
                    corrected_seconds / max(corrected_result.audio_duration_seconds or 0.0, 1e-6),
                    4,
                ),
            }
        )
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)

    manifest = {
        "provider": "silero",
        "model": provider.model_name,
        "speaker": "baya",
        "device": provider.metadata["device"],
        "stress": provider.metadata["stress"],
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
            f"<p>{html.escape(str(row['text']))}</p>"
            f"<h3>Автоматически</h3>"
            f"<audio controls preload=\"metadata\" src=\"Baya-Stress-Corrections/{html.escape(str(row['automatic_audio']))}\"></audio>"
            f"<p class=\"marked\">{html.escape(str(row['automatic_marked']))}</p>"
            f"<h3>С контекстной поправкой</h3>"
            f"<audio controls preload=\"metadata\" src=\"Baya-Stress-Corrections/{html.escape(str(row['corrected_audio']))}\"></audio>"
            f"<p class=\"marked\">{html.escape(str(row['corrected_marked']))}</p></article>"
        )
    page = f"""<!doctype html>
<html lang=\"ru\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Baya stress corrections</title>
<style>body{{max-width:920px;margin:32px auto;padding:0 20px;background:#17131b;color:#f8eef8;font-family:system-ui,sans-serif}}article{{background:#241c28;border:1px solid #4b3850;border-radius:16px;padding:16px;margin:14px 0}}audio{{width:100%}}p{{line-height:1.5}}.marked{{font-family:ui-monospace,monospace;color:#e6cce8}}h3{{margin-bottom:8px}}</style></head>
<body><h1>Baya: проверка русских ударений</h1><p>Слева автоматическое ударение, справа — контекстная поправка. Знак <code>+</code> показывает ударную гласную в подготовленном тексте.</p>{''.join(cards)}</body></html>"""
    page_path = OUTPUT_DIR.parent / "listen_baya_stress_corrections.html"
    page_path.write_text(page, encoding="utf-8")
    print(f"Listen page: {page_path}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    args = parser.parse_args()
    asyncio.run(main_async(args.device))


if __name__ == "__main__":
    main()
