from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_and_documentation_are_synchronized() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_docs.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
