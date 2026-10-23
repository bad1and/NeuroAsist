"""Validate Iris release metadata and maintained Markdown without dependencies."""

from __future__ import annotations

import ast
import html
import json
import re
import tomllib
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
LINK = re.compile(r"!?\[[^\]]*\]\((?P<target><[^>]+>|[^\s)]+)")
IMAGE = re.compile(r"!\[[^\]]*\]\((?P<target><[^>]+>|[^\s)]+)")

ROOT_MARKDOWN = (
    "README.md",
    "README.en.md",
    "README.ru.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "PRIVACY.md",
    "SECURITY.md",
    "THIRD_PARTY_ASSETS.md",
    "design.md",
    "AGENTS.md",
    "GEMINI.md",
    "assets/README.md",
    "requirements/README.md",
    "apps/desktop/README.md",
    "apps/avatar-unity/README.md",
    "apps/web/public/brand/README.md",
    "apps/web/src/startup-snake/README.md",
    "apps/web/src/design-pack/reference.md",
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
    for readme in ("README.md", "README.en.md"):
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
        if node.target.id in {"deepseek_api_key", "coding_api_key", "brave_api_key", "tavily_api_key", "serper_api_key"}:
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
    leaked_secret_settings = {"DEEPSEEK_API_KEY", "CODING_API_KEY", "BRAVE_API_KEY", "TAVILY_API_KEY", "SERPER_API_KEY"} & documented
    if leaked_secret_settings:
        errors.append(
            ".env.example must not advertise API secrets: "
            + ", ".join(sorted(leaked_secret_settings))
        )


def maintained_markdown() -> list[Path]:
    files = {ROOT / item for item in ROOT_MARKDOWN}
    # rules.md is a local, gitignored agent guide. Clean public checkouts and
    # the private Unity builder must not require an unpublished local file.
    if (ROOT / "rules.md").is_file():
        files.add(ROOT / "rules.md")
    files.update((ROOT / "Docs").rglob("*.md"))
    return sorted(files)


def prose_lines(text: str) -> list[str]:
    """Blank fenced examples without changing line numbers."""
    lines: list[str] = []
    fence: tuple[str, int] | None = None
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            run, tail = marker.groups()
            if fence is None:
                fence = (run[0], len(run))
            elif run[0] == fence[0] and len(run) >= fence[1] and not tail.strip():
                fence = None
            lines.append("")
        else:
            lines.append(line if fence is None else "")
    return lines


def markdown_anchors(text: str) -> set[str]:
    """GitHub-style heading slugs, including duplicate and Cyrillic headings."""
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for line in prose_lines(text):
        match = re.match(r"^ {0,3}#{1,6}\s+(.+?)(?:\s+#+)?\s*$", line)
        if not match:
            continue
        label = re.sub(r"!?\[([^]]*)\]\([^)]*\)", r"\1", match.group(1))
        label = html.unescape(re.sub(r"<[^>]*>", "", label)).lower()
        base = "".join(
            ch for ch in label
            if ch in "_-" or ch.isspace() or unicodedata.category(ch)[0] in "LN"
        ).replace(" ", "-")
        number = counts.get(base, 0)
        slug = base if number == 0 else f"{base}-{number}"
        while slug in anchors:
            number += 1
            slug = f"{base}-{number}"
        counts[base] = number + 1
        anchors.add(slug)
    anchors.update(re.findall(r'<(?:a|h[1-6])\b[^>]*\b(?:id|name)=[\"\']([^\"\']+)', text, re.I))
    return anchors


class _HTMLTargets(HTMLParser):
    def __init__(self, *, images_only: bool = False) -> None:
        super().__init__()
        self.targets: list[tuple[int, str]] = []
        self.images_only = images_only

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if value is None:
                continue
            if (tag in {"img", "source"} and key == "src") or (
                tag == "a" and key == "href" and not self.images_only
            ):
                self.targets.append((self.getpos()[0], value))
            elif tag in {"img", "source"} and key == "srcset":
                for candidate in value.split(","):
                    if candidate.strip():
                        self.targets.append((self.getpos()[0], candidate.strip().split()[0]))


def document_targets(text: str) -> list[tuple[int, str]]:
    lines = prose_lines(text)
    targets: list[tuple[int, str]] = []
    for line_number, line in enumerate(lines, 1):
        # Inline examples are not rendered links.
        prose = re.sub(r"(`+).*?\1", "", line)
        for match in LINK.finditer(prose):
            targets.append((line_number, match.group("target").strip("<>")))
        definition = re.match(r"^ {0,3}\[[^]]+\]:\s*(<[^>]+>|\S+)", prose)
        if definition:
            targets.append((line_number, definition.group(1).strip("<>")))
    parser = _HTMLTargets()
    parser.feed("\n".join(lines))
    return targets + parser.targets


def check_links(errors: list[str]) -> None:
    for path in maintained_markdown():
        if not path.exists():
            errors.append(f"missing maintained document: {path.relative_to(ROOT)}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, raw in document_targets(text):
            if not raw:
                continue
            parsed = urlsplit(raw)
            if parsed.scheme in {"http", "https", "mailto", "data"} or parsed.netloc:
                continue
            if parsed.scheme:
                errors.append(f"{path.relative_to(ROOT)}:{line_number}: unsupported local link {raw!r}")
                continue
            target = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path.resolve()
            try:
                target.relative_to(ROOT.resolve())
            except ValueError:
                errors.append(f"{path.relative_to(ROOT)}:{line_number}: link escapes repository: {raw!r}")
                continue
            if not target.exists():
                errors.append(f"{path.relative_to(ROOT)}:{line_number}: missing local target {raw!r}")
                continue
            if parsed.fragment and target.suffix.lower() == ".md":
                fragment = unquote(parsed.fragment)
                anchors = markdown_anchors(target.read_text(encoding="utf-8"))
                if fragment not in anchors:
                    errors.append(f"{path.relative_to(ROOT)}:{line_number}: missing heading anchor {raw!r}")


def check_readme_navigation(errors: list[str]) -> None:
    """Check language transitions while editions can be revised independently."""
    for name, destination in (
        ("README.md", "README.en.md"),
        ("README.en.md", "README.md"),
        ("README.ru.md", "README.md"),
    ):
        path = ROOT / name
        if not path.exists():
            continue  # check_links reports missing maintained documents.
        targets = document_targets(path.read_text(encoding="utf-8"))
        if not any(
            not urlsplit(raw).scheme
            and not urlsplit(raw).netloc
            and (path.parent / unquote(urlsplit(raw).path)).resolve() == (ROOT / destination).resolve()
            for _, raw in targets
        ):
            errors.append(f"{name}: missing language link to {destination}")


def check_readme_images(errors: list[str]) -> None:
    """Keep local illustrations in sync, without requiring identical text."""
    editions: dict[str, set[Path]] = {}
    for name in ("README.md", "README.en.md"):
        path = ROOT / name
        if not path.exists():
            return  # check_links reports missing maintained documents.
        lines = prose_lines(path.read_text(encoding="utf-8"))
        prose = "\n".join(re.sub(r"(`+).*?\1", "", line) for line in lines)
        parser = _HTMLTargets(images_only=True)
        parser.feed(prose)
        targets = [raw for _, raw in parser.targets]
        targets.extend(
            match.group("target").strip("<>")
            for match in IMAGE.finditer(prose)
        )
        editions[name] = {
            (path.parent / unquote(urlsplit(raw).path)).resolve()
            for raw in targets
            if not urlsplit(raw).scheme and not urlsplit(raw).netloc
        }
    for name, images in editions.items():
        other = "README.en.md" if name == "README.md" else "README.md"
        source_lang, target_lang = (".ru.", ".en.") if name == "README.en.md" else (".en.", ".ru.")
        # Composed illustrations may contain translated text. Gallery photos
        # and all other shared assets still require the identical file.
        expected = {
            image.with_name(image.name.replace(source_lang, target_lang))
            for image in editions[other]
        }
        for missing in sorted(expected - images):
            if missing.is_relative_to(ROOT.resolve()):
                errors.append(f"{name}: missing shared image {missing.relative_to(ROOT.resolve()).as_posix()}")


def _requirement_entries(relative_path: str) -> list[str]:
    return [
        line.strip()
        for line in (ROOT / relative_path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _requirement_name(entry: str) -> str | None:
    if entry.startswith("-"):
        return None
    match = re.match(r"^([A-Za-z0-9_.-]+)(?:\s*@|\s*[<>=!~])", entry)
    return match.group(1).lower().replace("_", "-") if match else None


def check_dependency_profiles(errors: list[str]) -> None:
    root_entries = _requirement_entries("requirements.txt")
    expected_root = ["-r requirements/runtime.txt", "-r requirements/dev.txt"]
    if root_entries != expected_root:
        errors.append(
            "requirements.txt must include only the runtime and dev dependency profiles"
        )

    runtime_entries = _requirement_entries("requirements/runtime.txt")
    runtime_names = {
        name for entry in runtime_entries if (name := _requirement_name(entry)) is not None
    }
    required_runtime = {
        "av",
        "chromadb",
        "ctranslate2",
        "fastapi",
        "faster-whisper",
        "gigaam",
        "huggingface-hub",
        "num2words",
        "numpy",
        "onnx",
        "onnxruntime",
        "openai",
        "pydantic",
        "pydantic-settings",
        "python-dotenv",
        "python-multipart",
        "sentencepiece",
        "sentence-transformers",
        "silero-vad",
        "soundfile",
        "torch",
        "torchaudio",
        "transformers",
        "uvicorn",
        "websockets",
    }
    missing = sorted(required_runtime - runtime_names)
    if missing:
        errors.append("requirements/runtime.txt is missing: " + ", ".join(missing))

    retired = {
        "edge-tts",
        "py7zr",
        "silero",
        "silero-stress",
        "supertonic",
        "torchvision",
    }
    for profile in (
        "requirements/runtime.txt",
        "requirements/dev.txt",
        "requirements/constraints.txt",
        "requirements/torch-cpu.txt",
        "requirements/torch-cu128.txt",
    ):
        names = {
            name
            for entry in _requirement_entries(profile)
            if (name := _requirement_name(entry)) is not None
        }
        stale = sorted(names & retired)
        if stale:
            errors.append(f"{profile} contains retired direct dependencies: {', '.join(stale)}")

    build_entries = _requirement_entries("requirements/build.txt")
    if "-r runtime.txt" not in build_entries or not any(
        _requirement_name(entry) == "pyinstaller" for entry in build_entries
    ):
        errors.append("requirements/build.txt must include runtime.txt and PyInstaller")

    for profile, index in (
        ("requirements/torch-cpu.txt", "https://download.pytorch.org/whl/cpu"),
        ("requirements/torch-cu128.txt", "https://download.pytorch.org/whl/cu128"),
    ):
        text = (ROOT / profile).read_text(encoding="utf-8")
        if index not in text or "torch==2.11.0" not in text or "torchaudio==2.11.0" not in text:
            errors.append(f"{profile} must pin the expected PyTorch channel and packages")

    release_script = (ROOT / "scripts/build-desktop-release.ps1").read_text(encoding="utf-8")
    for marker in (
        "requirements\\build.txt",
        "requirements\\torch-cpu.txt",
        "build\\release-venv",
    ):
        if marker not in release_script:
            errors.append(f"release build must use isolated dependency marker {marker!r}")
    if 'Join-Path $root "requirements.txt"' in release_script:
        errors.append("release build must not install the developer requirements profile")


def main() -> int:
    errors: list[str] = []
    version = check_versions(errors)
    check_environment_reference(errors)
    check_links(errors)
    check_readme_navigation(errors)
    check_readme_images(errors)
    check_dependency_profiles(errors)
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
