from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_release_artifact import build_manifest, private_paths


def _installer(root: Path, version: str = "1.0.0") -> Path:
    installer = root / f"Iris_{version}_x64-setup.exe"
    installer.write_bytes(b"candidate installer")
    return installer


def test_release_manifest_hashes_installer_and_records_resource_scan(tmp_path: Path) -> None:
    staging = tmp_path / "core"
    staging.mkdir()
    (staging / "neuroasist-core.exe").write_bytes(b"sidecar")

    manifest = build_manifest(
        artifact=_installer(tmp_path),
        version="1.0.0",
        staging_roots=[staging],
        signing_status="unsigned",
    )

    assert manifest["installer"]["filename"] == "Iris_1.0.0_x64-setup.exe"
    assert len(manifest["installer"]["sha256"]) == 64
    assert manifest["privacy_scan"]["forbidden_files"] == []


@pytest.mark.parametrize("name", (".env", "timeline.sqlite3", "sample.wav"))
def test_release_scan_rejects_private_runtime_files(tmp_path: Path, name: str) -> None:
    staging = tmp_path / "core"
    staging.mkdir()
    (staging / name).write_bytes(b"private")

    assert private_paths([staging]) == [f"core/{name}"]
    with pytest.raises(ValueError, match="Private runtime data"):
        build_manifest(
            artifact=_installer(tmp_path),
            version="1.0.0",
            staging_roots=[staging],
            signing_status="unsigned",
        )
