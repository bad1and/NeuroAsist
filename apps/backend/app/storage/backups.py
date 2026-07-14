from __future__ import annotations

import re
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


BACKUP_NAME = re.compile(r"^neuroasist-\d{8}T\d{6}Z\.zip$")


class BackupService:
    """Creates portable user backups without ever copying an API key."""

    def __init__(self, directory: Path, database_path: Path, settings_path: Path, retention_days: int = 30) -> None:
        self.directory = directory
        self.database_path = database_path
        self.settings_path = settings_path
        self.retention_days = retention_days

    def list(self) -> list[dict[str, object]]:
        if not self.directory.exists():
            return []
        return [
            {"name": path.name, "size_bytes": path.stat().st_size, "created_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()}
            for path in sorted(self.directory.glob("neuroasist-*.zip"), reverse=True)
            if BACKUP_NAME.match(path.name)
        ]

    def create(self) -> dict[str, object]:
        self.directory.mkdir(parents=True, exist_ok=True)
        name = f"neuroasist-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.zip"
        destination = self.directory / name
        with tempfile.TemporaryDirectory(prefix="neuroasist-backup-") as temporary_dir:
            snapshot = Path(temporary_dir) / "neuroasist.sqlite3"
            self._snapshot_database(snapshot)
            with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
                if snapshot.exists():
                    archive.write(snapshot, "data/neuroasist.sqlite3")
                if self.settings_path.exists():
                    archive.write(self.settings_path, "settings.json")
        self.prune()
        return next(item for item in self.list() if item["name"] == name)

    def delete(self, name: str) -> None:
        if not BACKUP_NAME.match(name):
            raise ValueError("Invalid backup name")
        (self.directory / name).unlink(missing_ok=True)

    def prune(self) -> int:
        cutoff = datetime.now(UTC).timestamp() - self.retention_days * 24 * 60 * 60
        removed = 0
        for item in self.list():
            path = self.directory / str(item["name"])
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        return removed

    def _snapshot_database(self, destination: Path) -> None:
        if not self.database_path.exists():
            return
        source = sqlite3.connect(self.database_path)
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
