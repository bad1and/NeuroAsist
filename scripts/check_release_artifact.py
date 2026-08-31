"""Create an attestable manifest for an Iris Windows release candidate.

The NSIS executable is opaque until it is installed.  The Tauri bundle is
therefore checked *before* NSIS packages it: the complete PyInstaller sidecar
and the Avatar resource tree are scanned for private runtime data.  The script
then writes SHA-256 metadata for the installer that is uploaded by CI.

This is deliberately dependency-free so it can run in a fresh CI checkout and
on a clean Windows release machine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_FILE_NAMES = frozenset(
    {
        ".env",
        "llmdebug.db",
        "desktop.sqlite3",
        "timeline.sqlite3",
        "settings.json",
    }
)
PRIVATE_SUFFIXES = frozenset(
    {
        ".db",
        ".sqlite",
        ".sqlite3",
        ".sqlite3-journal",
        ".wav",
        ".pcm",
        ".mp3",
        ".flac",
        ".ogg",
    }
)
PRIVATE_PATH_PARTS = frozenset({"diagnostics", "stt-audio", "private-corpus"})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def private_paths(roots: Iterable[Path]) -> list[str]:
    """Return forbidden runtime files, relative to their scanned resource root."""

    findings: list[str] = []
    for root in roots:
        if not root.is_dir():
            raise ValueError(f"Release resource directory does not exist: {root}")
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = path.relative_to(root)
            lowered_parts = tuple(part.lower() for part in relative.parts)
            name = path.name.lower()
            suffix = "".join(path.suffixes).lower()
            if (
                name in PRIVATE_FILE_NAMES
                or suffix in PRIVATE_SUFFIXES
                or name.endswith((".sqlite-journal", ".sqlite3-journal"))
                or any(part in PRIVATE_PATH_PARTS for part in lowered_parts)
            ):
                findings.append(f"{root.name}/{relative.as_posix()}")
    return findings


def git_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def build_manifest(
    *, artifact: Path, version: str, staging_roots: Iterable[Path], signing_status: str
) -> dict[str, object]:
    if not artifact.is_file():
        raise ValueError(f"Release installer does not exist: {artifact}")
    if artifact.suffix.lower() != ".exe":
        raise ValueError(f"Release installer must be an .exe file: {artifact}")
    if version not in artifact.name:
        raise ValueError(
            f"Installer filename must contain product version {version!r}: {artifact.name}"
        )
    if artifact.stat().st_size == 0:
        raise ValueError(f"Release installer is empty: {artifact}")

    scanned_roots = list(staging_roots)
    forbidden = private_paths(scanned_roots)
    if forbidden:
        formatted = "\n- ".join(forbidden)
        raise ValueError(f"Private runtime data is present in the package staging tree:\n- {formatted}")

    return {
        "schema_version": 1,
        "product": "Iris",
        "version": version,
        "commit": os.getenv("GITHUB_SHA") or git_revision(),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "installer": {
            "filename": artifact.name,
            "bytes": artifact.stat().st_size,
            "sha256": sha256(artifact),
            "signing_status": signing_status,
        },
        "privacy_scan": {
            "method": "pre-nsis-resource-tree",
            "scanned_roots": [str(root) for root in scanned_roots],
            "forbidden_files": [],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True, help="NSIS installer executable")
    parser.add_argument(
        "--staging",
        type=Path,
        action="append",
        required=True,
        help="Resource directory included in the package; may be provided more than once",
    )
    parser.add_argument("--version", required=True, help="Product SemVer from VERSION")
    parser.add_argument("--output", type=Path, required=True, help="Manifest JSON path")
    parser.add_argument(
        "--signing-status",
        choices=("unsigned", "authenticode"),
        default="unsigned",
        help="Recorded status only; Authenticode verification is performed by the build script",
    )
    args = parser.parse_args()

    try:
        manifest = build_manifest(
            artifact=args.artifact.resolve(),
            version=args.version,
            staging_roots=[path.resolve() for path in args.staging],
            signing_status=args.signing_status,
        )
    except ValueError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
