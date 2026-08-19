"""Generate a local, non-production listening pack for TeraTTSv2."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.backend.app.voice.providers import TTSRequest
from apps.backend.app.voice.style import VoiceStyle
from apps.backend.app.voice.teratts_provider import (
    TERATTS_MODEL_ID,
    TERATTS_REVISION,
    TeraTTSProvider,
)


CASES = (
    ("01_neutral", "Привет! Я рядом и внимательно тебя слушаю.", VoiceStyle.AUTO, 1.00, "neutral baseline"),
    ("02_calm", "Давай спокойно разберёмся, что произошло, и проверим всё по шагам.", VoiceStyle.CALM, 1.00, "calm style"),
    ("03_thoughtful_question", "Правда? Почему после запятой иногда возникает такая пауза?", VoiceStyle.THOUGHTFUL, 1.00, "thoughtful question"),
    ("04_energetic_fast", "Готово! Проверка завершена, можно начинать прямо сейчас!", VoiceStyle.ENERGETIC, 1.15, "energetic style plus faster tempo"),
    ("05_assertive", "Важно: не выключай питание во время обновления.", VoiceStyle.ASSERTIVE, 1.00, "assertive warning"),
    ("06_stress_and_ellipsis", "Мука́ закончилась, а мука осталась на столе…", VoiceStyle.AUTO, 1.00, "explicit stress and ellipsis"),
    ("07_dates_versions_terms", "Проверка завершена 5 августа 2026 года в 21:45. API и TeraTTS v2 работают.", VoiceStyle.AUTO, 1.00, "dates, time, version and technical terms"),
    ("08_slow_delivery", "Подожди немного, я внимательно проверяю длинный результат.", VoiceStyle.CALM, 0.85, "calm style plus slower tempo"),
    ("09_ru_f2_voice", "Это дополнительный женский голос TeraTTSv2.", VoiceStyle.AUTO, 1.00, "additional model voice"),
)


async def generate(model_path: Path, output_dir: Path, device: str) -> Path:
    provider = TeraTTSProvider(model_path=model_path, device=device, warmup=True)
    started = time.perf_counter()
    await provider.preload()
    rows: list[dict[str, object]] = []

    for case_id, text, style, tempo, description in CASES:
        voice = "ru_f2" if case_id == "09_ru_f2_voice" else "ru_f1"
        request = TTSRequest(
            text=text,
            language="ru",
            voice=voice,
            style=style,
            tempo=tempo,
        )
        chunks = [chunk async for chunk in provider.stream(request)]
        if len(chunks) != 1 or not chunks[0].is_final:
            raise RuntimeError(f"Expected one final WAV segment for {case_id}")
        path = output_dir / f"{case_id}.wav"
        path.write_bytes(chunks[0].data)
        rows.append({
            "id": case_id,
            "file": path.name,
            "text": text,
            "voice": voice,
            "style": style.value,
            "tempo": tempo,
            "description": description,
            "metadata": chunks[0].metadata,
            "sha256": hashlib.sha256(chunks[0].data).hexdigest(),
            "bytes": len(chunks[0].data),
        })

    manifest = {
        "provider": "teratts",
        "model": TERATTS_MODEL_ID,
        "revision": TERATTS_REVISION,
        "device": device,
        "sample_rate": 44100,
        "channels": 1,
        "sample_width": 2,
        "generated_seconds": round(time.perf_counter() - started, 3),
        "cases": rows,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("output/tts-model-comparison/TeraTTSv2-listening-pack"))
    parser.add_argument("--device", choices=("cpu", "auto"), default="cpu")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(asyncio.run(generate(args.model_path, args.output_dir, args.device)))
