from __future__ import annotations

from pathlib import Path


class CodingPolicyError(ValueError):
    pass


class PathPolicy:
    """Allowlist paths before a snapshot reaches the model or Docker."""

    _blocked_parts = {
        ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
        ".pytest_cache", ".mypy_cache", ".cache", ".idea", ".vscode", "data", "logs",
    }
    _blocked_names = {".env", ".env.local", ".env.production", ".env.development"}
    _blocked_suffixes = {".pem", ".key", ".pfx", ".p12", ".sqlite", ".db", ".sqlite3"}
    _sensitive_name_fragments = {"secret", "credential", "password", "passwd", "api_key", "apikey", "token", "private"}

    def __init__(self, root: Path, *, extensions: frozenset[str], max_file_bytes: int) -> None:
        self.root = root.resolve()
        self.extensions = extensions
        self.max_file_bytes = max_file_bytes

    def relative(self, value: str | Path) -> Path:
        candidate = Path(value)
        if candidate.is_absolute():
            candidate = candidate.resolve()
            try:
                relative = candidate.relative_to(self.root)
            except ValueError as error:
                raise CodingPolicyError("Path is outside the approved project") from error
        else:
            if ".." in candidate.parts:
                raise CodingPolicyError("Parent traversal is not allowed")
            relative = candidate
        if not relative.parts or str(relative) in {".", ""}:
            raise CodingPolicyError("A file path is required")
        if any(part.casefold() in self._blocked_parts for part in relative.parts):
            raise CodingPolicyError("Path is excluded from Coding Agent access")
        name = relative.name.casefold()
        if (
            name in self._blocked_names
            or relative.suffix.casefold() in self._blocked_suffixes
            or any(fragment in name for fragment in self._sensitive_name_fragments)
        ):
            raise CodingPolicyError("Sensitive or generated files are excluded")
        return relative

    def accepts_file(self, path: Path) -> bool:
        try:
            relative = self.relative(path)
        except CodingPolicyError:
            return False
        return path.is_file() and relative.suffix.casefold() in self.extensions
