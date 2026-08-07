"""Compare Silero's actual intensity parameter for Baya naturalness."""

from __future__ import annotations

import argparse
import asyncio
import html
import io
import json
import sys
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from apps.backend.app.voice.providers import SileroTTSProvider, make_silero_ssml, normalize_russian_tts_text
from apps.backend.app.voice.style import VoiceStyle


OUTPUT_DIR = ROOT / "output" / "tts-model-comparison" / "Baya-Intensity-Comparison"
TEXT = "Привет! Я рядом. Не спеши, расскажи, что случилось — я тебя внимательно выслушаю. Хорошо?"

VARIANTS = [
    (2, "Мягче", "Меньше выраженности, спокойнее интонация."),
    (3, "Баланс", "Текущий уровень Silero."),
    (4, "Выразительнее", "Заметнее интонационные движения."),
    (5, "Максимум", "Верхняя граница для проверки; может быть слишком театрально."),
]


def waveform_to_filtered_wav(provider: SileroTTSProvider, waveform: object) -> bytes:
    rendered, _ = provider._postprocess_speech_waveform(waveform, provider.sample_rate)
    sos = butter(4, 12000 / (provider.sample_rate / 2), btype="lowpass", output="sos")
    rendered = sosfiltfilt(sos, rendered).astype(np.float32)
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(provider.sample_rate)
        audio.writeframes((np.clip(rendered, -1.0, 1.0) * 32767).astype("<i2").tobytes())
    return output.getvalue()


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
    await provider.preload()
    normalized = normalize_russian_tts_text(
        TEXT,
        pronunciations={},
        stress_accentor=provider._stress_accentor.accent,
    )
    ssml = make_silero_ssml(
        normalized,
        VoiceStyle.NORMAL,
        provider._expression_level,
        adaptive_prosody=True,
        terminal_pause=False,
    )

    rows: list[dict[str, object]] = []
    for intensity, label, description in VARIANTS:
        with provider._torch.inference_mode():
            waveform = provider._model.apply_tts(
                ssml_text=ssml,
                speaker="baya",
                sample_rate=provider.sample_rate,
                intensity=intensity,
            )
        wav_bytes = waveform_to_filtered_wav(provider, waveform)
        output_path = OUTPUT_DIR / f"baya_intensity_{intensity}.wav"
        output_path.write_bytes(wav_bytes)
        rows.append({
            "intensity": intensity,
            "label": label,
            "description": description,
            "audio": output_path.name,
        })
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)

    manifest = {
        "provider": "silero",
        "model": provider.model_name,
        "speaker": "baya",
        "device": provider.metadata["device"],
        "stress": provider.metadata["stress"],
        "filter_cutoff_hz": 12000,
        "text": TEXT,
        "samples": rows,
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    cards = []
    for row in rows:
        cards.append(
            f"<article><h2>{html.escape(str(row['label']))} · intensity {row['intensity']}</h2>"
            f"<p>{html.escape(str(row['description']))}</p>"
            f"<audio controls preload=\"metadata\" src=\"Baya-Intensity-Comparison/{html.escape(str(row['audio']))}\"></audio></article>"
        )
    page = f"""<!doctype html>
<html lang=\"ru\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Baya intensity comparison</title>
<style>body{{max-width:920px;margin:32px auto;padding:0 20px;background:#17131b;color:#f8eef8;font-family:system-ui,sans-serif}}article{{background:#241c28;border:1px solid #4b3850;border-radius:16px;padding:16px;margin:14px 0}}audio{{width:100%}}p{{line-height:1.5}}</style></head>
<body><h1>Baya: выразительность интонации</h1><p>{html.escape(TEXT)}</p><p>Здесь меняется настоящий параметр интенсивности Silero; фильтр сипов одинаковый во всех вариантах.</p>{''.join(cards)}</body></html>"""
    page_path = OUTPUT_DIR.parent / "listen_baya_intensity.html"
    page_path.write_text(page, encoding="utf-8")
    print(f"Listen page: {page_path}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    args = parser.parse_args()
    asyncio.run(main_async(args.device))


if __name__ == "__main__":
    main()
