from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import psutil
import soundfile as sf


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    py_dir = args.repo / "py"
    sys.path.insert(0, str(py_dir))
    from helper import load_text_to_speech, load_voice_style

    args.output.mkdir(parents=True, exist_ok=True)
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    process = psutil.Process()

    load_started = time.perf_counter()
    tts = load_text_to_speech(str(args.repo / "assets" / "onnx"), False)
    load_seconds = time.perf_counter() - load_started

    rows: list[dict[str, object]] = []
    primary_style = load_voice_style(
        [str(args.repo / "assets" / "voice_styles" / "F1.json")], verbose=False
    )
    jobs = [(case["id"], case["text"], primary_style, "F1") for case in cases]

    # Extra fixed voices let the listener distinguish model quality from a
    # single preset's timbre. The shared dialogue case remains identical.
    dialogue = cases[0]
    for voice in ("F2", "F3", "F4", "F5"):
        style = load_voice_style(
            [str(args.repo / "assets" / "voice_styles" / f"{voice}.json")],
            verbose=False,
        )
        jobs.append((f"06_voice_{voice.lower()}", dialogue["text"], style, voice))

    # Warm-up is reported separately and discarded.
    warm_started = time.perf_counter()
    tts("Привет. Это короткая проверка голоса.", "ru", primary_style, 8, 1.05)
    warmup_seconds = time.perf_counter() - warm_started

    for sample_id, text, style, voice in jobs:
        started = time.perf_counter()
        wav, duration = tts(text, "ru", style, 8, 1.05)
        synthesis_seconds = time.perf_counter() - started
        audio_seconds = float(duration[0].item())
        output_path = args.output / f"supertonic3__{sample_id}__{voice}.wav"
        sf.write(
            output_path,
            wav[0, : int(tts.sample_rate * audio_seconds)],
            tts.sample_rate,
            subtype="PCM_16",
        )
        rows.append(
            {
                "sample": output_path.name,
                "voice": voice,
                "text": text,
                "synthesis_seconds": round(synthesis_seconds, 4),
                "audio_seconds": round(audio_seconds, 4),
                "rtf": round(synthesis_seconds / audio_seconds, 4),
                "rss_mb_after": round(process.memory_info().rss / 1024**2, 1),
            }
        )
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)

    manifest = {
        "model": "Supertone/supertonic-3",
        "runtime": "onnxruntime-cpu",
        "sample_rate": tts.sample_rate,
        "settings": {"total_steps": 8, "speed": 1.05},
        "load_seconds": round(load_seconds, 4),
        "warmup_seconds": round(warmup_seconds, 4),
        "samples": rows,
    }
    (args.output / "metrics.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
