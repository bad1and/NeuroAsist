from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class RuntimeSettings:
    personality: str = "default"
    voice_language: str = "ru"
    voice_tts_voice: str | None = None
    voice_playback_rate: float = 1.0
    voice_live_playback_prebuffer_segments: int = 1
    voice_live_playback_prebuffer_ms: int = 0
    memory_mode: str = "balanced"
    memory_incognito: bool = False
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
