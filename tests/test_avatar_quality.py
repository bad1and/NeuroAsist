import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from apps.backend.app.api.routes import settings as settings_route
from apps.backend.app.avatar.connection_manager import AvatarConnectionManager
from apps.backend.app.avatar.protocol import parse_incoming
from apps.backend.app.avatar.schemas import RenderQualityPayload
from apps.backend.app.avatar.service import AvatarService
from apps.backend.app.events.bus import EventBus
from apps.backend.app.runtime.settings import RuntimeSettings, RuntimeSettingsStore
from apps.backend.app.schemas.settings import RuntimeSettingsPatch


def test_old_and_corrupt_preferences_keep_per_placement_defaults(tmp_path):
    path = tmp_path / "settings.json"
    store = RuntimeSettingsStore(path)
    for values in ({}, {"avatar_in_app_quality": None, "avatar_desktop_quality": ["ultra"]}):
        path.write_text(json.dumps({"schema_version": 1, "settings": {"memory_incognito": True, **values}}))
        loaded = store.load(RuntimeSettings())
        assert loaded.avatar_in_app_quality == "high"
        assert loaded.avatar_desktop_quality == "medium"
        assert loaded.memory_incognito


@pytest.mark.anyio
async def test_independent_quality_preferences_persist_before_live_apply(monkeypatch, tmp_path):
    runtime = RuntimeSettings()
    store = RuntimeSettingsStore(tmp_path / "settings.json")
    observed = []

    async def configure(quality):
        loaded = store.load(RuntimeSettings())
        assert (loaded.avatar_in_app_quality, loaded.avatar_desktop_quality) == (quality.in_app_quality, quality.desktop_quality)
        observed.append(quality.model_dump())

    state = SimpleNamespace(runtime_settings=runtime, runtime_settings_store=store,
        settings=SimpleNamespace(deepseek_model="test", coding_allowed_project_paths=(tmp_path,)),
        event_bus=EventBus(), avatar_service=SimpleNamespace(configure_render_quality=configure))
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    monkeypatch.setattr(settings_route, "get_public_settings", lambda request: {})
    await settings_route.patch_runtime_settings(RuntimeSettingsPatch(avatar_desktop_quality="high"), request)
    await settings_route.patch_runtime_settings(RuntimeSettingsPatch(avatar_in_app_quality="low"), request)
    assert observed == [
        {"in_app_quality": "high", "desktop_quality": "high"},
        {"in_app_quality": "low", "desktop_quality": "high"},
    ]
    assert runtime.avatar_placement == "desktop_overlay"

    state.avatar_service.configure_render_quality = AsyncMock()
    monkeypatch.setattr(store, "save", lambda candidate: (_ for _ in ()).throw(OSError("full disk")))
    with pytest.raises(HTTPException) as error:
        await settings_route.patch_runtime_settings(RuntimeSettingsPatch(avatar_desktop_quality="low"), request)
    assert error.value.status_code == 503
    assert runtime.avatar_desktop_quality == "high"
    state.avatar_service.configure_render_quality.assert_not_awaited()


@pytest.mark.parametrize("value", ["ultra", "", 8, ["high"]])
def test_quality_rejects_values_outside_presets(value):
    with pytest.raises(ValidationError):
        RuntimeSettingsPatch(avatar_desktop_quality=value)


@pytest.mark.anyio
async def test_quality_applies_live_and_replays_on_renderer_reconnect():
    class Socket:
        def __init__(self): self.sent = []
        async def send_json(self, frame): self.sent.append(frame)

    manager = AvatarConnectionManager()
    service = AvatarService(manager, EventBus(), enabled=True,
        heartbeat_interval_seconds=30, client_timeout_seconds=60)
    first = await manager.register(Socket())
    await manager.update(first.client_id, protocol_version=2)
    quality = RenderQualityPayload(in_app_quality="low", desktop_quality="high")
    await service.configure_render_quality(quality)
    assert first.websocket.sent[-1]["payload"] == quality.model_dump()
    second = await manager.register(Socket())
    envelope, payload = parse_incoming({"protocol_version": 2, "type": "avatar.hello",
        "message_id": "hello", "payload": {"client_name": "test", "client_version": "test", "platform": "Windows", "supported_protocol_versions": [1, 2]}})
    await service.inbound(second.client_id, envelope, payload)
    frames = [frame for frame in second.websocket.sent if frame["type"] == "avatar.render.quality"]
    assert len(frames) == 1 and frames[0]["payload"] == quality.model_dump()
