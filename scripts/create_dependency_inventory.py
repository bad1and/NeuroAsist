"""Collect supplied license metadata and notices; this does not approve redistribution."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def create(destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    python = []
    for distribution in sorted(metadata.distributions(), key=lambda d: d.metadata.get("Name", "")):
        name = distribution.metadata.get("Name", "unknown")
        declared = distribution.metadata.get("License-Expression") or distribution.metadata.get("License") or "Unspecified"
        notices = []
        for file in distribution.files or ():
            normalized = str(file).lower()
            if ".dist-info/" in normalized and any(part in normalized for part in ("license", "copying", "notice", "copyright")):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    relative_notice = Path(str(file).replace("\\", "/").split(".dist-info/", 1)[1])
                    target = destination / "python" / name / relative_notice
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    notices.append(target.relative_to(destination).as_posix())
        python.append({"name": name, "version": distribution.version, "declared_license": declared, "notices": notices})
    npm = []
    npm_workspaces = []
    for workspace in (".", "apps/web", "apps/desktop"):
        lock = json.loads((ROOT / workspace / "package-lock.json").read_text(encoding="utf-8"))
        npm_workspaces.append({"path": workspace, "package_count": sum(bool(path) for path in lock["packages"])})
        for path, package in lock["packages"].items():
            if not path: continue
            name = path.split("node_modules/")[-1]
            notices = []
            source = ROOT / workspace / path
            if source.is_dir():
                for candidate in source.iterdir():
                    if candidate.is_file() and candidate.name.lower().startswith(("license", "notice", "copying")):
                        target = destination / "npm" / (name.replace("/", "_") + "-" + package.get("version", "unknown")) / candidate.name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(candidate, target)
                        notices.append(target.relative_to(destination).as_posix())
            npm.append({"workspace": workspace, "name": name, "version": package.get("version"), "dev": package.get("dev", False), "declared_license": package.get("license", "Unspecified"), "notices": notices})
    rust_metadata = json.loads(subprocess.check_output(["cargo", "metadata", "--locked", "--format-version", "1", "--manifest-path", str(ROOT / "apps/desktop/src-tauri/Cargo.toml")], cwd=ROOT))
    rust = []
    for package in rust_metadata["packages"]:
        notices = []
        source = Path(package["manifest_path"]).parent
        for candidate in source.iterdir():
            if candidate.is_file() and candidate.name.lower().startswith(("license", "notice", "copying")):
                target = destination / "rust" / (package["name"] + "-" + package["version"]) / candidate.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(candidate, target)
                notices.append(target.relative_to(destination).as_posix())
        rust.append({"name": package["name"], "version": package["version"], "declared_license": package["license"] or "Unspecified", "notices": notices})
    models = json.loads((ROOT / "apps/backend/app/model_manager/catalog.json").read_text(encoding="utf-8"))
    from apps.backend.app.model_manager.service import SILERO_VAD, SMART_TURN_V3_2
    model_records = [{"name": m["name"], "revision": m["revision"], "source": "https://huggingface.co/" + m["repository"]} for m in models]
    model_records.extend({"name": spec.name, "revision": spec.version, "source": spec.url, "sha256": spec.sha256}
                         for spec in (SILERO_VAD, SMART_TURN_V3_2))
    model_notices = []
    for notice in sorted((ROOT / "third-party/model-notices").glob("*.txt")):
        target = destination / "models" / notice.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(notice, target)
        model_notices.append({"path": target.relative_to(destination).as_posix(),
                              "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    font_notices = []
    for notice in sorted((ROOT / "third-party/font-notices").iterdir()):
        if not notice.is_file():
            continue
        target = destination / "fonts" / notice.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(notice, target)
        font_notices.append({"path": target.relative_to(destination).as_posix(),
                             "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    ffmpeg_notice_root = ROOT / "third-party/ffmpeg/notices"
    ffmpeg_notices = []
    for notice in sorted(ffmpeg_notice_root.glob("COPYING.*")):
        target = destination / "ffmpeg" / notice.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(notice, target)
        ffmpeg_notices.append({"path": target.relative_to(destination).as_posix(),
                               "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    # Use the linked wheel's own metadata, not PyAV's BSD license as a proxy
    # for its separately licensed FFmpeg libraries.
    import av._core
    # An inventory describes the build graph. It does not prove which compiled
    # dependencies are linked into a particular binary or grant redistribution.
    assets = json.loads((ROOT / "Docs/distribution-components.json").read_text(encoding="utf-8"))
    source_files = ["requirements/runtime.txt", "requirements/build.txt", "requirements/torch-cpu.txt", "requirements/constraints.txt", "package-lock.json",
                    "apps/web/package-lock.json", "apps/desktop/package-lock.json", "apps/desktop/src-tauri/Cargo.lock",
                    "apps/avatar-unity/Packages/packages-lock.json", "apps/backend/app/model_manager/catalog.json",
                    "Docs/distribution-components.json", "third-party/ffmpeg/profile.json", "third-party/ffmpeg/notices/sources.json",
                    "apps/web/src/fonts/DaysOne-Regular.ttf", "apps/web/src/fonts/Geologica-Variable.ttf",
                    "third-party/font-notices/sources.json"]
    result = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "scope": "Installed Python build environment and all npm/Cargo lock entries; includes development and foreign targets, not an artifact bill of materials",
              "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_files},
              "distribution_approved": False, "python": python, "npm": npm, "npm_workspaces": npm_workspaces, "rust": rust,
              "models": model_records, "model_notices": model_notices, "font_notices": font_notices,
              "ffmpeg_version": av._core.ffmpeg_version_info, "ffmpeg_libraries": av._core.library_meta,
              "ffmpeg_license_texts": ffmpeg_notices,
              "distribution_components": assets["components"],
              "owner_review_required": [item["id"] for item in assets["components"] if item["status"] not in {"license_recorded", "notice_required"}]}
    (destination / "inventory.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["Iris third-party component inventory", "Distribution approval is pending owner review. See THIRD_PARTY_ASSETS.md.", "Avatar: Kado / 柾木門 (@masakikado).", ""]
    for ecosystem, packages in (("Python", python), ("npm", npm), ("Rust", rust)):
        lines.append(ecosystem)
        lines.extend(f"{p['name']} {p['version']}: {p['declared_license']}" for p in packages)
        lines.append("")
    lines.append("Model and asset delivery conditions (not a grant of rights)")
    for item in assets["components"]:
        lines.extend([f"{item['component']}: {item['license']} [{item['status']}]", item["source"], item["required"], ""])
    lines.append("Complete model notices: " + ", ".join("licenses/" + n["path"] for n in model_notices))
    lines.append("Complete font notices: " + ", ".join("licenses/" + n["path"] for n in font_notices))
    lines.extend(["", f"This software uses libraries from the FFmpeg project ({av._core.ffmpeg_version_info}).",
                  "https://ffmpeg.org/ - full license texts: licenses/ffmpeg/COPYING.*",
                  "The build report records linked library configuration and declarations; corresponding source/build materials require release verification."])
    (destination.parent / "THIRD_PARTY_NOTICES.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = create(args.output)
    print(f"Inventory: {len(result['python'])} Python, {len(result['npm'])} npm, {len(result['rust'])} Rust packages; owner review remains open.")
