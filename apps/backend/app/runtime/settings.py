from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class RuntimeSettings:
    personality: str = "default"
    voice_language: str = "ru"
    voice_microphone_profile: str = "balanced"
    voice_tts_voice: str | None = None
    voice_playback_rate: float = 1.0
    voice_live_playback_prebuffer_segments: int = 1
    voice_live_playback_prebuffer_ms: int = 0
    memory_mode: str = "balanced"
    memory_incognito: bool = False
    reflections_enabled: bool = True
    reflection_min_significance: float = 0.55
    live_conversation_enabled: bool = False
    live_conversation_participant_mode: str = "one_to_one"
    live_conversation_engagement: str = "balanced"
    live_conversation_initiative: str = "rare"
    live_conversation_address_strictness: str = "balanced"
    live_conversation_interruption_sensitivity: str = "balanced"
    live_conversation_pause_tolerance: str = "natural"
    live_conversation_emotion_expression: str = "natural"
    live_conversation_mood_recovery: str = "natural"
    live_conversation_recent_event_weight: str = "balanced"
    live_conversation_echo_mode: str = "auto"
    # The desktop shell consumes this preference before it starts the Unity
    # renderer.  It intentionally lives next to the overlay preferences so a
    # backup restores the avatar exactly as the person left it.
    avatar_placement: str = "desktop_overlay"
    # This controls the chat-hosted avatar only.  It must not reuse the
    # desktop-overlay flag: a hidden desktop popup must not make the avatar
    # disappear after switching it into Iris.
    avatar_in_app_visible: bool = True
    avatar_overlay_visible: bool = True
    avatar_overlay_always_on_top: bool = True
    avatar_overlay_locked: bool = True
    avatar_overlay_scale: float = 1.0
    avatar_overlay_monitor: str = "primary"
    avatar_overlay_x: float = 80.0
    avatar_overlay_y: float = 80.0
    avatar_overlay_width: float = 640.0
    avatar_overlay_height: float = 720.0


class RuntimeSettingsStore:
    """Versioned, atomic storage for non-secret desktop preferences."""

    schema_version = 1

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, defaults: RuntimeSettings) -> RuntimeSettings:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return defaults
        if not isinstance(payload, dict) or payload.get("schema_version") != self.schema_version:
            return defaults
        if not isinstance(payload.get("settings"), dict):
            return defaults
        defaults_dict = asdict(defaults)
        values = {
            key: value
            for key, value in payload["settings"].items()
            if key in defaults_dict
            and (defaults_dict[key] is None or isinstance(value, type(defaults_dict[key])))
        }
        # V0.5 originally defaulted to ``ask`` but never surfaced a useful
        # confirmation prompt in the conversation.  Treat persisted values as
        # the new guided policy so existing local users receive the intended
        # behaviour after upgrading.
        if values.get("memory_mode") == "ask":
            values["memory_mode"] = "balanced"
        if values.get("avatar_placement") not in {None, "desktop_overlay", "in_app"}:
            values["avatar_placement"] = defaults.avatar_placement
        try:
            loaded = RuntimeSettings(**{**defaults_dict, **values})
        except TypeError:
            return defaults
        if payload["settings"].get("memory_mode") == "ask":
            try:
                self.save(loaded)
            except OSError:
                # A read-only settings file must not prevent the app starting.
                pass
        return loaded

    def save(self, settings: RuntimeSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"schema_version": self.schema_version, "settings": asdict(settings)},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
