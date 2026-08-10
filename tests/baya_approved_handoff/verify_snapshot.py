"""Verify that the handoff source snapshot matches the current worktree."""

from __future__ import annotations

import hashlib
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SNAPSHOT = HERE / "source"

FILES = (
    ".env.example",
    "apps/backend/app/agents/character/prompts.py",
    "apps/backend/app/api/routes/settings.py",
    "apps/backend/app/core/config.py",
    "apps/backend/app/schemas/character.py",
    "apps/backend/app/voice/delivery.py",
    "apps/backend/app/voice/live.py",
    "apps/backend/app/voice/orchestrator.py",
    "apps/backend/app/voice/providers.py",
    "apps/backend/app/voice/service.py",
    "apps/backend/app/voice/stress.py",
    "tests/test_character_protocol_v3.py",
    "tests/test_voice_providers.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    mismatches: list[str] = []
    for relative in FILES:
        worktree = ROOT / relative
        snapshot = SNAPSHOT / relative
        if not worktree.exists():
            mismatches.append(f"missing worktree: {relative}")
        elif not snapshot.exists():
            mismatches.append(f"missing snapshot: {relative}")
        elif digest(worktree) != digest(snapshot):
            mismatches.append(f"changed since snapshot: {relative}")
    if mismatches:
        print("Snapshot mismatch:")
        print("\n".join(f"- {item}" for item in mismatches))
        return 1
    print(f"Baya handoff snapshot is exact: {len(FILES)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
