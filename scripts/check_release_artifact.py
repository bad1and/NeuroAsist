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

try:
    from .avatar_assets import raw_model_paths
except ImportError:
    from avatar_assets import raw_model_paths


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
RETIRED_RUNTIME_PACKAGES = frozenset(
    {"edge-tts", "py7zr", "silero", "silero-stress", "supertonic", "torchvision"}
)


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


def retired_dependency_paths(roots: Iterable[Path]) -> list[str]:
    """Return package paths that belong to removed runtime integrations."""

    def is_retired_package_part(part: str) -> bool:
        normalized = part.lower().replace("_", "-")
        if normalized in RETIRED_RUNTIME_PACKAGES:
            return True
        if not normalized.endswith(".dist-info"):
            return False
        distribution = normalized.removesuffix(".dist-info")
        return any(
            distribution.startswith(f"{package}-")
            and distribution.removeprefix(f"{package}-")[:1].isdigit()
            for package in RETIRED_RUNTIME_PACKAGES
        )

    findings: set[str] = set()
    for root in roots:
        if not root.is_dir():
            raise ValueError(f"Release resource directory does not exist: {root}")
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            for index, part in enumerate(relative.parts):
                if is_retired_package_part(part):
                    package_path = Path(*relative.parts[: index + 1]).as_posix()
                    findings.add(f"{root.name}/{package_path}")
                    break
    return sorted(findings)


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


def download_only_model_paths(roots: Iterable[Path]) -> list[str]:
    """Keep TeraTTS snapshots/caches and known weights out of release resources.

    Hash matching also detects renamed weights. Only files with a catalogued
    weight size are hashed; unrelated ONNX libraries and legal notices are valid.
    """
    catalog = json.loads((ROOT / "apps/backend/app/model_manager/catalog.json").read_text(encoding="utf-8"))
    model = next(item for item in catalog if item["id"] == "teratts-v2")
    namespaces = {"teratts-v2", "terattsv2", "models--teraspace--terattsv2"}
    weights: dict[int, set[str]] = {}
    for file in model["files"]:
        if Path(file["path"]).suffix.lower() in {".onnx", ".npy"}:
            weights.setdefault(file["size_bytes"], set()).add(file["sha256"])
    findings: set[str] = set()
    for root in roots:
        if not root.is_dir():
            raise ValueError(f"Release resource directory does not exist: {root}")
        if root.name.lower() in namespaces:
            findings.add(root.name)
            continue
        for path in root.rglob("*"):
            relative = path.relative_to(root)
            namespace_index = next((index for index, part in enumerate(relative.parts) if part.lower() in namespaces), None)
            if namespace_index is not None:
                findings.add(f"{root.name}/{Path(*relative.parts[:namespace_index + 1]).as_posix()}")
            elif path.is_file() and (digests := weights.get(path.stat().st_size)) and sha256(path) in digests:
                findings.add(f"{root.name}/{relative.as_posix()}")
    return sorted(findings)


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
    raw_models = raw_model_paths(scanned_roots)
    if raw_models:
        raise ValueError("Source avatar assets are present in the package staging tree:\n- " + "\n- ".join(raw_models))
    forbidden = private_paths(scanned_roots)
    if forbidden:
        formatted = "\n- ".join(forbidden)
        raise ValueError(f"Private runtime data is present in the package staging tree:\n- {formatted}")
    retired_dependencies = retired_dependency_paths(scanned_roots)
    if retired_dependencies:
        formatted = "\n- ".join(retired_dependencies)
        raise ValueError(f"Retired dependencies are present in the package staging tree:\n- {formatted}")
    model_files = download_only_model_paths(scanned_roots)
    if model_files:
        raise ValueError("Download-only model resources are present in the package staging tree:\n- " + "\n- ".join(model_files))

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
        "dependency_scan": {
            "method": "pre-nsis-resource-tree",
            "retired_packages": sorted(RETIRED_RUNTIME_PACKAGES),
            "forbidden_paths": [],
        },
        "model_delivery_scan": {"method": "pre-nsis-resource-tree", "download_only_models": ["teratts-v2"], "forbidden_paths": []},
        "avatar_source_scan": {"method": "pre-nsis-resource-tree", "forbidden_paths": []},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, help="NSIS installer executable")
    parser.add_argument("--models-only", action="store_true", help="Reject download-only model resources before packaging")
    parser.add_argument(
        "--staging",
        type=Path,
        action="append",
        required=True,
        help="Resource directory included in the package; may be provided more than once",
    )
    parser.add_argument("--version", help="Product SemVer from VERSION")
    parser.add_argument("--output", type=Path, help="Manifest JSON path")
    parser.add_argument(
        "--signing-status",
        choices=("unsigned", "authenticode"),
        default="unsigned",
        help="Recorded status only; Authenticode verification is performed by the build script",
    )
    args = parser.parse_args()

    if args.models_only:
        try:
            raw_models = raw_model_paths([path.resolve() for path in args.staging])
            if raw_models:
                parser.error("Source avatar assets are present: " + ", ".join(raw_models))
            findings = download_only_model_paths([path.resolve() for path in args.staging])
            if findings:
                parser.error("Download-only model resources are present: " + ", ".join(findings))
        except ValueError as error:
            parser.error(str(error))
        print("Download-only model scan passed: no TeraTTS weights or cache in release resources.")
        return 0
    if not all((args.artifact, args.version, args.output)):
        parser.error("--artifact, --version and --output are required unless --models-only is used")

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
