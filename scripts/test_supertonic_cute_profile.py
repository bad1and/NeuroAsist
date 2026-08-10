"""Generate a repeatable listening pack for the experimental Iris cute voice.

This is intentionally isolated from the production TTS provider. It lets us
compare the voice profile, normalization and delivery settings before wiring
Supertonic into the main application.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / "output" / "tts-model-comparison" / "iris_cute_v1.json"
DEFAULT_MODEL_DIR = Path.home() / ".cache" / "supertonic3"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.backend.app.voice.providers import apply_wav_delivery, waveform_to_wav_bytes


def _resolve_path(value: str | None, *, base: Path) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def _audio_metrics(wav_bytes: bytes) -> dict[str, float]:
    audio, sample_rate = sf.read(__import__("io").BytesIO(wav_bytes), dtype="float32")
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    rms = float(np.sqrt(np.mean(np.square(samples)))) if len(samples) else 0.0
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    return {
        "sample_rate": int(sample_rate),
        "duration_seconds": round(len(samples) / sample_rate, 4) if sample_rate else 0.0,
        "rms_dbfs": round(20 * math.log10(max(rms, 1e-12)), 2),
        "peak_dbfs": round(20 * math.log10(max(peak, 1e-12)), 2),
        "clipped_samples_percent": round(
            float(np.mean(np.abs(samples) >= 0.999)) * 100, 5
        )
        if len(samples)
        else 0.0,
    }


def _write_listen_page(
    *, output_root: Path, profile: dict[str, Any], rows: list[dict[str, Any]]
) -> Path:
    cards: list[str] = []
    for row in rows:
        cards.append(
            f"""<article class=\"card\">
  <h2>{row['label']}</h2>
  <audio controls preload=\"metadata\" src=\"{row['audio']}\"></audio>
  <p><strong>Исходный текст:</strong> {row['text']}</p>
  <p class=\"muted\"><strong>TTS-текст:</strong> {row['tts_text']}</p>
  <p class=\"metrics\">{row['generation_seconds']:.2f} с генерации · {row['audio_metrics']['duration_seconds']:.2f} с аудио · RTF {row['rtf']:.3f} · RMS {row['audio_metrics']['rms_dbfs']:.1f} dBFS</p>
</article>"""
        )
    html = f"""<!doctype html>
<html lang=\"ru\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>Iris cute voice profile</title>
  <style>
    :root {{ color-scheme: dark; font-family: system-ui, sans-serif; background: #17131b; color: #f8eef8; }}
    body {{ max-width: 920px; margin: 0 auto; padding: 32px 20px 56px; }}
    h1 {{ margin-bottom: 6px; }}
    .muted {{ color: #cdbdce; }}
    .card {{ background: #241c28; border: 1px solid #4b3850; border-radius: 16px; padding: 18px; margin: 16px 0; }}
    audio {{ width: 100%; margin: 8px 0 12px; }}
    p {{ line-height: 1.5; }}
    .metrics {{ color: #e7b9df; font-size: 0.92rem; }}
    code {{ color: #ffd4f7; }}
  </style>
</head>
<body>
  <h1>Iris cute v1</h1>
  <p class=\"muted\">Экспериментальный профиль. Голос: <code>{profile['voice']}</code>; шаги: <code>{profile['generation']['total_steps']}</code>; скорость: <code>{profile['generation']['speed']}</code>.</p>
  <p>При прослушивании оцени: мягкость, милоту без писка, естественность, разборчивость, отсутствие переигрывания.</p>
  {''.join(cards)}
</body>
</html>
"""
    path = output_root / "listen_iris_cute.html"
    path.write_text(html, encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--voice", default=None, help="Override the built-in voice for an A/B run")
    parser.add_argument(
        "--skip-postprocess",
        action="store_true",
        help="Keep the raw Supertonic waveform for diagnosing harshness",
    )
    args = parser.parse_args()

    profile_path = args.profile.resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    generation = profile["generation"]
    delivery = profile["delivery"]
    pitch_shift = float(delivery.get("pitch_shift_semitones", 0.0))
    if abs(pitch_shift) > 1e-6:
        raise SystemExit(
            "pitch_shift_semitones пока должен быть 0: профиль хранит допустимый "
            "диапазон, но pitch shift намеренно выключен до отдельного A/B-теста."
        )

    try:
        from supertonic import TTS
    except ImportError as exc:
        raise SystemExit(
            "Не найден пакет supertonic. Установите его в используемое окружение: "
            "pip install supertonic"
        ) from exc

    model_dir = args.model_dir.expanduser().resolve()
    if not model_dir.is_dir():
        raise SystemExit(f"Каталог модели не найден: {model_dir}")
    output_root = (args.output_dir or (ROOT / "output" / "tts-model-comparison" / "Iris-Cute-v1")).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    print(f"Loading Supertonic from {model_dir} ...", flush=True)
    tts = TTS(
        model_dir=model_dir,
        auto_download=False,
        intra_op_num_threads=8,
        inter_op_num_threads=1,
    )
    custom_style = _resolve_path(profile.get("custom_voice_style_path"), base=profile_path.parent)
    if custom_style is not None:
        style = tts.get_voice_style_from_path(custom_style)
        voice_label = custom_style.stem
    else:
        voice_label = args.voice or profile["voice"]
        style = tts.get_voice_style(voice_label)

    rows: list[dict[str, Any]] = []
    for case in profile["cases"]:
        started = time.perf_counter()
        wav, duration = tts.synthesize(
            text=case["tts_text"],
            voice_style=style,
            total_steps=int(generation["total_steps"]),
            speed=float(generation["speed"]),
            max_chunk_length=int(generation["max_chunk_length"]),
            silence_duration=float(generation["silence_duration_seconds"]),
            lang=profile["language"],
            verbose=False,
        )
        generation_seconds = time.perf_counter() - started
        raw_wav = waveform_to_wav_bytes(wav[0], tts.sample_rate)
        delivered_wav = apply_wav_delivery(
            raw_wav,
            tempo=float(delivery["tempo"]),
            pause_before_ms=int(delivery["pause_before_ms"]),
            pause_after_ms=int(delivery["pause_after_ms"]),
            postprocess=not args.skip_postprocess,
            loudness_target_dbfs=float(delivery["loudness_target_dbfs"]),
            peak_ceiling_dbfs=float(delivery["peak_ceiling_dbfs"]),
            highpass_cutoff_hz=float(delivery["highpass_cutoff_hz"]),
        )
        output_path = output_root / f"{case['id']}.wav"
        output_path.write_bytes(delivered_wav)
        metrics = _audio_metrics(delivered_wav)
        row = {
            "id": case["id"],
            "label": case["label"],
            "text": case["text"],
            "tts_text": case["tts_text"],
            "audio": output_path.name,
            "voice": voice_label,
            "generation_seconds": round(generation_seconds, 4),
            "model_duration_seconds": round(float(duration[0]), 4),
            "rtf": round(generation_seconds / max(float(duration[0]), 1e-6), 4),
            "audio_metrics": metrics,
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    manifest = {
        "profile": profile,
        "profile_path": str(profile_path),
        "model_dir": str(model_dir),
        "voice_used": voice_label,
        "samples": rows,
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    listen_page = _write_listen_page(output_root=output_root.parent, profile=profile, rows=[
        {**row, "audio": f"{output_root.name}/{row['audio']}"} for row in rows
    ])
    print(f"\nListen page: {listen_page}", flush=True)
    print(f"Manifest: {output_root / 'manifest.json'}", flush=True)


if __name__ == "__main__":
    main()
