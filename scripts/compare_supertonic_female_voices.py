"""Generate an A/B listening pack for Supertonic 3 built-in female voices."""

from __future__ import annotations

import argparse
import html
import io
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.backend.app.voice.providers import apply_wav_delivery, waveform_to_wav_bytes


DEFAULT_MODEL_DIR = Path.home() / ".cache" / "supertonic3"
OUTPUT_DIR = ROOT / "output" / "tts-model-comparison" / "Iris-Voice-Comparison"
TEXT = "Привет… Я рядом. Расскажешь, как у тебя дела?"


def metrics(data: bytes) -> dict[str, float]:
    audio, rate = sf.read(io.BytesIO(data), dtype="float32")
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    rms = float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0.0
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    return {
        "duration_seconds": round(len(samples) / rate, 4),
        "rms_dbfs": round(20 * math.log10(max(rms, 1e-12)), 2),
        "peak_dbfs": round(20 * math.log10(max(peak, 1e-12)), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--steps", type=int, default=6)
    parser.add_argument(
        "--skip-postprocess",
        action="store_true",
        help="Keep raw Supertonic audio for diagnosing harshness",
    )
    args = parser.parse_args()

    from supertonic import TTS

    args.model_dir = args.model_dir.expanduser().resolve()
    tts = TTS(
        model_dir=args.model_dir,
        auto_download=False,
        intra_op_num_threads=8,
        inter_op_num_threads=1,
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for voice in ("F1", "F2", "F3", "F4", "F5"):
        style = tts.get_voice_style(voice)
        started = time.perf_counter()
        wav, duration = tts.synthesize(
            TEXT,
            voice_style=style,
            total_steps=args.steps,
            speed=1.0,
            max_chunk_length=300,
            silence_duration=0.15,
            lang="ru",
            verbose=False,
        )
        generation_seconds = time.perf_counter() - started
        delivered = apply_wav_delivery(
            waveform_to_wav_bytes(wav[0], tts.sample_rate),
            postprocess=not args.skip_postprocess,
            loudness_target_dbfs=-18.0,
            peak_ceiling_dbfs=-1.0,
            highpass_cutoff_hz=60.0,
        )
        filename = f"{voice}.wav"
        (OUTPUT_DIR / filename).write_bytes(delivered)
        row = {
            "voice": voice,
            "audio": filename,
            "generation_seconds": round(generation_seconds, 4),
            "model_duration_seconds": round(float(duration[0]), 4),
            "rtf": round(generation_seconds / max(float(duration[0]), 1e-6), 4),
            "metrics": metrics(delivered),
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps({"text": TEXT, "steps": args.steps, "samples": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    cards = "".join(
        f"<article><h2>{html.escape(str(row['voice']))}</h2>"
        f"<audio controls preload=\"metadata\" src=\"Iris-Voice-Comparison/{html.escape(str(row['audio']))}\"></audio>"
        f"<p>{row['generation_seconds']:.2f} с генерации · RTF {row['rtf']:.3f} · RMS {row['metrics']['rms_dbfs']:.1f} dBFS</p></article>"
        for row in rows
    )
    page = f"""<!doctype html>
<html lang=\"ru\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Supertonic female voice comparison</title>
<style>body{{max-width:860px;margin:32px auto;padding:0 20px;background:#17131b;color:#f8eef8;font-family:system-ui,sans-serif}}article{{background:#241c28;border:1px solid #4b3850;border-radius:16px;padding:16px;margin:14px 0}}audio{{width:100%}}p{{color:#d3c2d4}}</style></head>
<body><h1>Supertonic: F1–F5</h1><p>Одна и та же фраза: «{html.escape(TEXT)}». Слушать прежде всего возраст, мягкость и естественность.</p>{cards}</body></html>"""
    page_path = OUTPUT_DIR.parent / "listen_iris_voice_comparison.html"
    page_path.write_text(page, encoding="utf-8")
    print(f"Listen page: {page_path}", flush=True)


if __name__ == "__main__":
    main()
