"""Record the linked FFmpeg profile and reject unsuitable public-release inputs.

This verifies build-profile facts, not complete redistribution approval.
It runs during packaging, never during application startup.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import shlex

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "third-party/ffmpeg/profile.json"


def profile_issues(version: str, libraries: dict, profile: dict) -> list[str]:
    issues = []
    if version != profile["ffmpeg_version"]:
        issues.append(f"FFmpeg {version} differs from the reviewed source profile {profile['ffmpeg_version']}")
    if not libraries:
        issues.append("Linked FFmpeg metadata is missing")
    required = set(profile.get("configure_flags", ["--enable-shared", "--disable-gpl", "--disable-nonfree", "--disable-autodetect"]))
    forbidden = {"--enable-gpl", "--enable-nonfree", "--enable-libx264", "--enable-libx265"}
    for name, library in libraries.items():
        flags = set(shlex.split(library.get("configuration", "")))
        if not str(library.get("license", "")).startswith("LGPL"):
            issues.append(f"{name}: expected an LGPL library declaration")
        if found := flags & forbidden:
            issues.append(f"{name}: review/rebuild required for {', '.join(sorted(found))}")
        if missing := required - flags:
            issues.append(f"{name}: missing explicit profile flags {', '.join(sorted(missing))}")
    return issues


def collect() -> dict:
    import av
    import av._core

    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    dlls = []
    distribution = metadata.distribution("av")
    for file in distribution.files or []:
        if str(file).lower().endswith(".dll"):
            path = Path(distribution.locate_file(file))
            if path.is_file():
                dlls.append({"path": str(file).replace("\\", "/"), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    issues = profile_issues(av._core.ffmpeg_version_info, av._core.library_meta, profile)
    if not dlls:
        issues.append("No bundled Windows FFmpeg DLLs found in the PyAV distribution")
    return {
        "created_at": datetime.now(timezone.utc).isoformat(), "pyav_version": av.__version__,
        "ffmpeg_version": av._core.ffmpeg_version_info, "libraries": av._core.library_meta, "dlls": dlls,
        "selected_profile": profile, "profile_matches": not issues, "issues": issues,
        "distribution_approved": False,
        "remaining": "Exact corresponding source/build materials, notices and final artifact verification are separate release conditions.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--strict", action="store_true", help="Fail when the linked wheel does not match the selected profile")
    args = parser.parse_args()
    report = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"FFmpeg {report['ffmpeg_version']}: {len(report['dlls'])} DLLs; profile matches={report['profile_matches']}")
    if args.strict and report["issues"]:
        raise SystemExit("FFmpeg release profile requires preparation. See Docs/tts-ffmpeg-delivery.md and the generated report.")
