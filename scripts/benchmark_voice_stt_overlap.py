"""Replay PCM to compare batch STT with work done during speech.

No microphone, network or playback is measured. Frames arrive on a virtual
one-second clock; measured precompute must fit between arrivals. Residual STT
is timed separately after the final frame, with exact raw-text parity checked.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.backend.app.core.config import Settings
from apps.backend.app.voice.audio import Pcm16Audio
from apps.backend.app.voice.service import VoiceService
from scripts.benchmark_local_stt import load_rows, long_rows


async def run(args):
    service = VoiceService(Settings())
    await service.stt_provider.preload()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    corpus = list(load_rows(args.manifest.resolve(), include_synthetic=True))
    corpus.extend(long_rows(corpus))
    audio_by_name = {row["audio"]: Pcm16Audio(b"\0\0" * (args.pre_roll_ms * 16) + audio.data)
                     for row, audio in corpus}
    rows = []
    for sample in baseline["samples"]:
        audio = audio_by_name[sample["audio"]]
        if abs(audio.duration_seconds - sample["audio_seconds"]) > .001:
            raise RuntimeError("Replay audio duration does not match baseline")
        stream = service.start_live_stt()
        if stream is None:
            raise RuntimeError("Live STT precompute is disabled or unavailable")
        prefix_ms = []
        for end in range(32000, len(audio.data), 32000):
            stream.update(bytearray(audio.data[:end]))
            if stream.task is not None and not stream.task.done():
                started = time.perf_counter()
                await stream.task
                prefix_ms.append((time.perf_counter() - started) * 1000)
        if prefix_ms and max(prefix_ms) >= 1000:
            raise RuntimeError("Precompute exceeds replay frame interval; use a real-time replay")
        started = time.perf_counter()
        result = await service.transcribe_pcm16(audio, "ru", live_stt=stream)
        remaining_ms = (time.perf_counter() - started) * 1000
        batch_ms = []
        if audio.duration_seconds >= 28:
            for _ in range(3):
                started = time.perf_counter()
                await service.transcribe_pcm16(audio, "ru")
                batch_ms.append((time.perf_counter() - started) * 1000)
        row = {
            "audio": sample["audio"], "audio_seconds": audio.duration_seconds,
            "raw_text": result.raw_text, "parity": result.raw_text == sample["raw_text"],
            "reused_chunks": stream.reused_chunks,
            "precompute_ms": prefix_ms, "remaining_stt_ms": round(remaining_ms, 1),
            "batch_ms": [round(value, 1) for value in batch_ms],
        }
        rows.append(row)
        print(json.dumps({key: value for key, value in row.items()
                          if key not in {"audio", "raw_text"}}, ensure_ascii=True), flush=True)
        await stream.close()
    report = {
        "measurement": "virtual one-second PCM arrivals; local inference only",
        "provider_metadata": service.stt_provider.metadata,
        "parity_count": sum(row["parity"] for row in rows),
        "sample_count": len(rows), "samples": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if report["parity_count"] != report["sample_count"]:
        raise RuntimeError("Raw STT text changed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--pre-roll-ms", type=int, default=900)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
