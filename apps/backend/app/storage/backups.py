from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

BACKUP_NAME = re.compile(r"^neuroasist-\d{8}T\d{6}(?:\d{6})?Z\.zip$")
ARCHIVE_FILES = frozenset({"data/neuroasist.sqlite3", "settings.json", "stt-terms.json", "tts-pronunciations.json"})
MAX_ARCHIVE_BYTES = 2 * 1024**3


def check_database(path: Path, *, maximum_schema: int | None = None, require_iris: bool = True) -> int:
    if maximum_schema is None:
        from apps.backend.app.storage.timeline import LATEST_SCHEMA_VERSION
        maximum_schema = LATEST_SCHEMA_VERSION
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("База повреждена. Исходные данные сохранены.")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if require_iris and not tables.intersection({"messages", "conversation_messages"}):
            raise ValueError("Архив не содержит базу Iris.")
        version = int(connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]) if "schema_migrations" in tables else 0
        if version > maximum_schema:
            raise ValueError("База создана более новой версией Iris.")
        return version


def snapshot_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + "." + uuid4().hex + ".tmp")
    try:
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as origin, closing(sqlite3.connect(temporary)) as target:
            with target:
                origin.backup(target)
        check_database(temporary, require_iris=False)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


class BackupService:
    """Portable backups; restore runs only with the application core stopped."""

    def __init__(self, directory: Path, database_path: Path, settings_path: Path, retention_days: int = 30) -> None:
        self.directory, self.database_path, self.settings_path = directory, database_path, settings_path
        self.retention_days = retention_days

    def path_for(self, name: str) -> Path:
        if not BACKUP_NAME.fullmatch(name):
            raise ValueError("Invalid backup name")
        return self.directory / name

    def list(self) -> list[dict[str, object]]:
        return [{"name": p.name, "size_bytes": p.stat().st_size, "created_at": datetime.fromtimestamp(p.stat().st_mtime, UTC).isoformat()}
                for p in sorted(self.directory.glob("neuroasist-*.zip"), reverse=True) if BACKUP_NAME.fullmatch(p.name)]

    def create(self) -> dict[str, object]:
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.directory / f"neuroasist-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.zip"
        temporary_archive = destination.with_suffix(".tmp")
        try:
            with tempfile.TemporaryDirectory(prefix="iris-backup-") as temporary:
                snapshot = Path(temporary) / "neuroasist.sqlite3"
                files = {}
                if self.database_path.exists():
                    snapshot_database(self.database_path, snapshot)
                    files["data/neuroasist.sqlite3"] = snapshot
                for name in ("settings.json", "stt-terms.json", "tts-pronunciations.json"):
                    path = self.settings_path if name == "settings.json" else self.settings_path.parent / name
                    if path.exists():
                        frozen = Path(temporary) / name
                        if name == "settings.json":
                            from dataclasses import fields
                            from apps.backend.app.runtime.settings import RuntimeSettings
                            payload = json.loads(path.read_text(encoding="utf-8"))
                            allowed = {field.name for field in fields(RuntimeSettings)}
                            values = payload.get("settings", {}) if isinstance(payload, dict) else {}
                            frozen.write_text(json.dumps({"schema_version": 1, "settings": {key: value for key, value in values.items() if key in allowed}}, ensure_ascii=False), encoding="utf-8")
                        else:
                            shutil.copyfile(path, frozen)
                        files[name] = frozen
                from apps.backend.app.core.config import APP_VERSION
                manifest = {"format_version": 1, "app_version": APP_VERSION, "created_at": datetime.now(UTC).isoformat(),
                            "files": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}}
                with ZipFile(temporary_archive, "w", ZIP_DEFLATED) as archive:
                    for name, path in files.items():
                        archive.write(path, name)
                    archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            os.replace(temporary_archive, destination)
        finally:
            temporary_archive.unlink(missing_ok=True)
        self.prune()
        return next(item for item in self.list() if item["name"] == destination.name)

    def validate(self, archive_path: Path, destination: Path) -> dict[str, object]:
        if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("Архив слишком большой.")
        try:
            with ZipFile(archive_path) as archive:
                names = [item.filename for item in archive.infolist()]
                if len(names) != len(set(names)) or set(names) - ARCHIVE_FILES - {"manifest.json"}:
                    raise ValueError("Архив содержит неизвестные или повторяющиеся пути.")
                if "data/neuroasist.sqlite3" not in names or sum(item.file_size for item in archive.infolist()) > MAX_ARCHIVE_BYTES:
                    raise ValueError("Нет базы Iris или превышен допустимый размер.")
                if any(item.file_size > 1024**2 for item in archive.infolist() if item.filename.endswith(".json")):
                    raise ValueError("Некорректный размер настроек копии.")
                manifest = json.loads(archive.read("manifest.json")) if "manifest.json" in names else None
                if manifest is not None and (not isinstance(manifest, dict) or manifest.get("format_version") != 1):
                    raise ValueError("Неподдерживаемый формат копии.")
                if manifest is not None and set(manifest.get("files", {})) != set(names) - {"manifest.json"}:
                    raise ValueError("Состав архива не совпадает с манифестом.")
                for name in names:
                    if name == "manifest.json":
                        continue
                    path = destination / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(name) as source, path.open("wb") as target:
                        shutil.copyfileobj(source, target)
                    if manifest is not None and hashlib.sha256(path.read_bytes()).hexdigest() != manifest["files"][name]:
                        raise ValueError("Контрольная сумма копии не совпадает.")
                schema = check_database(destination / "data/neuroasist.sqlite3")
                for name in names:
                    if name.endswith(".json") and name != "manifest.json":
                        payload = json.loads((destination / name).read_text(encoding="utf-8"))
                        if not isinstance(payload, dict):
                            raise ValueError("Некорректный формат настроек.")
                return {"valid": True, "schema_version": schema, "legacy": manifest is None}
        except (BadZipFile, sqlite3.DatabaseError, json.JSONDecodeError, UnicodeError, KeyError, TypeError) as error:
            raise ValueError("Повреждённая резервная копия. Текущие данные сохранены.") from error

    def import_archive(self, source: Path) -> dict[str, object]:
        with tempfile.TemporaryDirectory(prefix="iris-import-") as staging:
            self.validate(source, Path(staging))
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.directory / f"neuroasist-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.zip"
        shutil.copyfile(source, destination)
        return next(item for item in self.list() if item["name"] == destination.name)

    def delete(self, name: str) -> None:
        self.path_for(name).unlink(missing_ok=True)

    def prune(self) -> int:
        cutoff = datetime.now(UTC).timestamp() - self.retention_days * 86400
        old = [self.path_for(str(item["name"])) for item in self.list() if self.path_for(str(item["name"])).stat().st_mtime < cutoff]
        for path in old:
            path.unlink(missing_ok=True)
        return len(old)

    def _snapshot_database(self, destination: Path) -> None:
        if self.database_path.exists():
            snapshot_database(self.database_path, destination)
