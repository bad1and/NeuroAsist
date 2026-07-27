from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import psutil

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.backend.app.conversation.service import LiveConversationService
from apps.backend.app.storage.timeline import TimelineStore


def runtime():
    return SimpleNamespace(
        memory_incognito=False,
        live_conversation_mood_recovery="natural",
        live_conversation_engagement="balanced",
        live_conversation_participant_mode="one_to_one",
        live_conversation_address_strictness="balanced",
        live_conversation_echo_mode="auto",
    )


async def run(duration: float, cycles: int) -> dict[str, object]:
    process = psutil.Process()
    rss_start = process.memory_info().rss
    started = time.monotonic()
    cancellations = 0
    with tempfile.TemporaryDirectory(prefix="iris-live-soak-") as temporary:
        root = Path(temporary)
        store = TimelineStore(root / "timeline.sqlite3")
        store.init_db()
        service = LiveConversationService(store, runtime())
        for index in range(cycles):
            generation = await service.speech_started("soak")
            cancellations += 1
            transcript = (
                "Ирис, коротко ответь."
                if index % 4 == 0
                else f"Это фоновое наблюдение номер {index}."
            )
            result = await service.ingest_observation(
                session_id="soak",
                transcript=transcript,
                language="ru",
                expected_generation=generation,
            )
            if result.decision.action.value in {"respond", "backchannel"}:
                await service.playback_segment_started(
                    "soak",
                    "Короткий ответ.",
                    result.utterance_id,
                    generation,
                )
                await asyncio.sleep(0)
                await service.playback_segment_finished(
                    "soak",
                    "Короткий ответ.",
                    result.utterance_id,
                    generation,
                )
                await service.playback_finished("soak", result.utterance_id)
            target = started + duration * (index + 1) / cycles
            await asyncio.sleep(max(0.0, target - time.monotonic()))
        await asyncio.sleep(0.05)
        debug = service.debug("soak")
        observations = store.recent_conversation_observations("soak", limit=cycles + 5)
        message_ids = [item["message_id"] for item in observations]
        raw_audio = list(root.rglob("*.wav")) + list(root.rglob("*.pcm"))
        await service.close()
        rss_end = process.memory_info().rss
        elapsed = time.monotonic() - started
        report = {
            "version": 1,
            "duration_seconds": elapsed,
            "cycles": cycles,
            "vad_transitions_simulated": cycles * 3,
            "cancellations": cancellations,
            "observations": len(observations),
            "duplicate_observation_ids": len(message_ids) - len(set(message_ids)),
            "active_tasks_after_quiescence": len(debug["active_tasks"]),
            "deferred_after_quiescence": len(debug["deferred_reactions"]),
            "raw_audio_files_after_completion": len(raw_audio),
            "rss_start_bytes": rss_start,
            "rss_end_bytes": rss_end,
            "rss_delta_bytes": rss_end - rss_start,
        }
        report["passed"] = bool(
            report["duplicate_observation_ids"] == 0
            and report["active_tasks_after_quiescence"] == 0
            and report["raw_audio_files_after_completion"] == 0
        )
        return report


def markdown(report: dict[str, object]) -> str:
    rows = "\n".join(f"| {key} | {value} |" for key, value in report.items())
    return f"# Iris Live Conversation soak report\n\n| Metric | Value |\n|---|---:|\n{rows}\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=900)
    parser.add_argument("--cycles", type=int, default=100)
    parser.add_argument("--output", type=Path, default=Path("output/live-soak.json"))
    parser.add_argument("--full", action="store_true", help="Run the four-hour release soak")
    args = parser.parse_args()
    duration = 14_400 if args.full else args.duration
    report = asyncio.run(run(duration, args.cycles))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
