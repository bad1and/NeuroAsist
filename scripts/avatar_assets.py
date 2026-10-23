"""Separate private avatar inputs from public sources and compiled Player delivery.

No Git mutations or network calls. Imports and extraction require a new target;
existing projects are never overwritten by these commands.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_TREES = (
    "apps/avatar-unity/Assets/NeuroAsistAvatar/Animations",
    "apps/avatar-unity/Assets/NeuroAsistAvatar/Motion/Generated",
    "apps/web/public/avatar/animations",
)
MODEL_SUFFIXES = {".vrm", ".glb", ".gltf"}
RAW_PLAYER_SUFFIXES = MODEL_SUFFIXES | {
    ".fbx", ".blend", ".psd", ".unitypackage", ".unity", ".prefab", ".meta", ".anim", ".mat", ".asset",
}
PLAYER_ROOTS = {"NeuroAsistAvatar.exe", "UnityPlayer.dll", "UnityCrashHandler64.exe", "NeuroAsistAvatar_Data", "MonoBleedingEdge"}
KNOWN_VRM_SHA256 = {"c80c488e4836d41f1b54b601fcebd943b9a5a6107428b9027e10f006cb1f5f78"}


def is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def tracked(root: Path) -> list[str]:
    return [p for p in git(root, "ls-files", "-z").decode("utf-8").split("\0") if p]


def private_source(name: str) -> bool:
    name = name.replace("\\", "/")
    lower = name.lower()
    # Package names such as com.vrmc.vrm are directories, not model files.
    if PurePosixPath(lower).suffix in MODEL_SUFFIXES:
        return True
    return any(lower == p.lower() + ".meta" or lower.startswith(p.lower() + "/") for p in PRIVATE_TREES)


def safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if (not name or "\\" in name or path.is_absolute() or ":" in name
            or any(p in {"", ".", ".."} for p in name.split("/"))):
        raise ValueError(f"Unsafe path: {name!r}")
    # Windows aliases and device names could escape a checked file inventory.
    for part in path.parts:
        if part.endswith((".", " ")) or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part):
            raise ValueError(f"Unsafe Windows path: {name!r}")
    return path.as_posix()


def public_findings(root: Path) -> list[str]:
    findings = []
    for name in tracked(root):
        path = root / name
        if private_source(name):
            findings.append(name)
        elif path.is_file():
            with path.open("rb") as stream:
                header = stream.read(4)
            if header == b"glTF" or (path.stat().st_size == 24481376 and sha256(path) in KNOWN_VRM_SHA256):
                findings.append(name)
    return findings


def source_record(root: Path) -> dict:
    names = [p for p in tracked(root) if not private_source(p) and
             (p.startswith("apps/avatar-unity/") or p.startswith("apps/protocol/") or p in {"VERSION", "scripts/avatar_assets.py"})]
    def source_hash(path: Path) -> str:
        data = path.read_bytes()
        # Git normalizes ordinary text. Different Windows/Linux autocrlf
        # settings must not invalidate an otherwise identical reviewed source.
        if b"\0" not in data:
            data = data.replace(b"\r\n", b"\n")
        return hashlib.sha256(data).hexdigest()
    files = {name: source_hash(root / name) for name in sorted(names) if (root / name).is_file()}
    return {"public_commit": git(root, "rev-parse", "HEAD").decode().strip(),
            "renderer_source_sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
            "source_files": files}


def export_private(root: Path, destination: Path) -> dict:
    if destination.exists() or destination.is_relative_to(root.resolve()):
        raise ValueError("Private export requires a new directory outside the public repository")
    names = [p for p in tracked(root) if private_source(p)]
    if "apps/avatar-unity/Assets/IRIS.vrm" not in names:
        raise ValueError("The canonical VRM is not available in this source checkout")
    destination.mkdir(parents=True)
    files = {}
    for name in names:
        source = root / safe_name(name)
        if is_link(source) or not source.is_file():
            raise ValueError(f"Invalid private input: {name}")
        target = destination / "assets" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        files[name] = sha256(source)
        if sha256(target) != files[name]:
            raise ValueError(f"Private backup checksum mismatch: {name}")
    record = {"schema_version": 1, "files": files}
    (destination / "assets-manifest.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def import_private(root: Path, private: Path) -> None:
    manifest = json.loads((private / "assets-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), dict):
        raise ValueError("Unsupported private assets manifest")
    files = manifest["files"]
    if "apps/avatar-unity/Assets/IRIS.vrm" not in files:
        raise ValueError("Private assets do not contain IRIS.vrm")
    # Validate the entire import before copying a single input.
    for name, digest in files.items():
        safe_name(name)
        source, target = private / "assets" / name, root / name
        if not private_source(name) or is_link(source) or not source.is_file() or sha256(source) != digest:
            raise ValueError(f"Invalid private asset: {name}")
        if any(is_link(p) for p in source.parents if p != private.parent):
            raise ValueError(f"Linked private asset directory: {name}")
        if target.exists() or is_link(target) or any(is_link(p) for p in target.parents):
            raise ValueError(f"Refusing to overwrite an existing project asset: {name}")
    for name in files:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(private / "assets" / name, target)


def player_findings(root: Path, *, allow_build_debug: bool = False) -> list[str]:
    if not root.is_dir() or is_link(root):
        raise ValueError(f"Player directory does not exist or is a link: {root}")
    findings = []
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        if allow_build_debug and "donotship" in name.split("/")[0].lower():
            continue
        if is_link(path) or any(part.lower() in {"library", "temp", "obj", ".git"} or "donotship" in part.lower() for part in path.relative_to(root).parts):
            findings.append(name)
        elif path.is_file() and path.name != ".gitkeep":
            if (path.suffix.lower() in RAW_PLAYER_SUFFIXES or name.split("/")[0] not in PLAYER_ROOTS):
                findings.append(name)
                continue
            with path.open("rb") as stream:
                header = stream.read(4)
            if header == b"glTF" or (path.stat().st_size == 24481376 and sha256(path) in KNOWN_VRM_SHA256):
                findings.append(name)
    return sorted(set(findings))


def raw_model_paths(roots: list[Path]) -> list[str]:
    findings = []
    for root in roots:
        if not root.is_dir():
            raise ValueError(f"Resource directory does not exist: {root}")
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            with path.open("rb") as stream:
                header = stream.read(4)
            if path.suffix.lower() in MODEL_SUFFIXES | {".fbx", ".blend", ".psd", ".unitypackage"} or header == b"glTF":
                findings.append(f"{root.name}/{path.relative_to(root).as_posix()}")
    return sorted(findings)


def package_player(player: Path, archive: Path, record: dict, version: str) -> dict:
    # Unity emits a separate Burst diagnostics tree next to the Player. It is
    # a build output, not a deliverable; omit it rather than shipping or deleting
    # it. Checks on the extracted/staged Player stay strict.
    findings = player_findings(player, allow_build_debug=True)
    if findings:
        raise ValueError("Source assets or unexpected files in Player: " + ", ".join(findings))
    for name in ("NeuroAsistAvatar.exe", "UnityPlayer.dll"):
        if not (player / name).is_file() or (player / name).stat().st_size == 0:
            raise ValueError(f"Missing Player resource: {name}")
    if not (player / "NeuroAsistAvatar_Data").is_dir():
        raise ValueError("Missing NeuroAsistAvatar_Data")
    files = {p.relative_to(player).as_posix(): {"bytes": p.stat().st_size, "sha256": sha256(p)}
             for p in sorted(player.rglob("*")) if p.is_file() and p.name != ".gitkeep"
             and "donotship" not in p.relative_to(player).parts[0].lower()}
    manifest = {"schema_version": 1, "component": "iris-avatar-windows", "version": version,
                "public_commit": record["public_commit"], "renderer_source_sha256": record["renderer_source_sha256"],
                "files": files}
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        for name in files:
            bundle.write(player / name, "player/" + name)
    return manifest


def install_player(archive: Path, expected: str, destination: Path, root: Path) -> dict:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected) or sha256(archive) != expected.lower():
        raise ValueError("Avatar archive SHA-256 mismatch")
    if destination.exists() or is_link(destination):
        raise ValueError("Player destination must not exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        names = []
        for entry in bundle.infolist():
            safe_name(entry.filename)
            if entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("Directory/link entries are not allowed in the Player package")
            names.append(entry.filename)
        if len({n.casefold() for n in names}) != len(names):
            raise ValueError("Duplicate or case-colliding archive paths")
        if "manifest.json" not in names or bundle.getinfo("manifest.json").file_size > 1024 * 1024:
            raise ValueError("Missing or oversized Player manifest")
        manifest = json.loads(bundle.read("manifest.json"))
        if manifest.get("schema_version") != 1 or manifest.get("component") != "iris-avatar-windows":
            raise ValueError("Unsupported Player manifest")
        if manifest.get("version") != (root / "VERSION").read_text().strip():
            raise ValueError("Player version does not match Iris")
        if manifest.get("renderer_source_sha256") != source_record(root)["renderer_source_sha256"]:
            raise ValueError("Player was built from different renderer sources")
        files = manifest.get("files")
        if not isinstance(files, dict) or set(names) != {"manifest.json", *("player/" + safe_name(n) for n in files)}:
            raise ValueError("Player inventory does not match archive contents")
        # Extract only after the archive has been authenticated by its pinned hash.
        # A temporary sibling is removed on failure; the destination appears only
        # after every file hash and source-file check passes.
        with tempfile.TemporaryDirectory(prefix="iris-avatar-", dir=destination.parent) as temp:
            staging = Path(temp) / "player"
            staging.mkdir()
            for name, item in files.items():
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                entry = bundle.getinfo("player/" + name)
                if entry.file_size != item["bytes"]:
                    raise ValueError(f"Player file size mismatch: {name}")
                with bundle.open(entry) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                if sha256(target) != item["sha256"]:
                    raise ValueError(f"Player file checksum mismatch: {name}")
            findings = player_findings(staging)
            if findings:
                raise ValueError("Source assets in Player package: " + ", ".join(findings))
            for name in ("NeuroAsistAvatar.exe", "UnityPlayer.dll", "NeuroAsistAvatar_Data"):
                if not (staging / name).exists():
                    raise ValueError(f"Missing Player resource: {name}")
            staging.rename(destination)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check-public", "export-private", "import-private", "record-source", "package-player", "install-player", "check-player"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--private", type=Path)
    parser.add_argument("--player", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--source-record", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == "check-public":
            findings = public_findings(root)
            if findings:
                raise ValueError("Private avatar inputs are tracked: " + ", ".join(findings))
        elif args.command == "export-private":
            if not args.output: parser.error("--output is required")
            export_private(root, args.output.resolve())
        elif args.command == "import-private":
            if not args.private: parser.error("--private is required")
            import_private(root, args.private.resolve())
        elif args.command == "record-source":
            if not args.output: parser.error("--output is required")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(source_record(root), indent=2) + "\n", encoding="utf-8")
        elif args.command == "package-player":
            if not all((args.player, args.archive, args.source_record)): parser.error("--player, --archive, --source-record are required")
            package_player(args.player, args.archive, json.loads(args.source_record.read_text(encoding="utf-8")), (root / "VERSION").read_text().strip())
            print("Archive SHA-256:", sha256(args.archive))
        elif args.command == "install-player":
            if not all((args.archive, args.sha256, args.output)): parser.error("--archive, --sha256, --output are required")
            manifest = install_player(args.archive, args.sha256, args.output.resolve(), root)
            if args.receipt:
                receipt = {**manifest, "archive_sha256": args.sha256.lower()}
                args.receipt.parent.mkdir(parents=True, exist_ok=True)
                with args.receipt.open("x", encoding="utf-8") as stream:
                    stream.write(json.dumps(receipt, indent=2) + "\n")
        else:
            if not args.player: parser.error("--player is required")
            findings = player_findings(args.player)
            if findings: raise ValueError("Unexpected Player files: " + ", ".join(findings))
    except (ValueError, OSError, zipfile.BadZipFile, KeyError) as error:
        parser.error(str(error))
    print(args.command + ": passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
