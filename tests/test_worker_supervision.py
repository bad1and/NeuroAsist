import asyncio
import threading
from pathlib import Path

import pytest

from apps.backend import main as backend_main
from apps.backend.app.model_manager.service import ModelManager, ModelSpec


def _fixture_manager(tmp_path: Path) -> ModelManager:
    spec = ModelSpec(
        id="fixture",
        name="Fixture",
        version="1",
        url="file:///unused",
        relative_path="fixture/model.bin",
        sha256="0" * 64,
        size_bytes=1,
    )
    return ModelManager(tmp_path / "models", specs=(spec,))


def test_duplicate_model_install_does_not_reenter_progress_lock(tmp_path: Path) -> None:
    manager = _fixture_manager(tmp_path)
    manager._progress["fixture"] = {
        "status": "downloading",
        "downloaded_bytes": 3,
        "total_bytes": 10,
    }
    completed = threading.Event()
    result: list[dict[str, object]] = []

    def duplicate_install() -> None:
        result.append(manager.install_async("fixture"))
        completed.set()

    thread = threading.Thread(target=duplicate_install, daemon=True)
    thread.start()

    assert completed.wait(.5), "duplicate install deadlocked while reading model state"
    assert result[0]["status"] == "downloading"
    assert result[0]["downloaded_bytes"] == 3


def test_worker_supervisor_restarts_after_exception_and_reports_failure() -> None:
    async def scenario() -> None:
        calls = 0
        restarted = asyncio.Event()
        events: list[tuple[str, str, str, dict[str, object]]] = []

        async def worker() -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("transient worker failure")
            restarted.set()
            await asyncio.Event().wait()

        supervisor = asyncio.create_task(
            backend_main._supervise_worker(
                "fixture",
                worker,
                lambda *event: events.append(event),
                restart_min_seconds=0,
                restart_max_seconds=0,
            )
        )
        await asyncio.wait_for(restarted.wait(), timeout=1)

        assert calls == 2
        assert events[0][0] == "backend.worker_failed"
        assert events[0][3]["worker"] == "fixture"
        assert events[0][3]["error_type"] == "RuntimeError"

        supervisor.cancel()
        with pytest.raises(asyncio.CancelledError):
            await supervisor

    asyncio.run(scenario())


def test_worker_supervisor_does_not_restart_cancelled_worker() -> None:
    async def scenario() -> None:
        calls = 0
        started = asyncio.Event()
        events: list[object] = []

        async def worker() -> None:
            nonlocal calls
            calls += 1
            started.set()
            await asyncio.Event().wait()

        supervisor = asyncio.create_task(
            backend_main._supervise_worker(
                "fixture",
                worker,
                lambda *event: events.append(event),
                restart_min_seconds=0,
                restart_max_seconds=0,
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        supervisor.cancel()

        with pytest.raises(asyncio.CancelledError):
            await supervisor
        await asyncio.sleep(0)
        assert calls == 1
        assert events == []

    asyncio.run(scenario())
