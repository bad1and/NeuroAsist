from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from apps.backend.app.coding.policy import CodingPolicyError, PathPolicy
from apps.backend.app.core.config import Settings


class SnapshotLimitError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChangedFile:
    path: str
    change: str
    before_hash: str | None
    after_hash: str | None
    size: int | None


class TaskSandbox:
    """A task-private copy of selected source files; never a live project mount."""

    def __init__(self, settings: Settings, *, task_id: str, project_root: Path | None, workspace_name: str) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}", workspace_name):
            raise CodingPolicyError("Invalid task workspace name")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", task_id):
            raise CodingPolicyError("Invalid task id")
        self.settings = settings
        self.task_id = task_id
        self.base = (settings.coding_workspace_path / workspace_name / task_id).resolve()
        # Never permit task output below (or around) a source root.  The model
        # writes through host-side tool handlers, so this check is as important
        # as the Docker mount boundary.
        for source_root in settings.coding_allowed_project_paths:
            if _paths_overlap(settings.coding_workspace_path.resolve(), source_root):
                raise CodingPolicyError("Coding workspace root must be separate from every allowed project root")
        self.snapshot_root = self.base / "snapshot"
        self.work_root = self.base / "work"
        self.project_root = project_root.resolve() if project_root is not None else None
        self.policy = PathPolicy(
            self.project_root or self.work_root,
            extensions=settings.coding_allowed_extension_set,
            max_file_bytes=settings.coding_max_file_bytes,
        )
        self._manifest: dict[str, str] = {}

    @property
    def manifest(self) -> dict[str, object]:
        return {
            "version": 1,
            "project_root": str(self.project_root) if self.project_root is not None else None,
            "files": dict(self._manifest),
        }

    def create_snapshot(self, requested_files: list[str] | None = None) -> dict[str, object]:
        if self.project_root is None:
            return self.create_empty_workspace()
        if self.base.exists():
            raise SnapshotLimitError("Task workspace already exists")
        self.snapshot_root.mkdir(parents=True, exist_ok=False)
        selected: set[Path] | None = None
        if requested_files:
            selected = {self.policy.relative(value) for value in requested_files}
        copied, total = 0, 0
        for candidate in self.project_root.rglob("*"):
            if not self.policy.accepts_file(candidate):
                continue
            relative = candidate.relative_to(self.project_root)
            if selected is not None and relative not in selected:
                continue
            size = candidate.stat().st_size
            if size > self.settings.coding_max_file_bytes:
                continue
            copied += 1
            total += size
            if copied > self.settings.coding_max_files:
                raise SnapshotLimitError(
                    "The approved project snapshot exceeds the file limit "
                    f"({copied} > {self.settings.coding_max_files})"
                )
            if total > self.settings.coding_max_total_bytes:
                raise SnapshotLimitError(
                    "The approved project snapshot exceeds the size limit "
                    f"({total} > {self.settings.coding_max_total_bytes} bytes)"
                )
            destination = self.snapshot_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, destination)
            self._manifest[str(relative).replace("\\", "/")] = self._sha256(destination)
        if not self._manifest:
            raise SnapshotLimitError("No approved source files were found for the task")
        shutil.copytree(self.snapshot_root, self.work_root)
        (self.base / "manifest.json").write_text(json.dumps(self.manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.manifest

    def create_empty_workspace(self) -> dict[str, object]:
        """Create a task-private folder for standalone files without copying a project."""
        if self.base.exists():
            raise SnapshotLimitError("Task workspace already exists")
        self.snapshot_root.mkdir(parents=True, exist_ok=False)
        self.work_root.mkdir(parents=True, exist_ok=False)
        (self.base / "manifest.json").write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return self.manifest

    def open_existing(self, manifest: dict[str, object]) -> None:
        """Rehydrate a persisted task for explicit review/apply after restart."""
        files = manifest.get("files") if isinstance(manifest, dict) else None
        if not isinstance(files, dict) or not self.snapshot_root.is_dir() or not self.work_root.is_dir():
            raise SnapshotLimitError("Task workspace is no longer available")
        safe_manifest: dict[str, str] = {}
        for path, digest in files.items():
            relative = self.policy.relative(str(path))
            if relative.suffix.casefold() not in self.policy.extensions:
                raise CodingPolicyError("Task manifest contains an unsupported file")
            safe_manifest[str(relative).replace("\\", "/")] = str(digest)
        self._manifest = safe_manifest

    def read_text(self, relative_path: str) -> str:
        path = self._work_path(relative_path)
        if not path.exists() or not path.is_file():
            raise CodingPolicyError("File does not exist in the task workspace")
        return path.read_text(encoding="utf-8", errors="replace")[: self.settings.coding_max_file_bytes]

    def write_text(self, relative_path: str, content: str) -> None:
        if len(content.encode("utf-8")) > self.settings.coding_max_file_bytes:
            raise CodingPolicyError("File exceeds the Coding Agent size limit")
        path = self._work_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def delete_file(self, relative_path: str) -> None:
        path = self._work_path(relative_path)
        if path.exists():
            path.unlink()

    def changed_files(self) -> list[ChangedFile]:
        current = self._hash_tree(self.work_root)
        changes: list[ChangedFile] = []
        for path in sorted(set(self._manifest) | set(current)):
            before, after = self._manifest.get(path), current.get(path)
            if before == after:
                continue
            changes.append(ChangedFile(
                path=path,
                change="created" if before is None else "deleted" if after is None else "modified",
                before_hash=before,
                after_hash=after,
                size=(self.work_root / path).stat().st_size if after and (self.work_root / path).exists() else None,
            ))
        return changes

    def source_unchanged(self) -> bool:
        if self.project_root is None:
            return True
        for relative, digest in self._manifest.items():
            source = self.project_root / relative
            if not source.exists() or self._sha256(source) != digest:
                return False
        # A task may create a file that did not exist in its snapshot. Never
        # overwrite a same-path file the user created meanwhile.
        for change in self.changed_files():
            if change.change == "created" and (self.project_root / change.path).exists():
                return False
        return True

    def apply_to_source(self) -> list[ChangedFile]:
        if self.project_root is None:
            # In standalone mode the reviewed files already live in the
            # configured task workspace; applying only acknowledges review.
            return self.changed_files()
        if not self.source_unchanged():
            raise RuntimeError("Source project changed since the task snapshot; review/apply is blocked")
        changes = self.changed_files()
        backup_root = self.base / "apply-backup"
        backup_root.mkdir(parents=True, exist_ok=True)
        for change in changes:
            source = self.project_root / change.path
            work = self.work_root / change.path
            if source.exists():
                backup = backup_root / change.path
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, backup)
            if change.change == "deleted":
                if source.exists():
                    source.unlink()
                continue
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(work, source)
        (backup_root / "README.txt").write_text(
            "Pre-apply backup created by NeuroAsist Coding Agent. Keep it until the reviewed change is accepted.\n",
            encoding="utf-8",
        )
        return changes

    def diff_text(self, max_bytes: int) -> str:
        import difflib
        lines: list[str] = []
        for change in self.changed_files():
            before = self.snapshot_root / change.path
            after = self.work_root / change.path
            before_lines = before.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if before.exists() else []
            after_lines = after.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if after.exists() else []
            lines.extend(difflib.unified_diff(before_lines, after_lines, fromfile=f"a/{change.path}", tofile=f"b/{change.path}"))
            if len("".join(lines).encode("utf-8")) > max_bytes:
                return "".join(lines).encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore") + "\n... diff truncated ...\n"
        return "".join(lines)

    def _work_path(self, relative_path: str) -> Path:
        relative = self.policy.relative(relative_path)
        target = (self.work_root / relative).resolve()
        try:
            target.relative_to(self.work_root.resolve())
        except ValueError as error:
            raise CodingPolicyError("Path is outside the task workspace") from error
        return target

    def _hash_tree(self, root: Path) -> dict[str, str]:
        values: dict[str, str] = {}
        for path in root.rglob("*"):
            relative = path.relative_to(root)
            try:
                self.policy.relative(relative)
            except CodingPolicyError:
                continue
            if path.is_file() and relative.suffix.casefold() in self.policy.extensions:
                values[str(relative).replace("\\", "/")] = self._sha256(path)
        return values

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(128 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()


def _paths_overlap(first: Path, second: Path) -> bool:
    """True when either resolved directory contains the other."""
    try:
        first.relative_to(second)
        return True
    except ValueError:
        try:
            second.relative_to(first)
            return True
        except ValueError:
            return False
