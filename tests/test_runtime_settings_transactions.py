from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from threading import Barrier, get_ident
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.backend.app.api.routes import settings as settings_route
from apps.backend.app.runtime.settings import RuntimeSettings, RuntimeSettingsStore
from apps.backend.app.schemas.settings import RuntimeSettingsPatch


class EventBusStub:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def publish(self, *args) -> None:
        self.events.append(args)


def _request(runtime, store, tmp_path: Path, event_bus=None):
    settings = SimpleNamespace(
        deepseek_model="deepseek-test",
        coding_allowed_project_paths=(tmp_path.resolve(),),
    )
    state = SimpleNamespace(
        runtime_settings=runtime,
        runtime_settings_store=store,
        settings=settings,
        event_bus=event_bus or EventBusStub(),
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


def test_late_validation_error_does_not_mutate_or_persist_earlier_fields(tmp_path) -> None:
    path = tmp_path / "settings.json"
    store = RuntimeSettingsStore(path)
    runtime = RuntimeSettings(interface_locale="ru", coding_workspace_name="default")
    store.save(runtime)
    before_file = path.read_bytes()
    before_runtime = asdict(runtime)
    request = _request(runtime, store, tmp_path)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(settings_route.patch_runtime_settings(
            RuntimeSettingsPatch(
                interface_locale="en",
                coding_workspace_name="invalid workspace",
            ),
            request,
        ))

    assert raised.value.status_code == 400
    assert asdict(runtime) == before_runtime
    assert path.read_bytes() == before_file
    assert request.app.state.event_bus.events == []


def test_persist_error_keeps_live_state_and_previous_file(monkeypatch, tmp_path) -> None:
    path = tmp_path / "settings.json"
    store = RuntimeSettingsStore(path)
    runtime = RuntimeSettings(interface_locale="ru")
    store.save(runtime)
    before_file = path.read_bytes()
    events = EventBusStub()
    request = _request(runtime, store, tmp_path, events)

    def fail_save(_candidate) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(store, "save", fail_save)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(settings_route.patch_runtime_settings(
            RuntimeSettingsPatch(interface_locale="en"),
            request,
        ))

    assert raised.value.status_code == 503
    assert runtime.interface_locale == "ru"
    assert path.read_bytes() == before_file
    assert events.events == []


def test_success_persists_before_publishing_live_runtime(monkeypatch, tmp_path) -> None:
    path = tmp_path / "settings.json"
    runtime = RuntimeSettings(interface_locale="ru")

    class ObservingStore(RuntimeSettingsStore):
        def save(self, candidate: RuntimeSettings) -> None:
            assert runtime.interface_locale == "ru"
            super().save(candidate)

    store = ObservingStore(path)
    events = EventBusStub()
    request = _request(runtime, store, tmp_path, events)
    monkeypatch.setattr(
        settings_route,
        "get_public_settings",
        lambda _request: {"interface_locale": runtime.interface_locale},
    )

    result = asyncio.run(settings_route.patch_runtime_settings(
        RuntimeSettingsPatch(interface_locale="en"),
        request,
    ))

    persisted = json.loads(path.read_text(encoding="utf-8"))["settings"]
    assert persisted["interface_locale"] == "en"
    assert runtime.interface_locale == "en"
    assert result == {"interface_locale": "en"}
    assert len(events.events) == 1


def test_settings_fsync_and_replace_stay_off_event_loop(monkeypatch, tmp_path) -> None:
    save_threads: list[int] = []

    class RecordingStore(RuntimeSettingsStore):
        def save(self, candidate: RuntimeSettings) -> None:
            save_threads.append(get_ident())
            super().save(candidate)

    runtime = RuntimeSettings(interface_locale="ru")
    store = RecordingStore(tmp_path / "settings.json")
    request = _request(runtime, store, tmp_path)
    monkeypatch.setattr(settings_route, "get_public_settings", lambda _request: {})

    async def invoke() -> int:
        event_loop_thread = get_ident()
        await settings_route.patch_runtime_settings(
            RuntimeSettingsPatch(interface_locale="en"),
            request,
        )
        return event_loop_thread

    event_loop_thread = asyncio.run(invoke())

    assert save_threads
    assert all(thread_id != event_loop_thread for thread_id in save_threads)


def test_concurrent_api_patches_rebase_disjoint_fields(monkeypatch, tmp_path) -> None:
    barrier = Barrier(2)

    class BarrierStore(RuntimeSettingsStore):
        @contextmanager
        def transaction(self):
            barrier.wait(timeout=5)
            with super().transaction():
                yield

    path = tmp_path / "settings.json"
    store = BarrierStore(path)
    runtime = RuntimeSettings(interface_locale="ru", memory_mode="balanced")
    request = _request(runtime, store, tmp_path)
    monkeypatch.setattr(settings_route, "get_public_settings", lambda _request: {})

    def patch(payload: RuntimeSettingsPatch) -> None:
        asyncio.run(settings_route.patch_runtime_settings(payload, request))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(patch, RuntimeSettingsPatch(interface_locale="en")),
            executor.submit(patch, RuntimeSettingsPatch(memory_mode="automatic")),
        ]
        for future in futures:
            future.result(timeout=10)

    persisted = RuntimeSettingsStore(path).load(RuntimeSettings())
    assert runtime.interface_locale == "en"
    assert runtime.memory_mode == "automatic"
    assert persisted.interface_locale == "en"
    assert persisted.memory_mode == "automatic"


def test_concurrent_store_writers_never_share_or_leave_temp_files(tmp_path) -> None:
    path = tmp_path / "settings.json"

    def write(index: int) -> None:
        # Separate instances exercise unique temp names in addition to the
        # per-instance lock used by the API.
        RuntimeSettingsStore(path).save(RuntimeSettings(
            personality=f"profile-{index}",
            voice_output_device_id=f"device-{index}",
        ))

    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(write, range(80)))

    payload = json.loads(path.read_text(encoding="utf-8"))
    personality_index = payload["settings"]["personality"].removeprefix("profile-")
    device_index = payload["settings"]["voice_output_device_id"].removeprefix("device-")
    assert personality_index == device_index
    assert not list(tmp_path.glob(".settings.json.*.tmp"))
    assert not (tmp_path / "settings.tmp").exists()


def test_replace_failure_preserves_old_file_and_cleans_unique_temp(monkeypatch, tmp_path) -> None:
    path = tmp_path / "settings.json"
    store = RuntimeSettingsStore(path)
    store.save(RuntimeSettings(interface_locale="ru"))
    before = path.read_bytes()

    def fail_replace(_source, _destination) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr("apps.backend.app.runtime.settings.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        store.save(RuntimeSettings(interface_locale="en"))

    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".settings.json.*.tmp"))


def test_developer_mode_enabled_patches_and_persists(monkeypatch, tmp_path) -> None:
    path = tmp_path / "settings.json"
    store = RuntimeSettingsStore(path)
    runtime = RuntimeSettings(developer_mode_enabled=False)
    store.save(runtime)
    request = _request(runtime, store, tmp_path)
    monkeypatch.setattr(
        settings_route,
        "get_public_settings",
        lambda req: SimpleNamespace(developer_mode_enabled=req.app.state.runtime_settings.developer_mode_enabled),
    )

    response = asyncio.run(settings_route.patch_runtime_settings(
        RuntimeSettingsPatch(developer_mode_enabled=True),
        request,
    ))

    assert response.developer_mode_enabled is True
    assert runtime.developer_mode_enabled is True
    persisted = store.load(RuntimeSettings())
    assert persisted.developer_mode_enabled is True

