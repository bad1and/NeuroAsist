import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.backend.app.avatar.schemas import AvatarOverlayPatch, OverlayPayload
from apps.backend.app.api.routes.avatar import update_avatar_overlay, _overlay_from_runtime
from apps.backend.app.api.routes.avatar import avatar_audio_mute
from apps.backend.app.avatar.schemas import AudioMutePayload
from apps.backend.app.runtime.settings import RuntimeSettings, RuntimeSettingsStore


def layout(monitor="left", height=400):
    return {"monitor": monitor, "x_ratio": 0.25, "y_ratio": 0.4, "height_dip": height}


def test_legacy_preferences_keep_defaults_and_new_layouts_survive_reload(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": 1, "settings": {"avatar_overlay_height": 600.0}}))
    store = RuntimeSettingsStore(path)
    settings = store.load(RuntimeSettings())
    assert _overlay_from_runtime(settings).desktop_mode == "waist"
    assert settings.avatar_overlay_height == 600
    settings.avatar_overlay_layouts = {"waist": layout(), "full_body": layout("right", 560)}
    settings.avatar_overlay_desktop_mode = "full_body"
    settings.avatar_overlay_subtitle_position = "left"
    store.save(settings)
    restored = _overlay_from_runtime(store.load(RuntimeSettings()))
    assert restored.desktop_mode == "full_body"
    assert restored.layouts["waist"].monitor == "left"
    assert restored.layouts["full_body"].height_dip == 560
    assert restored.subtitle_position == "left"


@pytest.mark.parametrize("patch", [
    {"desktop_mode": "seated"}, {"subtitle_position": "centre"},
    {"layouts": {"unknown": layout()}}, {"layouts": {"waist": layout(height=float("nan"))}},
    {"layouts": {"full_body": {**layout(), "x_ratio": 2}}},
])
def test_invalid_layout_cannot_reach_native_host(patch):
    with pytest.raises(ValidationError):
        AvatarOverlayPatch(**patch)


def test_corrupt_nested_preferences_fall_back_without_losing_other_settings(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": 1, "settings": {
        "avatar_overlay_layouts": {"waist": {"height_dip": "invalid"}},
        "avatar_overlay_desktop_mode": "broken", "avatar_overlay_subtitle_position": "broken",
        "avatar_overlay_visible": False,
    }}))
    restored = RuntimeSettingsStore(path).load(RuntimeSettings())
    assert _overlay_from_runtime(restored).layouts == {}
    assert restored.avatar_overlay_desktop_mode == "waist"
    assert restored.avatar_overlay_subtitle_position == "above"
    assert not restored.avatar_overlay_visible


@pytest.mark.anyio
async def test_concurrent_per_mode_commits_preserve_both_layouts_and_lock(tmp_path):
    settings = RuntimeSettings()
    store = RuntimeSettingsStore(tmp_path / "settings.json")
    sent = []
    async def configure(overlay):
        sent.append(overlay)
        return SimpleNamespace(sent=1)
    state = SimpleNamespace(runtime_settings=settings, runtime_settings_store=store,
        avatar_service=SimpleNamespace(configure_overlay=configure),
        event_bus=SimpleNamespace(publish=lambda *args: None))
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    await asyncio.gather(
        update_avatar_overlay(AvatarOverlayPatch(layouts={"waist": layout()}), request),
        update_avatar_overlay(AvatarOverlayPatch(layouts={"full_body": layout("right", 580)}), request),
        update_avatar_overlay(AvatarOverlayPatch(locked=False), request),
    )
    restored = _overlay_from_runtime(store.load(RuntimeSettings()))
    assert set(restored.layouts) == {"waist", "full_body"}
    assert not restored.locked
    assert len(sent) == 3


def test_geometry_lock_does_not_hide_controls_or_subtitles():
    overlay = OverlayPayload(locked=True, desktop_mode="full_body", subtitles_enabled=True)
    assert overlay.visible and overlay.subtitles_enabled


@pytest.mark.anyio
@pytest.mark.parametrize("device,user_muted,expected", [("",True,True),("",False,False),("headphones",False,True)])
async def test_avatar_mute_preserves_single_output_owner(device,user_muted,expected):
    calls=[]
    async def mute(value):
        calls.append(value)
        return SimpleNamespace(sent=1)
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        runtime_settings=RuntimeSettings(voice_output_device_id=device),
        avatar_service=SimpleNamespace(set_audio_muted=mute))))
    assert (await avatar_audio_mute(AudioMutePayload(muted=user_muted),request))["muted"] is expected
    assert calls == [expected]
