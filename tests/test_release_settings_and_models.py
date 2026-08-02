import hashlib
import sqlite3
import time
from pathlib import Path
from zipfile import ZipFile

from apps.backend.app.model_manager.service import ModelManager, ModelSpec
from apps.backend.app.runtime.settings import RuntimeSettings, RuntimeSettingsStore
from apps.backend.app.storage.backups import BackupService


def test_runtime_settings_survive_restart_without_secrets(tmp_path: Path) -> None:
    store = RuntimeSettingsStore(tmp_path / "settings.json")
    values = RuntimeSettings(
        voice_language="en",
        memory_mode="automatic",
        avatar_placement="in_app",
        avatar_in_app_visible=False,
    )

    store.save(values)
    loaded = store.load(RuntimeSettings())

    assert loaded.voice_language == "en"
    assert loaded.memory_mode == "automatic"
    assert loaded.avatar_placement == "in_app"
    assert loaded.avatar_in_app_visible is False
    assert "api" not in (tmp_path / "settings.json").read_text(encoding="utf-8").lower()


def test_legacy_ask_memory_mode_is_migrated_to_balanced(tmp_path: Path) -> None:
    store = RuntimeSettingsStore(tmp_path / "settings.json")
    store.save(RuntimeSettings(memory_mode="ask"))

    loaded = store.load(RuntimeSettings())

    assert loaded.memory_mode == "balanced"
    assert '"balanced"' in (tmp_path / "settings.json").read_text(encoding="utf-8")


def test_existing_avatar_settings_default_to_visible_in_iris(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        '{"schema_version": 1, "settings": {"avatar_placement": "in_app", "avatar_overlay_visible": false}}',
        encoding="utf-8",
    )

    loaded = RuntimeSettingsStore(path).load(RuntimeSettings())

    assert loaded.avatar_placement == "in_app"
    assert loaded.avatar_in_app_visible is True


def test_model_manager_downloads_and_verifies_pinned_file(tmp_path: Path) -> None:
    source = tmp_path / "source.jit"
    source.write_bytes(b"silero fixture")
    spec = ModelSpec(
        id="fixture",
        name="Fixture",
        version="1",
        url=source.as_uri(),
        relative_path="fixture/1/model.jit",
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        size_bytes=source.stat().st_size,
    )
    manager = ModelManager(tmp_path / "models", specs=(spec,))

    manager.install_async("fixture")
    for _ in range(50):
        state = manager.model_state("fixture")
        if state["status"] != "downloading":
            break
        time.sleep(.01)

    assert state["status"] == "installed"
    assert state["installed"] is True
    assert manager.path_for("fixture").read_bytes() == source.read_bytes()


def test_backup_snapshots_database_and_nonsecret_settings(tmp_path: Path) -> None:
    database = tmp_path / "data" / "neuroasist.sqlite3"
    database.parent.mkdir()
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE note (value TEXT)")
    connection.execute("INSERT INTO note VALUES ('kept')")
    connection.commit()
    connection.close()
    settings = tmp_path / "settings.json"
    settings.write_text('{"schema_version": 1}', encoding="utf-8")
    service = BackupService(tmp_path / "backups", database, settings)

    backup = service.create()

    with ZipFile(tmp_path / "backups" / str(backup["name"])) as archive:
        assert sorted(archive.namelist()) == ["data/neuroasist.sqlite3", "settings.json"]
        archive.extract("data/neuroasist.sqlite3", tmp_path / "restored")

    restored = sqlite3.connect(tmp_path / "restored" / "data" / "neuroasist.sqlite3")
    try:
        assert restored.execute("SELECT value FROM note").fetchone() == ("kept",)
    finally:
        restored.close()
