"""Private-corpus benchmark for NeuroAsist STT.

Manifest format (JSON list or JSONL):
{"audio":"recordings/001.webm","reference":"Привет Iris","tags":["short"],
 "profile":"balanced","noise_only":false,"session_sequence":1}

The tool never uploads recordings. Run baseline/candidate in separate processes
when changing PyTorch thread counts so global thread pools cannot contaminate
the comparison.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.backend.app.core.config import get_settings  # noqa: E402
from apps.backend.app.voice.audio import Pcm16Audio, decode_audio_file  # noqa: E402
from apps.backend.app.voice.runtime import configure_torch_threads  # noqa: E402
from apps.backend.app.voice.service import VoiceService  # noqa: E402
from apps.backend.app.voice.stt_terms import correct_stt_terms  # noqa: E402
from apps.backend.app.voice.input import SileroVadProvider, VadGate, VadProvider  # noqa: E402
from apps.backend.app.voice.providers import TTSRequest  # noqa: E402


@dataclass
class SampleResult:
    audio: str
    reference: str
    transcript: str
    raw_transcript: str
    tags: list[str]
    profile: str
    noise_only: bool
    session_sequence: int | None
    words: int
    word_errors: int
    chars: int
    char_errors: int
    term_hits: int
    term_total: int
    first_token_deleted: bool
    last_token_deleted: bool
    short_utterance_missed: bool
    false_positive_vad: bool
    vad_detected: bool
    vad_provider: str
    audio_ms: float
    stt_ms: float
    end_to_transcript_ms: float


def _tokens(value: str) -> list[str]:
    return re.findall(r"\w+", value.casefold(), flags=re.UNICODE)


def _chars(value: str) -> list[str]:
    return [item for item in value.casefold() if not item.isspace()]


def _edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for left_index, left in enumerate(reference, 1):
        current = [left_index]
        for right_index, right in enumerate(hypothesis, 1):
            current.append(min(
                previous[right_index] + 1,
                current[right_index - 1] + 1,
                previous[right_index - 1] + (left != right),
            ))
        previous = current
    return previous[-1]


def _deleted_reference_positions(reference: list[str], hypothesis: list[str]) -> set[int]:
    rows, columns = len(reference) + 1, len(hypothesis) + 1
    matrix = [[0] * columns for _ in range(rows)]
    for row in range(rows):
        matrix[row][0] = row
    for column in range(columns):
        matrix[0][column] = column
    for row in range(1, rows):
        for column in range(1, columns):
            matrix[row][column] = min(
                matrix[row - 1][column] + 1,
                matrix[row][column - 1] + 1,
                matrix[row - 1][column - 1]
                + (reference[row - 1] != hypothesis[column - 1]),
            )
    deleted: set[int] = set()
    row, column = len(reference), len(hypothesis)
    while row or column:
        if (
            row
            and column
            and matrix[row][column]
            == matrix[row - 1][column - 1]
            + (reference[row - 1] != hypothesis[column - 1])
        ):
            row -= 1
            column -= 1
        elif row and matrix[row][column] == matrix[row - 1][column] + 1:
            deleted.add(row - 1)
            row -= 1
        else:
            column -= 1
    return deleted


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _load_manifest(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if isinstance(value, dict) and isinstance(value.get("fixtures"), list):
        value = [
            {
                **item,
                "audio": item.get("audio", item.get("file")),
                "reference": item.get("reference", item.get("transcript", "")),
                "tags": item.get("tags", [item.get("purpose", "synthetic")]),
            }
            for item in value["fixtures"]
        ]
    if not isinstance(value, list):
        raise ValueError("Manifest must be a JSON list or JSONL")
    rows: list[dict] = []
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict) or "audio" not in item or "reference" not in item:
            raise ValueError(f"Manifest row {index} requires audio and reference")
        row = dict(item)
        audio = Path(str(row["audio"]))
        row["_audio_path"] = audio if audio.is_absolute() else path.parent / audio
        rows.append(row)
    return rows


def _streaming_replay(audio: Pcm16Audio, frame_ms: int) -> Pcm16Audio:
    """Reconstruct canonical audio through irregular browser-sized chunks."""
    samples_per_frame = max(1, round(audio.sample_rate * frame_ms / 1000))
    frame_bytes = samples_per_frame * 2
    output = bytearray()
    offsets = (frame_bytes, frame_bytes // 2, frame_bytes + frame_bytes // 3)
    cursor = 0
    sequence = 0
    while cursor < len(audio.data):
        size = offsets[sequence % len(offsets)]
        output.extend(audio.data[cursor:cursor + size])
        cursor += size
        sequence += 1
    return Pcm16Audio(bytes(output))


def _replay_vad(
    audio: Pcm16Audio,
    settings,
    frame_ms: int,
    provider,
) -> tuple[bool, str]:
    try:
        stream = provider.create_stream()
    except Exception:
        stream = VadProvider().create_stream()
    silero = stream.name == "silero"
    gate = VadGate(
        start_threshold=(
            settings.voice_silero_vad_start_threshold
            if silero else settings.voice_energy_vad_start_rms
        ),
        end_threshold=(
            settings.voice_silero_vad_end_threshold
            if silero else settings.voice_energy_vad_end_rms
        ),
        start_ms=(
            settings.voice_silero_vad_min_speech_ms
            if silero else settings.voice_energy_vad_min_speech_ms
        ),
        end_ms=settings.voice_vad_end_silence_ms,
    )
    frame_bytes = max(2, round(audio.sample_rate * frame_ms / 1000) * 2)
    detected = False
    for offset in range(0, len(audio.data), frame_bytes):
        for observation in stream.feed(audio.data[offset:offset + frame_bytes]):
            if gate.feed(observation.value, observation.samples) == "speech_started":
                detected = True
    stream.reset()
    return detected, stream.name


def _term_score(reference: str, hypothesis: str, terms: dict[str, list[str]]) -> tuple[int, int]:
    expected = correct_stt_terms(reference, terms).text
    expected_folded = expected.casefold()
    hypothesis_folded = hypothesis.casefold()
    total = hits = 0
    for canonical in terms:
        if canonical.casefold() in expected_folded:
            total += expected_folded.count(canonical.casefold())
            hits += min(
                expected_folded.count(canonical.casefold()),
                hypothesis_folded.count(canonical.casefold()),
            )
    return hits, total


async def _run(args: argparse.Namespace) -> dict:
    if args.torch_threads is not None:
        os.environ["VOICE_TORCH_CPU_THREADS"] = str(args.torch_threads)
    settings = get_settings()
    configure_torch_threads(
        settings.voice_torch_cpu_threads,
        settings.voice_torch_interop_threads,
    )
    service = VoiceService(settings)
    process = psutil.Process()
    rss_before = process.memory_info().rss
    cpu_before = process.cpu_times()
    cold_started = time.perf_counter()
    await service.preload_stt()
    cold_load_ms = (time.perf_counter() - cold_started) * 1000
    warm_started = time.perf_counter()
    await service.preload_stt()
    warm_load_ms = (time.perf_counter() - warm_started) * 1000
    rows = _load_manifest(args.manifest)
    parallel_tts_ms: float | None = None
    if args.tts_probe and rows:
        await service.preload_tts()
        probe_audio = await asyncio.to_thread(
            decode_audio_file, Path(rows[0]["_audio_path"])
        )

        async def consume_tts() -> None:
            nonlocal parallel_tts_ms
            started = time.perf_counter()
            request = TTSRequest(
                text="Короткая параллельная проверка синтеза речи.",
                language="ru",
                voice=service.resolve_tts_voice("ru"),
            )
            async for _chunk in service.tts_provider.stream(request):
                pass
            parallel_tts_ms = (time.perf_counter() - started) * 1000

        await asyncio.gather(
            service.transcribe_pcm16(probe_audio, "ru"),
            consume_tts(),
        )
    rss_after_warmup = process.memory_info().rss
    results: list[SampleResult] = []
    peak_rss = rss_before
    vad_provider = (
        SileroVadProvider(settings.voice_silero_vad_model)
        if settings.voice_vad_provider == "silero"
        else VadProvider()
    )

    for row in rows:
        audio_path = Path(row["_audio_path"])
        audio = await asyncio.to_thread(decode_audio_file, audio_path)
        if args.streaming_replay:
            audio = _streaming_replay(audio, args.frame_ms)
            vad_detected, active_vad = _replay_vad(
                audio, settings, args.frame_ms, vad_provider
            )
        else:
            vad_detected, active_vad = True, "not-replayed"
        reference = str(row.get("reference", "")).strip()
        started = time.perf_counter()
        result = await service.transcribe_pcm16(audio, str(row.get("language", "ru")))
        stt_ms = (time.perf_counter() - started) * 1000
        reference_words = _tokens(reference)
        hypothesis_words = _tokens(result.text)
        word_errors = _edit_distance(reference_words, hypothesis_words)
        deleted_positions = _deleted_reference_positions(reference_words, hypothesis_words)
        reference_chars = _chars(reference)
        char_errors = _edit_distance(reference_chars, _chars(result.text))
        noise_only = bool(row.get("noise_only", False))
        term_hits, term_total = _term_score(reference, result.text, service.stt_terms())
        results.append(SampleResult(
            audio=str(audio_path),
            reference=reference,
            transcript=result.text,
            raw_transcript=result.raw_text or result.text,
            tags=[str(tag) for tag in row.get("tags", [])],
            profile=str(row.get("profile", "balanced")),
            noise_only=noise_only,
            session_sequence=row.get("session_sequence"),
            words=len(reference_words),
            word_errors=word_errors,
            chars=len(reference_chars),
            char_errors=char_errors,
            term_hits=term_hits,
            term_total=term_total,
            first_token_deleted=bool(reference_words and 0 in deleted_positions),
            last_token_deleted=bool(reference_words and len(reference_words) - 1 in deleted_positions),
            short_utterance_missed=bool(
                not noise_only and len(reference_words) <= 2
                and (not vad_detected or not hypothesis_words)
            ),
            false_positive_vad=bool(noise_only and vad_detected),
            vad_detected=vad_detected,
            vad_provider=active_vad,
            audio_ms=audio.duration_seconds * 1000,
            stt_ms=stt_ms,
            end_to_transcript_ms=stt_ms,
        ))
        peak_rss = max(peak_rss, process.memory_info().rss)

    total_words = sum(item.words for item in results)
    total_chars = sum(item.chars for item in results)
    latencies = [item.stt_ms for item in results]
    term_total = sum(item.term_total for item in results)
    cpu_after = process.cpu_times()
    metrics = {
        "wer": sum(item.word_errors for item in results) / max(1, total_words),
        "cer": sum(item.char_errors for item in results) / max(1, total_chars),
        "term_accuracy": sum(item.term_hits for item in results) / max(1, term_total),
        "first_token_deletions": sum(item.first_token_deleted for item in results),
        "last_token_deletions": sum(item.last_token_deleted for item in results),
        "false_positive_vad": sum(item.false_positive_vad for item in results),
        "short_utterance_misses": sum(item.short_utterance_missed for item in results),
        "stt_p50_ms": _percentile(latencies, .50),
        "stt_p95_ms": _percentile(latencies, .95),
        "end_to_transcript_p50_ms": _percentile(
            [item.end_to_transcript_ms for item in results], .50
        ),
        "end_to_transcript_p95_ms": _percentile(
            [item.end_to_transcript_ms for item in results], .95
        ),
        "cold_load_ms": cold_load_ms,
        "warm_load_ms": warm_load_ms,
        "rss_growth_mb": (process.memory_info().rss - rss_before) / 1024 / 1024,
        "steady_state_rss_growth_mb": (
            process.memory_info().rss - rss_after_warmup
        ) / 1024 / 1024,
        "rss_after_warmup_mb": rss_after_warmup / 1024 / 1024,
        "peak_rss_mb": peak_rss / 1024 / 1024,
        "cpu_seconds": (
            cpu_after.user + cpu_after.system - cpu_before.user - cpu_before.system
        ),
        "sample_count": len(results),
        "parallel_tts_ms": parallel_tts_ms,
    }
    return {
        "schema_version": 1,
        "kind": args.action,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "manifest": str(args.manifest),
        "streaming_replay": args.streaming_replay,
        "torch_threads": settings.voice_torch_cpu_threads,
        "provider": settings.voice_stt_provider,
        "model": settings.voice_stt_model,
        "device": settings.voice_stt_device,
        "metrics": metrics,
        "samples": [asdict(item) for item in results],
    }


def _compare(baseline_path: Path, candidate_path: Path) -> dict:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    left = baseline["metrics"]
    right = candidate["metrics"]
    quality_keys = (
        "wer", "cer", "false_positive_vad", "short_utterance_misses",
        "first_token_deletions", "last_token_deletions",
    )
    regressions = [key for key in quality_keys if right[key] > left[key]]
    latency_limit = left["stt_p95_ms"] * 1.05
    full_limit = max(
        left["end_to_transcript_p95_ms"] * 1.10,
        left["end_to_transcript_p95_ms"] + 100,
    )
    gates = {
        "quality_not_worse": not regressions,
        "term_accuracy_100_percent": right["term_accuracy"] == 1.0,
        "stt_p95_within_5_percent": right["stt_p95_ms"] <= latency_limit,
        "full_p95_within_10_percent_or_100ms": right["end_to_transcript_p95_ms"] <= full_limit,
        "boundary_or_short_metric_improved": any(
            right[key] < left[key]
            for key in ("first_token_deletions", "last_token_deletions", "short_utterance_misses")
        ),
    }
    return {
        "baseline": str(baseline_path),
        "candidate": str(candidate_path),
        "deltas": {key: right[key] - left[key] for key in right if isinstance(right[key], (int, float))},
        "regressions": regressions,
        "gates": gates,
        "passed": all(gates.values()),
    }


def _thread_sweep(args: argparse.Namespace) -> dict:
    outputs = []
    for threads in (1, 2, 4, 8):
        output = args.output.parent / f"{args.output.stem}-threads-{threads}.json"
        command = [
            sys.executable, str(Path(__file__).resolve()), "candidate",
            "--manifest", str(args.manifest), "--output", str(output),
            "--torch-threads", str(threads),
        ]
        if args.streaming_replay:
            command.append("--streaming-replay")
        command.append("--tts-probe")
        subprocess.run(command, cwd=ROOT, check=True)
        outputs.append(json.loads(output.read_text(encoding="utf-8")))
    result_rows = [
        {"threads": item["torch_threads"], **item["metrics"]}
        for item in outputs
    ]
    default = next(item for item in result_rows if item["threads"] == 4)
    eligible = [
        item for item in result_rows
        if item["threads"] != 4
        and item["stt_p95_ms"] <= default["stt_p95_ms"] * .90
        and (
            default["parallel_tts_ms"] is None
            or item["parallel_tts_ms"] <= default["parallel_tts_ms"] * 1.10
        )
        and item["cpu_seconds"] <= default["cpu_seconds"] * 1.25
    ]
    recommended = (
        min(eligible, key=lambda item: item["stt_p95_ms"])["threads"]
        if eligible else 4
    )
    summary = {
        "schema_version": 1,
        "kind": "threads",
        "selection_rule": "p95 improves >=10%, parallel TTS <=10% worse, CPU <=25% higher",
        "recommended_threads": recommended,
        "results": result_rows,
    }
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("baseline", "candidate", "compare", "threads"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--streaming-replay", action="store_true")
    parser.add_argument("--frame-ms", type=int, default=20)
    parser.add_argument("--torch-threads", type=int, choices=(1, 2, 4, 8))
    parser.add_argument("--tts-probe", action="store_true")
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.action == "compare":
        if not args.baseline or not args.candidate:
            raise SystemExit("compare requires --baseline and --candidate")
        payload = _compare(args.baseline, args.candidate)
    elif args.action == "threads":
        if not args.manifest:
            raise SystemExit("threads requires --manifest")
        payload = _thread_sweep(args)
    else:
        if not args.manifest:
            raise SystemExit(f"{args.action} requires --manifest")
        payload = asyncio.run(_run(args))
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload.get("metrics", payload), ensure_ascii=False, indent=2))
    return 0 if payload.get("passed", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
