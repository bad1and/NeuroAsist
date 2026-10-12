"""Stopped-core maintenance with crash recovery before normal service construction."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from .backups import ARCHIVE_FILES, BackupService


def _checked_subtree(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if resolved == root.resolve() or not resolved.is_relative_to(root.resolve()) or path.is_symlink() or path.is_junction():
        raise ValueError("Recovery path is outside the selected profile")
    return path


def recover_interrupted_restore(root: Path) -> bool:
    transaction = _checked_subtree(root, root / ".restore-transaction")
    journal = transaction / "journal.json"
    if not journal.exists():
        return False
    payload = json.loads(journal.read_text(encoding="utf-8"))
    if payload.get("phase") == "committed":
        snapshot_id = payload.get("snapshot_id", "")
        if not isinstance(snapshot_id, str) or len(snapshot_id) != 32 or any(c not in "0123456789abcdef" for c in snapshot_id):
            raise ValueError("Invalid recovery snapshot")
        destination = _checked_subtree(root, root / "recovery-snapshots" / snapshot_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if (transaction / "previous").exists():
            os.replace(_checked_subtree(root, transaction / "previous"), destination)
        shutil.rmtree(transaction)
        return True
    for name, existed in payload["previous"].items():
        if name not in ARCHIVE_FILES | {"data/neuroasist.sqlite3-wal", "data/neuroasist.sqlite3-shm"}:
            raise ValueError("Invalid recovery journal")
        destination = root / name
        if existed:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".recovering")
            shutil.copyfile(transaction / "previous" / name, temporary)
            os.replace(temporary, destination)
        else:
            destination.unlink(missing_ok=True)
    shutil.rmtree(transaction)
    return True


def restore_archive(root: Path, name: str) -> dict[str, object]:
    recover_interrupted_restore(root)
    service = BackupService(root / "backups", root / "data/neuroasist.sqlite3", root / "settings.json")
    archive = service.path_for(name)
    with tempfile.TemporaryDirectory(prefix=".restore-staging-", dir=root) as temporary:
        staging = Path(temporary)
        _checked_subtree(root, staging)
        result = service.validate(archive, staging)
        from apps.backend.app.runtime.settings import RuntimeSettings, RuntimeSettingsStore
        from apps.backend.app.storage.timeline import TimelineStore
        settings_path = staging / "settings.json"
        settings = RuntimeSettingsStore(settings_path).load(RuntimeSettings())
        settings.voice_input_device_id = settings.voice_output_device_id = ""
        settings.coding_project_root = ""
        settings.coding_agent_enabled = False
        RuntimeSettingsStore(settings_path).save(settings)
        database = staging / "data/neuroasist.sqlite3"
        TimelineStore(database).init_db()
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("UPDATE coding_tasks SET status='cancelled', cancellation_requested=1 WHERE status IN ('pending','running','waiting_for_input','review_ready','conflicted')")
            connection.execute("UPDATE background_jobs SET status='cancelled', lease_owner=NULL, lease_until=NULL WHERE type='coding_task' AND status IN ('pending','running')")
        transaction = _checked_subtree(root, root / ".restore-transaction")
        if transaction.exists():
            # An unjournalled staging directory never changed live data.
            shutil.rmtree(transaction)
        previous = transaction / "previous"
        previous.mkdir(parents=True)
        paths = sorted(ARCHIVE_FILES | {"data/neuroasist.sqlite3-wal", "data/neuroasist.sqlite3-shm"})
        existed = {path: (root / path).exists() for path in paths}
        for path, present in existed.items():
            if present:
                target = previous / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / path, target)
        # Keep a normal user-visible pre-restore backup when the current DB is healthy.
        try:
            pre_restore = service.create()["name"] if service.database_path.exists() else None
        except (ValueError, sqlite3.DatabaseError):
            pre_restore = None
        journal = transaction / "journal.json"
        snapshot_id = uuid4().hex
        with journal.open("w", encoding="utf-8") as stream:
            json.dump({"previous": existed, "phase": "pending", "snapshot_id": snapshot_id}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            for path in paths:
                source, target = staging / path, root / path
                if source.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(source, target)
                else:
                    target.unlink(missing_ok=True)
            # The index is derived data. Move it aside rather than delete it.
            index = root / "data/chroma"
            if index.exists():
                retired = _checked_subtree(root, root / "data" / ("chroma-before-restore-" + uuid4().hex))
                os.replace(_checked_subtree(root, index), retired)
            committed = transaction / "committed.tmp"
            with committed.open("w", encoding="utf-8") as stream:
                json.dump({"previous": existed, "phase": "committed", "snapshot_id": snapshot_id}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(committed, journal)
        except BaseException:
            recover_interrupted_restore(root)
            raise
        recover_interrupted_restore(root)
        return {**result, "restored": True, "previous_backup": pre_restore, "preserved_snapshot": snapshot_id, "devices_reset": True}


def maintenance_main(arguments: list[str]) -> bool:
    import argparse
    if not any(argument.startswith("--maintenance-") for argument in arguments):
        return False
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--maintenance-restore")
    group.add_argument("--maintenance-import", type=Path)
    group.add_argument("--maintenance-remove-model")
    group.add_argument("--maintenance-model-directory", type=Path)
    args = parser.parse_args(arguments)
    root = Path(os.environ["NEUROASIST_APP_DATA_DIR"])
    root.mkdir(parents=True, exist_ok=True)
    service = BackupService(root / "backups", root / "data/neuroasist.sqlite3", root / "settings.json")
    try:
        if args.maintenance_model_directory:
            from apps.backend.app.model_manager.location import set_model_directory
            result = set_model_directory(root, args.maintenance_model_directory)
        elif args.maintenance_remove_model:
            from apps.backend.app.model_manager.service import ModelManager
            from apps.backend.app.model_manager.location import model_root
            result = ModelManager(model_root(root)).remove(args.maintenance_remove_model)
        else:
            result = restore_archive(root, args.maintenance_restore) if args.maintenance_restore else service.import_archive(args.maintenance_import)
        print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, sqlite3.DatabaseError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(1) from error
    return True
