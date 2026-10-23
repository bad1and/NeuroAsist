"""Verify the staged app directory and identify the exact source and binary candidate."""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from check_release_artifact import ROOT, private_paths, retired_dependency_paths, download_only_model_paths, sha256
from avatar_assets import raw_model_paths, player_findings


def source_snapshot() -> dict:
    source_files = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT, text=True, encoding="utf-8").split("\0")
    sources = {name: sha256(ROOT / name) for name in source_files if name and (ROOT / name).is_file()}
    return {"source_tree_sha256": hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(), "source_files": sources}


def manifest(directory: Path, source_record: Path | None = None) -> dict:
    expected = ("Iris.exe", "core/neuroasist-core.exe", "avatar/NeuroAsistAvatar.exe")
    for path in expected:
        if not (directory / path).is_file():
            raise ValueError(f"Missing application resource: {path}")
    avatar_findings = raw_model_paths([directory]) + player_findings(directory / "avatar")
    if avatar_findings:
        raise ValueError("Source avatar assets or unexpected Player files: " + ", ".join(avatar_findings))
    findings = private_paths([directory / "core", directory / "avatar"]) + retired_dependency_paths([directory / "core"])
    if findings:
        raise ValueError("Unexpected runtime data: " + ", ".join(findings))
    model_files = download_only_model_paths([directory])
    if model_files:
        raise ValueError("Download-only model resources are present: " + ", ".join(model_files))
    files = {path.relative_to(directory).as_posix(): {"bytes": path.stat().st_size, "sha256": sha256(path)} for path in sorted(directory.rglob("*")) if path.is_file()}
    source = source_snapshot()
    if source_record and source != json.loads(source_record.read_text(encoding="utf-8")):
        raise ValueError("Sources changed while building. Build a new candidate.")
    return {"schema_version": 1, "product": "Iris", "version": (ROOT / "VERSION").read_text().strip(),
            "created_at_utc": datetime.now(UTC).isoformat(), "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
            **source, "files": files, "installer": False, "distribution_approved": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path)
    parser.add_argument("--record-source", action="store_true")
    parser.add_argument("--source-record", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = source_snapshot() if args.record_source else manifest(args.app, args.source_record)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Build source snapshot recorded." if args.record_source else f"Application verified: {len(result['files'])} files; source_dirty={result['source_dirty']}; installer=False")
