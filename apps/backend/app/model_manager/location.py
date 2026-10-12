"""Machine-local model storage; deliberately excluded from portable backups."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def model_root(profile: Path) -> Path:
    config = profile / "models-location.json"
    if not config.exists():
        return profile / "models"
    value = json.loads(config.read_text(encoding="utf-8"))["directory"]
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("Папка моделей должна иметь абсолютный путь.")
    return path


def set_model_directory(profile: Path, parent: Path) -> dict[str, str]:
    if not parent.is_absolute() or not parent.is_dir():
        raise ValueError("Выберите существующую папку для моделей.")
    # Own a dedicated child, never the user's selected directory itself.
    target = parent.resolve() / "Iris-models"
    target.mkdir(exist_ok=True)
    with tempfile.TemporaryFile(dir=target) as probe:
        probe.write(b"Iris")
        probe.flush()
        os.fsync(probe.fileno())
    profile.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="models-location-", suffix=".tmp", dir=profile)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"directory": str(target)}, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, profile / "models-location.json")
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {"directory": str(target)}
