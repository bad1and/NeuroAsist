"""Whisper intelligibility and basic waveform analysis for llama-tts reference tests."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel


def normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-zа-я0-9]+", text.lower().replace("ё", "е")))


def wer(reference: str, hypothesis: str) -> float:
    ref = normalize(reference).split()
    hyp = normalize(hypothesis).split()
    prev = list(range(len(hyp) + 1))
    for i, token in enumerate(ref, 1):
        cur = [i]
        for j, candidate in enumerate(hyp, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (token != candidate)))
        prev = cur
    return prev[-1] / max(1, len(ref))


def stats(path: Path) -> dict[str, float | int]:
    audio, rate = sf.read(path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    rms = float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
    return {
        "sample_rate": rate,
        "duration_seconds": round(len(audio) / rate, 4),
        "peak_dbfs": round(20 * math.log10(max(peak, 1e-12)), 2),
        "rms_dbfs": round(20 * math.log10(max(rms, 1e-12)), 2),
        "clipped_samples_percent": round(float(np.mean(np.abs(audio) >= 0.999)) * 100, 5),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    args = parser.parse_args()
    cases = {item["id"]: item for item in json.loads(args.cases.read_text(encoding="utf-8"))}
    model = WhisperModel("small", device="cpu", compute_type="int8")
    rows: list[dict[str, object]] = []

    for path in sorted(args.root.glob("*.wav")):
        parts = path.stem.split("___", 1)
        if len(parts) != 2:
            continue
        reference, case_id = parts
        case = cases[case_id]
        audio = stats(path)
        segments, info = model.transcribe(str(path), language="ru", beam_size=5, vad_filter=False)
        transcript = " ".join(segment.text.strip() for segment in segments if segment.end <= audio["duration_seconds"] + 0.5).strip()
        row = {
            "file": path.name,
            "reference": reference,
            "case_id": case_id,
            "text": case["text"],
            "transcript": transcript,
            "wer": round(wer(case["text"], transcript), 4),
            "character_similarity": round(SequenceMatcher(None, normalize(case["text"]), normalize(transcript)).ratio(), 4),
            "detected_language": info.language,
            **audio,
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    (args.root / "analysis.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
