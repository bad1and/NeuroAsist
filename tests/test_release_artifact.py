from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_release_artifact import build_manifest, private_paths, retired_dependency_paths


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
    assert manifest["dependency_scan"]["forbidden_paths"] == []


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


@pytest.mark.parametrize(
    "name",
    (
        "edge_tts",
        "py7zr",
        "silero-0.5.5.dist-info",
        "silero_stress",
        "supertonic",
        "torchvision",
    ),
)
def test_release_scan_rejects_retired_dependencies(tmp_path: Path, name: str) -> None:
    staging = tmp_path / "core"
    package = staging / "_internal" / name
    package.mkdir(parents=True)

    assert retired_dependency_paths([staging]) == [f"core/_internal/{name}"]
    with pytest.raises(ValueError, match="Retired dependencies"):
        build_manifest(
            artifact=_installer(tmp_path),
            version="1.0.0",
            staging_roots=[staging],
            signing_status="unsigned",
        )


def test_release_scan_keeps_supported_silero_vad(tmp_path: Path) -> None:
    staging = tmp_path / "core"
    (staging / "_internal" / "silero_vad").mkdir(parents=True)
    (staging / "_internal" / "silero_vad-6.2.1.dist-info").mkdir()

    assert retired_dependency_paths([staging]) == []
