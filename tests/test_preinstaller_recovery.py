import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from zipfile import ZipFile

import pytest

from apps.backend.app.storage.backups import BackupService, check_database
from apps.backend.app.storage.recovery import recover_interrupted_restore, restore_archive
from apps.backend.app.storage.timeline import LATEST_SCHEMA_VERSION, TimelineStore
from apps.backend.app.runtime.settings import RuntimeSettings, RuntimeSettingsStore


def profile(root: Path):
    store = TimelineStore(root / "data/neuroasist.sqlite3")
    store.init_db()
    RuntimeSettingsStore(root / "settings.json").save(RuntimeSettings())
    return store, BackupService(root / "backups", root / "data/neuroasist.sqlite3", root / "settings.json")


def test_restore_preserves_history_memory_and_dictionary_and_keeps_previous_copy(tmp_path):
    store, service = profile(tmp_path)
    message, _ = store.append_message(role="user", content="Сохранённый диалог", input_mode="text")
    (tmp_path / "stt-terms.json").write_text('{"terms": ["Ирис"]}', encoding="utf-8")
    backup = service.create()
    store.append_message(role="user", content="Более новый диалог", input_mode="text")
    result = restore_archive(tmp_path, backup["name"])
    assert result["restored"] and result["previous_backup"]
    restored = TimelineStore(service.database_path)
    restored.init_db()
    assert [m.content for m in restored.list_messages(20)[0]] == ["Сохранённый диалог"]
    assert json.loads((tmp_path / "stt-terms.json").read_text(encoding="utf-8"))["terms"] == ["Ирис"]
    assert not (tmp_path / ".restore-transaction").exists()


def test_legacy_zip_import_and_restore(tmp_path):
    source = tmp_path / "source"
    store, service = profile(source)
    store.append_message(role="user", content="Старая копия", input_mode="text")
    archive_path = tmp_path / "legacy.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.write(service.database_path, "data/neuroasist.sqlite3")
        archive.write(service.settings_path, "settings.json")
    _, target = profile(tmp_path / "target")
    imported = target.import_archive(archive_path)
    assert restore_archive(tmp_path / "target", imported["name"])["legacy"]


@pytest.mark.parametrize("name", ["../settings.json", "data/../../escape", "/escape", "keys.json"])
def test_unknown_and_traversal_paths_are_rejected_without_changing_live_data(tmp_path, name):
    store, service = profile(tmp_path)
    store.append_message(role="user", content="Не трогать", input_mode="text")
    before = service.database_path.read_bytes()
    malicious = tmp_path / "invalid.zip"
    with ZipFile(malicious, "w") as archive:
        archive.writestr(name, "bad")
    with pytest.raises(ValueError):
        service.import_archive(malicious)
    assert service.database_path.read_bytes() == before


def test_mismatched_manifest_and_newer_database_rejected(tmp_path):
    store, service = profile(tmp_path)
    backup = service.create()
    source = service.path_for(backup["name"])
    invalid = tmp_path / "mismatch.zip"
    with ZipFile(source) as original, ZipFile(invalid, "w") as output:
        for name in original.namelist():
            output.writestr(name, original.read(name) if name != "settings.json" else b'{}')
    with pytest.raises(ValueError, match="сумма"):
        service.import_archive(invalid)
    with closing(sqlite3.connect(service.database_path)) as connection, connection:
        connection.execute("INSERT INTO schema_migrations VALUES (999, 'future')")
    with pytest.raises(ValueError, match="новой"):
        check_database(service.database_path)


def test_interrupted_restore_rolls_back_all_files(tmp_path):
    _, service = profile(tmp_path)
    original = service.settings_path.read_bytes()
    transaction = tmp_path / ".restore-transaction"
    (transaction / "previous").mkdir(parents=True)
    (transaction / "previous/settings.json").write_bytes(original)
    (transaction / "journal.json").write_text(json.dumps({"previous": {"settings.json": True, "stt-terms.json": False}}))
    service.settings_path.write_text("replaced")
    (tmp_path / "stt-terms.json").write_text("partial")
    assert recover_interrupted_restore(tmp_path)
    assert service.settings_path.read_bytes() == original
    assert not (tmp_path / "stt-terms.json").exists()


def test_new_backup_filters_unknown_credentials(tmp_path):
    _, service = profile(tmp_path)
    service.settings_path.write_text(json.dumps({"schema_version": 1, "settings": {"deepseek_api_key": "must-not-export", "interface_locale": "en"}}))
    backup = service.create()
    with ZipFile(service.path_for(backup["name"])) as archive:
        assert b"must-not-export" not in archive.read("settings.json")


def test_corrupt_database_is_preserved(tmp_path):
    path = tmp_path / "data.sqlite3"
    path.write_bytes(b"damaged database")
    with pytest.raises(sqlite3.DatabaseError):
        TimelineStore(path).init_db()
    assert path.read_bytes() == b"damaged database"


def test_restore_failure_during_replacement_rolls_back(tmp_path, monkeypatch):
    import apps.backend.app.storage.recovery as recovery
    store, service = profile(tmp_path)
    store.append_message(role="user", content="Из копии", input_mode="text")
    backup = service.create()
    store.append_message(role="user", content="Текущие данные", input_mode="text")
    original = service.database_path.read_bytes()
    replace = recovery.os.replace
    failed = False

    def interrupt(source, target):
        nonlocal failed
        if not failed and ".restore-staging-" in str(source) and Path(target).name == "settings.json":
            failed = True
            raise OSError("simulated interruption")
        return replace(source, target)

    monkeypatch.setattr(recovery.os, "replace", interrupt)
    with pytest.raises(OSError, match="simulated"):
        restore_archive(tmp_path, backup["name"])
    assert failed
    assert service.database_path.read_bytes() == original
    assert not (tmp_path / ".restore-transaction").exists()


def test_committed_restore_finalizes_without_rolling_back(tmp_path):
    _, service = profile(tmp_path)
    transaction = tmp_path / ".restore-transaction"
    (transaction / "previous").mkdir(parents=True)
    (transaction / "previous/settings.json").write_text("old")
    snapshot_id = "a" * 32
    (transaction / "journal.json").write_text(json.dumps({"phase": "committed", "snapshot_id": snapshot_id}))
    current = service.settings_path.read_bytes()
    assert recover_interrupted_restore(tmp_path)
    assert service.settings_path.read_bytes() == current
    assert (tmp_path / "recovery-snapshots" / snapshot_id / "settings.json").read_text() == "old"
    assert not (tmp_path / ".restore-transaction").exists()


def test_migration_replaces_invalid_snapshot_without_losing_it(tmp_path):
    store, service = profile(tmp_path)
    with closing(sqlite3.connect(service.database_path)) as connection, connection:
        connection.execute("DELETE FROM schema_migrations WHERE version=?", (LATEST_SCHEMA_VERSION,))
    snapshot = service.database_path.parent / f"migration-backups/neuroasist-schema-{LATEST_SCHEMA_VERSION - 1}.sqlite3"
    snapshot.parent.mkdir(exist_ok=True)
    snapshot.write_bytes(b"interrupted snapshot")
    store.init_db()
    assert check_database(snapshot) == LATEST_SCHEMA_VERSION - 1
    preserved = list(snapshot.parent.glob(snapshot.name + ".invalid-*"))
    assert len(preserved) == 1 and preserved[0].read_bytes() == b"interrupted snapshot"
    assert check_database(service.database_path) == LATEST_SCHEMA_VERSION


def test_snapshot_publication_failure_keeps_existing_copy(tmp_path, monkeypatch):
    import apps.backend.app.storage.backups as backups
    _, service = profile(tmp_path)
    snapshot = tmp_path / "previous.sqlite3"
    backups.snapshot_database(service.database_path, snapshot)
    original = snapshot.read_bytes()
    def fail_publish(*_args):
        raise OSError("simulated publication failure")
    monkeypatch.setattr(backups.os, "replace", fail_publish)
    with pytest.raises(OSError, match="publication"):
        backups.snapshot_database(service.database_path, snapshot)
    assert snapshot.read_bytes() == original
    assert not list(tmp_path.glob("previous.sqlite3.*.tmp"))
