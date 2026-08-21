"""Validate Iris release metadata and maintained Markdown without dependencies."""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
LINK = re.compile(r"!?\[[^\]]*\]\((?P<target><[^>]+>|[^\s)]+)")

ROOT_MARKDOWN = (
    "README.md",
    "README.ru.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "PRIVACY.md",
    "SECURITY.md",
    "THIRD_PARTY_ASSETS.md",
    "design.md",
    "apps/desktop/README.md",
    "apps/avatar-unity/README.md",
    "output/tts-model-comparison/README.md",
    "tests/baya_approved_handoff/README.md",
    "tests/chatterbox_v3_experiment/README.md",
)


def _json(path: str) -> dict[str, object]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _expect(errors: list[str], label: str, actual: object, expected: object) -> None:
    if actual != expected:
        errors.append(f"{label}: expected {expected!r}, found {actual!r}")


def _cargo_package_version(lock_text: str, name: str) -> str | None:
    match = re.search(
        rf'\[\[package\]\]\s+name = "{re.escape(name)}"\s+version = "([^"]+)"',
        lock_text,
    )
    return match.group(1) if match else None


def check_versions(errors: list[str]) -> str:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not SEMVER.fullmatch(version):
        errors.append(f"VERSION: invalid SemVer {version!r}")

    root_package = _json("package.json")
    root_lock = _json("package-lock.json")
    web_package = _json("apps/web/package.json")
    web_lock = _json("apps/web/package-lock.json")
    desktop_package = _json("apps/desktop/package.json")
    desktop_lock = _json("apps/desktop/package-lock.json")
    tauri = _json("apps/desktop/src-tauri/tauri.conf.json")

    mirrors = {
        "package.json": root_package.get("version"),
        "package-lock.json": root_lock.get("version"),
        "package-lock root package": root_lock.get("packages", {}).get("", {}).get("version"),
        "apps/web/package.json": web_package.get("version"),
        "apps/web/package-lock.json": web_lock.get("version"),
        "apps/web lock root package": web_lock.get("packages", {}).get("", {}).get("version"),
        "apps/web lock local root dependency": web_lock.get("packages", {}).get("../..", {}).get("version"),
        "apps/desktop/package.json": desktop_package.get("version"),
        "apps/desktop/package-lock.json": desktop_lock.get("version"),
        "apps/desktop lock root package": desktop_lock.get("packages", {}).get("", {}).get("version"),
        "Tauri bundle": tauri.get("version"),
    }
    for label, actual in mirrors.items():
        _expect(errors, label, actual, version)
    for label, package in (
        ("root package", root_package),
        ("web package", web_package),
        ("desktop package", desktop_package),
    ):
        _expect(errors, f"{label} Node engine", package.get("engines", {}).get("node"), "24.x")
        _expect(errors, f"{label} npm engine", package.get("engines", {}).get("npm"), "11.x")

    cargo = tomllib.loads((ROOT / "apps/desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8"))
    _expect(errors, "Cargo.toml package", cargo["package"]["version"], version)
    cargo_lock = (ROOT / "apps/desktop/src-tauri/Cargo.lock").read_text(encoding="utf-8")
    _expect(
        errors,
        "Cargo.lock neuroasist-desktop package",
        _cargo_package_version(cargo_lock, "neuroasist-desktop"),
        version,
    )

    unity = (ROOT / "apps/avatar-unity/ProjectSettings/ProjectSettings.asset").read_text(encoding="utf-8")
    for label, pattern, expected in (
        ("Unity bundleVersion", r"(?m)^\s*bundleVersion:\s*(\S+)\s*$", version),
        ("Unity companyName", r"(?m)^\s*companyName:\s*(.+?)\s*$", "NeuroAsist"),
        ("Unity productName", r"(?m)^\s*productName:\s*(.+?)\s*$", "Iris Avatar"),
        (
            "Unity standalone identifier",
            r"(?m)^\s*Standalone:\s*(com\.[A-Za-z0-9_.-]+)\s*$",
            "com.neuroasist.avatar",
        ),
    ):
        match = re.search(pattern, unity)
        _expect(errors, label, match.group(1) if match else None, expected)

    config = (ROOT / "apps/backend/app/core/config.py").read_text(encoding="utf-8")
    main = (ROOT / "apps/backend/main.py").read_text(encoding="utf-8")
    if 'APP_VERSION = (ROOT_DIR / "VERSION").read_text' not in config:
        errors.append("Backend APP_VERSION must read the root VERSION file")
    if "FastAPI(title=settings.app_name, version=APP_VERSION)" not in main:
        errors.append("FastAPI must expose APP_VERSION")

    _expect(errors, ".python-version", (ROOT / ".python-version").read_text().strip(), "3.12.1")
    _expect(errors, ".nvmrc", (ROOT / ".nvmrc").read_text().strip(), "24.18.0")
    rust_toolchain = tomllib.loads((ROOT / "rust-toolchain.toml").read_text(encoding="utf-8"))
    _expect(errors, "Rust toolchain channel", rust_toolchain["toolchain"]["channel"], "stable")
    unity_editor = (ROOT / "apps/avatar-unity/ProjectSettings/ProjectVersion.txt").read_text(encoding="utf-8")
    if "m_EditorVersion: 2022.3.62f3" not in unity_editor:
        errors.append("Unity editor version must remain pinned to 2022.3.62f3")

    badge = f"version-{version}"
    for readme in ("README.md", "README.ru.md"):
        if badge not in (ROOT / readme).read_text(encoding="utf-8"):
            errors.append(f"{readme}: version badge must contain {badge}")
    return version


def _settings_environment_keys() -> set[str]:
    path = ROOT / "apps/backend/app/core/config.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    settings = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Settings"
    )
    keys: set[str] = set()
    for node in settings.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        key = node.target.id.upper()
        value = node.value
        if isinstance(value, ast.Call):
            for keyword in value.keywords:
                if keyword.arg == "validation_alias" and isinstance(keyword.value, ast.Constant):
                    key = str(keyword.value.value)
        keys.add(key)
    return keys


def check_environment_reference(errors: list[str]) -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    documented = set(re.findall(r"(?m)^#?\s*([A-Z][A-Z0-9_]*)\s*=", example))
    missing = sorted(_settings_environment_keys() - documented)
    if missing:
        errors.append(".env.example is missing Settings keys: " + ", ".join(missing))


def maintained_markdown() -> list[Path]:
    files = {ROOT / item for item in ROOT_MARKDOWN}
    files.update((ROOT / "Docs").rglob("*.md"))
    files.update((ROOT / "tests/chatterbox_v3_experiment/output").rglob("*.md"))
    return sorted(files)


def check_links(errors: list[str]) -> None:
    for path in maintained_markdown():
        if not path.exists():
            errors.append(f"missing maintained document: {path.relative_to(ROOT)}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), 1):
            for match in LINK.finditer(line):
                raw = match.group("target").strip("<>")
                if not raw or raw.startswith("#"):
                    continue
                parsed = urlsplit(raw)
                if parsed.scheme in {"http", "https", "mailto", "data"}:
                    continue
                if parsed.scheme:
                    errors.append(
                        f"{path.relative_to(ROOT)}:{line_number}: unsupported local link {raw!r}"
                    )
                    continue
                target_text = unquote(parsed.path).replace("/", str(Path("/")).replace("/", "\\") if sys.platform == "win32" else "/")
                target = (path.parent / target_text).resolve()
                try:
                    target.relative_to(ROOT.resolve())
                except ValueError:
                    errors.append(
                        f"{path.relative_to(ROOT)}:{line_number}: link escapes repository: {raw!r}"
                    )
                    continue
                if not target.exists():
                    errors.append(
                        f"{path.relative_to(ROOT)}:{line_number}: missing local target {raw!r}"
                    )


def check_readme_parity(errors: list[str]) -> None:
    structures: list[list[int]] = []
    for name in ("README.md", "README.ru.md"):
        headings = [len(match.group(1)) for match in re.finditer(r"(?m)^(#{1,6})\s+", (ROOT / name).read_text(encoding="utf-8"))]
        structures.append(headings)
    if structures[0] != structures[1]:
        errors.append("README.md and README.ru.md heading structures differ")


def main() -> int:
    errors: list[str] = []
    version = check_versions(errors)
    check_environment_reference(errors)
    check_links(errors)
    check_readme_parity(errors)
    if errors:
        print("Documentation check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        f"Documentation check passed: Iris {version}; "
        f"{len(maintained_markdown())} Markdown files validated."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
