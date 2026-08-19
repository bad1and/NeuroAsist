"""Run the isolated Qwen3-TTS 0.6B acceptance gate and write a JSON report."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
import wave
from pathlib import Path


MODEL = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
REVISION = "c27fe8aa05b732b1376d0f6a1e522fbccb84abbd"
DEFAULT_SEGMENTS = (
    "Привет! Я рядом и внимательно тебя слушаю.",
    "Давай спокойно разберёмся, что именно произошло.",
    "Проверь, пожалуйста, числа: двадцать четыре, сто семь и три целых пять десятых.",
    "Это важное предупреждение: не выключай питание во время обновления.",
    "API вернул HTTP status code four hundred and twenty nine.",
    "Сначала открой настройки, затем выбери нужный микрофон.",
    "Правда? Это уже работает заметно лучше!",
    "Подожди немного… я проверяю результат.",
    "Короткий ответ: да.",
    "Если хочешь, я объясню техническую часть подробнее.",
)


def _duration(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        return audio.getnframes() / audio.getframerate()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return float("inf")
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, required=True, help="Python from the isolated Qwen environment")
    parser.add_argument("--reference-wav", type=Path, required=True)
    parser.add_argument("--reference-text", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("data/qwen-tts-gate"))
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--baseline-p95-ms", type=float, default=226)
    parser.add_argument("--blind-wins", type=int)
    parser.add_argument("--similarity-median", type=float)
    args = parser.parse_args()

    texts = list(DEFAULT_SEGMENTS) * 10
    if args.corpus:
        texts = [
            line.strip()
            for line in args.corpus.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(args.python),
        str(Path(__file__).with_name("qwen_tts_worker.py")),
        "--model",
        MODEL,
        "--revision",
        REVISION,
        "--reference-wav",
        str(args.reference_wav),
        "--reference-text",
        args.reference_text,
    ]
    worker = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    assert worker.stdin is not None and worker.stdout is not None
    ready = json.loads(worker.stdout.readline())
    if ready.get("type") != "ready":
        raise RuntimeError(f"Qwen worker did not become ready: {ready}")

    results: list[dict] = []
    try:
        for index, text in enumerate(texts):
            output_path = args.output_dir / f"{index:03d}.wav"
            requested_at = time.perf_counter()
            worker.stdin.write(
                json.dumps(
                    {
                        "id": index,
                        "text": text,
                        "language": "Russian",
                        "output_path": str(output_path),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            worker.stdin.flush()
            result = json.loads(worker.stdout.readline())
            result["wall_ms"] = int((time.perf_counter() - requested_at) * 1000)
            if result.get("ok"):
                duration = _duration(output_path)
                result["audio_duration_seconds"] = duration
                result["rtf"] = (result["synthesis_ms"] / 1000) / duration
            results.append(result)
    finally:
        worker.stdin.close()
        worker.terminate()
        worker.wait(timeout=10)

    successes = [item for item in results if item.get("ok")]
    errors = len(results) - len(successes)
    rtfs = [float(item["rtf"]) for item in successes]
    latency = [float(item["wall_ms"]) for item in successes]
    peak_vram = max([float(ready.get("peak_vram_gb", 0)), *[
        float(item.get("peak_vram_gb", 0)) for item in results
    ]])
    objective = {
        "no_oom": all(item.get("error_type") != "OutOfMemoryError" for item in results),
        "peak_vram_le_5_2_gb": peak_vram <= 5.2,
        "p95_rtf_le_0_5": _percentile(rtfs, 0.95) <= 0.5,
        "p95_first_segment_delta_le_250_ms": _percentile(latency, 0.95) - args.baseline_p95_ms <= 250,
        "error_rate_lt_1_percent": errors / max(1, len(results)) < 0.01,
    }
    subjective = {
        "blind_wins_ge_14_of_20": args.blind_wins is not None and args.blind_wins >= 14,
        "similarity_median_ge_4_of_5": (
            args.similarity_median is not None and args.similarity_median >= 4
        ),
    }
    report = {
        "model": MODEL,
        "revision": REVISION,
        "configuration": {"dtype": "float16", "attention": "sdpa"},
        "segments": len(results),
        "errors": errors,
        "peak_vram_gb": peak_vram,
        "p50_rtf": statistics.median(rtfs) if rtfs else None,
        "p95_rtf": _percentile(rtfs, 0.95),
        "p95_wall_ms": _percentile(latency, 0.95),
        "objective_gate": objective,
        "subjective_gate": subjective,
        "passed": all(objective.values()) and all(subjective.values()),
        "results": results,
    }
    report_path = args.output_dir / "gate-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report_path)
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
