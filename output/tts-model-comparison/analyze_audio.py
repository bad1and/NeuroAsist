from __future__ import annotations

import argparse
import json
import math
import re
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    return " ".join(re.findall(r"[a-zа-я0-9]+", text))


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref = normalize(reference).split()
    hyp = normalize(hypothesis).split()
    previous = list(range(len(hyp) + 1))
    for i, ref_word in enumerate(ref, 1):
        current = [i]
        for j, hyp_word in enumerate(hyp, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (ref_word != hyp_word),
                )
            )
        previous = current
    return previous[-1] / max(1, len(ref))


def audio_stats(path: Path) -> dict[str, float | int]:
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    rms = float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
    return {
        "sample_rate": sample_rate,
        "duration_seconds": round(len(audio) / sample_rate, 4),
        "peak_dbfs": round(20 * math.log10(max(peak, 1e-12)), 2),
        "rms_dbfs": round(20 * math.log10(max(rms, 1e-12)), 2),
        "clipped_samples_percent": round(float(np.mean(np.abs(audio) >= 0.999)) * 100, 5),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    args = parser.parse_args()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    case_by_id = {case["id"]: case for case in cases}
    # CTranslate2's standalone CUDA runtime is not bundled in this Windows
    # environment, so use its portable CPU int8 path for reproducibility.
    model = WhisperModel("small", device="cpu", compute_type="int8")
    rows: list[dict[str, object]] = []

    for path in sorted(args.root.glob("*/*.wav")):
        case_id = next((case_id for case_id in case_by_id if case_id in path.name), None)
        if case_id is None and "06_" in path.name:
            case_id = "01_dialogue"
        reference = case_by_id[case_id]["text"] if case_id else ""
        stats = audio_stats(path)
        segments, info = model.transcribe(
            str(path), language="ru", beam_size=5, vad_filter=False
        )
        # Whisper operates on padded 30-second windows and can emit a phantom
        # subtitle-credit phrase after a clip has already ended. Discard only
        # segments whose timestamp materially exceeds the actual WAV length.
        transcript = " ".join(
            segment.text.strip()
            for segment in segments
            if segment.end <= float(stats["duration_seconds"]) + 0.5
        ).strip()
        similarity = SequenceMatcher(None, normalize(reference), normalize(transcript)).ratio()
        row = {
            "file": str(path.relative_to(args.root)).replace("\\", "/"),
            "case_id": case_id,
            "reference": reference,
            "transcript": transcript,
            "wer": round(word_error_rate(reference, transcript), 4) if reference else None,
            "character_similarity": round(similarity, 4) if reference else None,
            "detected_language": info.language,
            **stats,
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    (args.root / "analysis.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
