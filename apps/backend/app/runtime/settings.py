from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock, RLock
from typing import Iterator


_STORE_LOCKS_GUARD = Lock()
_STORE_LOCKS: dict[str, RLock] = {}


def _shared_store_lock(path: Path) -> RLock:
    """Return one process-wide lock for every normalized destination path."""
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    with _STORE_LOCKS_GUARD:
        return _STORE_LOCKS.setdefault(key, RLock())


@dataclass
class RuntimeSettings:
    # This controls only the application chrome and visible UI copy.  It must
    # stay independent from ``voice_language`` so changing the interface does
    # not alter Iris, STT, TTS, or the user's conversation data.
    interface_locale: str = "ru"
    developer_mode_enabled: bool = False
    personality: str = "default"
    voice_language: str = "ru"
    voice_microphone_profile: str = "balanced"
    # Browser/Windows device IDs are opaque, machine-local identifiers. An
    # empty value deliberately means "follow the operating-system default".
    voice_input_device_id: str = ""
    voice_output_device_id: str = ""
    voice_tts_voice: str | None = None
    voice_playback_rate: float = 1.0
    voice_live_playback_prebuffer_segments: int = 1
    voice_live_playback_prebuffer_ms: int = 0
    memory_mode: str = "balanced"
    memory_incognito: bool = False
    reflections_enabled: bool = True
    reflection_min_significance: float = 0.55
    live_conversation_enabled: bool = True
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
    # Coding Agent preferences are deliberately non-secret.  The service
    # receives credentials only from static Settings / the desktop keyring.
    coding_agent_enabled: bool = False
    coding_model: str = "deepseek-v4-flash"
    # Empty means the first server-configured allowed project root.
    coding_project_root: str = ""
    coding_workspace_name: str = "default"
    coding_auto_delegate: bool = True


class RuntimeSettingsStore:
    """Versioned, atomic storage for non-secret desktop preferences."""

    schema_version = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = _shared_store_lock(path)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Serialize a read/validate/save/publish transaction for this store."""
        with self._lock:
            yield

    def load(self, defaults: RuntimeSettings) -> RuntimeSettings:
        with self._lock:
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
            # Voice is live-only since protocol v3. Keep the field readable for
            # old settings files, but never allow a persisted flag to disable it.
            values["live_conversation_enabled"] = True
            if values.get("interface_locale") not in {None, "ru", "en"}:
                values["interface_locale"] = defaults.interface_locale
            if values.get("avatar_placement") not in {None, "desktop_overlay", "in_app"}:
                values["avatar_placement"] = defaults.avatar_placement
            if values.get("coding_model") not in {None, "deepseek-v4-flash", "deepseek-v4-pro"}:
                values["coding_model"] = defaults.coding_model
            workspace_name = values.get("coding_workspace_name")
            if workspace_name is not None and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}", workspace_name):
                values["coding_workspace_name"] = defaults.coding_workspace_name
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
        serialized = json.dumps(
            {"schema_version": self.schema_version, "settings": asdict(settings)},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=self.path.parent,
                    prefix=f".{self.path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as temporary:
                    temporary_path = Path(temporary.name)
                    temporary.write(serialized)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                os.replace(temporary_path, self.path)
                temporary_path = None
            finally:
                if temporary_path is not None:
                    try:
                        temporary_path.unlink(missing_ok=True)
                    except OSError:
                        pass
