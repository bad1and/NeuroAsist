"""Filter avatar inputs in an isolated bare mirror and record an auditable map.

This command never pushes or changes the normal developer checkout. Keep its
backup and reports private: they refer to the original, unfiltered history.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

try:
    from .avatar_assets import private_source
except ImportError:
    from avatar_assets import private_source


def run(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def scan_objects(root: Path) -> list[dict]:
    objects = run(root, "rev-list", "--objects", "--all").decode("utf-8").splitlines()
    findings = []
    with subprocess.Popen(["git", "cat-file", "--batch"], cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE) as process:
        assert process.stdin is not None and process.stdout is not None
        for line in objects:
            oid, _, name = line.partition(" ")
            process.stdin.write(oid.encode() + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().decode().split()
            if len(header) != 3:
                raise ValueError("Cannot read Git object: " + oid)
            size = int(header[2])
            data = process.stdout.read(size)
            if len(data) != size or process.stdout.read(1) != b"\n":
                raise ValueError("Truncated Git object: " + oid)
            if header[1] != "blob":
                continue
            reason = "private path" if private_source(name) else "GLB/VRM signature" if data.startswith(b"glTF") else None
            if not reason and data.startswith(b"PK\x03\x04"):
                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as archive:
                        if any(private_source(item.filename) or Path(item.filename).suffix.lower() == ".fbx" for item in archive.infolist()):
                            reason = "archive containing avatar source assets"
                except zipfile.BadZipFile:
                    pass
            if reason:
                findings.append({"blob": oid, "path": name, "bytes": size, "reason": reason})
        process.stdin.close()
        if process.wait() != 0:
            raise ValueError("git cat-file failed")
    return findings


def prepare(mirror: Path, output: Path, filter_repo: Path) -> dict:
    mirror, output = mirror.resolve(), output.resolve()
    if run(mirror, "rev-parse", "--is-bare-repository").strip() != b"true":
        raise ValueError("History filtering requires an isolated bare mirror")
    if not mirror.name.endswith(".git") or output.exists() or output.is_relative_to(mirror):
        raise ValueError("Use a new report directory outside the isolated *.git mirror")
    if not filter_repo.is_file():
        raise ValueError("Supply the pinned git-filter-repo 2.47.0 script")
    output.mkdir(parents=True)
    before = run(mirror, "show-ref").decode().splitlines()
    (output / "refs-before.txt").write_text("\n".join(before) + "\n", encoding="utf-8")
    run(mirror, "bundle", "create", str(output / "original-history.bundle"), "--all")
    run(mirror, "bundle", "verify", str(output / "original-history.bundle"))
    findings = scan_objects(mirror)
    blocked = output / "private-blobs.txt"
    blocked.write_text("\n".join(sorted({item["blob"] for item in findings})) + "\n", encoding="ascii")
    # Renamed copies are removed by object ID as well as by their known paths.
    # Do not use *.vrm/*.gltf path globs: git-filter-repo also matches
    # directory names such as Packages/com.vrmc.vrm and removes their code.
    # The blob scan already identifies every model independent of its name.
    args = [sys.executable, str(filter_repo.resolve()), "--strip-blobs-with-ids", str(blocked), "--invert-paths"]
    for path in ("apps/avatar-unity/Assets/NeuroAsistAvatar/Animations/", "apps/avatar-unity/Assets/NeuroAsistAvatar/Animations.meta",
                 "apps/avatar-unity/Assets/NeuroAsistAvatar/Motion/Generated/", "apps/avatar-unity/Assets/NeuroAsistAvatar/Motion/Generated.meta",
                 "apps/web/public/avatar/animations/"):
        args += ["--path", path]
    subprocess.run(args, cwd=mirror, check=True)
    remaining = scan_objects(mirror)
    if remaining:
        raise ValueError("Restricted blobs remain after filtering")
    after = run(mirror, "show-ref").decode().splitlines()
    (output / "refs-after.txt").write_text("\n".join(after) + "\n", encoding="utf-8")
    old = {line.split()[1]: line.split()[0] for line in before}
    new = {line.split()[1]: line.split()[0] for line in after}
    if old.keys() != new.keys():
        raise ValueError("Filtering changed the set of refs; review before publication")
    for name in ("commit-map", "ref-map", "changed-refs"):
        source = mirror / "filter-repo" / name
        if source.is_file():
            shutil.copyfile(source, output / name)
    report = {"schema_version": 1, "mirror": str(mirror), "remote_changed": False,
              "removed_blobs": findings, "remaining_findings": [],
              "refs": [{"ref": ref, "old": sha, "new": new[ref], "changed": sha != new[ref]} for ref, sha in sorted(old.items())],
              "warning": "GitHub pull refs, forks, cached objects and existing clones are separate from writable branch refs."}
    (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--filter-repo", type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args.mirror, args.output, args.filter_repo)
    print(f"Prepared {len(report['refs'])} refs; removed {len(report['removed_blobs'])} private blobs; no remote changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
