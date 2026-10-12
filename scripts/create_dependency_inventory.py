"""Collect supplied license metadata and notices; this does not approve redistribution."""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
    lock = json.loads((ROOT / "apps/web/package-lock.json").read_text(encoding="utf-8"))
    npm = []
    for path, package in lock["packages"].items():
        if not path: continue
        name = path.split("node_modules/")[-1]
        notices = []
        source = ROOT / "apps/web" / path
        if source.is_dir():
            for candidate in source.iterdir():
                if candidate.is_file() and candidate.name.lower().startswith(("license", "notice", "copying")):
                    target = destination / "npm" / (name.replace("/", "_") + "-" + package.get("version", "unknown")) / candidate.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(candidate, target)
                    notices.append(target.relative_to(destination).as_posix())
        npm.append({"name": name, "version": package.get("version"), "dev": package.get("dev", False), "declared_license": package.get("license", "Unspecified"), "notices": notices})
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
    result = {"distribution_approved": False, "python": python, "npm": npm, "rust": rust,
              "models": [{"name": m["name"], "revision": m["revision"], "source": "https://huggingface.co/" + m["repository"]} for m in models],
              "owner_review_required": ["IRIS.vrm AI companion redistribution", "Mixamo use and binary distribution", "Proxima Nova desktop embedding", "model weights and bundled RUAccent", "Unity and system binary notices"]}
    (destination / "inventory.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["Iris third-party component inventory", "Distribution approval is pending owner review. See THIRD_PARTY_ASSETS.md.", "Avatar: Kado / 柾木門 (@masakikado).", ""]
    for ecosystem, packages in (("Python", python), ("npm", npm), ("Rust", rust)):
        lines.append(ecosystem)
        lines.extend(f"{p['name']} {p['version']}: {p['declared_license']}" for p in packages)
        lines.append("")
    (destination.parent / "THIRD_PARTY_NOTICES.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = create(args.output)
    print(f"Inventory: {len(result['python'])} Python, {len(result['npm'])} npm, {len(result['rust'])} Rust packages; owner review remains open.")
