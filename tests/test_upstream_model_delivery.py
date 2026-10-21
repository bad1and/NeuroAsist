"""Direct model delivery metadata and release boundary regressions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from apps.backend.app.model_manager import service
from apps.backend.app.schemas.models import ManagedModelResponse
from scripts import check_release_artifact as release


def test_upstream_metadata_survives_api_serialization_without_downloading(tmp_path):
    manager = service.ModelManager(tmp_path)
    state = ManagedModelResponse(**manager.model_state("teratts-v2")).model_dump()
    assert state["delivery"] == "upstream_download"
    assert state["source_url"].endswith("/tree/f05ea799094571a3553904a555df3834fb0b963b")
    assert state["terms_url"] == "https://huggingface.co/terms-of-service"
    assert state["license"] is None  # Do not invent an SPDX license for v2.
    assert not state["installed"] and state["status"] == "not_installed"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("change", ["mirror", "moving_revision", "traversal"])
def test_catalog_rejects_unpinned_or_non_upstream_downloads(monkeypatch, change):
    path = Path(service.__file__).with_name("catalog.json")
    catalog = json.loads(path.read_text(encoding="utf-8"))
    model = next(item for item in catalog if item["id"] == "teratts-v2")
    if change == "mirror":
        model["files"][0]["url"] = "https://example.test/mirror/README.md"
    elif change == "moving_revision":
        model["revision"] = "main"
    else:
        model["files"][0]["path"] = "../README.md"
    read_text = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda self, *args, **kwargs: json.dumps(catalog) if self == path else read_text(self, *args, **kwargs))
    with pytest.raises(ValueError, match="pinned upstream"):
        service.catalog_specs()


@pytest.mark.parametrize("namespace", ["teratts-v2", "TeraTTSv2", "models--TeraSpace--TeraTTSv2"])
def test_release_rejects_model_snapshot_and_cache_directories(tmp_path, namespace):
    staging = tmp_path / "app"
    (staging / "models" / namespace / "snapshot").mkdir(parents=True)
    assert release.download_only_model_paths([staging]) == [f"app/models/{namespace}"]
    artifact = tmp_path / "Iris_1.0.0.exe"
    artifact.write_bytes(b"installer")
    with pytest.raises(ValueError, match="Download-only model"):
        release.build_manifest(artifact=artifact, version="1.0.0", staging_roots=[staging], signing_status="unsigned")


def test_release_detects_renamed_weights_but_allows_notices_and_other_onnx(monkeypatch, tmp_path):
    data = b"fixture TeraTTS weight"
    catalog_path = tmp_path / "apps/backend/app/model_manager/catalog.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(json.dumps([{"id": "teratts-v2", "files": [{"path": "models/tts.onnx", "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}]}]), encoding="utf-8")
    monkeypatch.setattr(release, "ROOT", tmp_path)
    staging = tmp_path / "core"
    staging.mkdir()
    (staging / "renamed.bin").write_bytes(data)
    (staging / "silero_vad.onnx").write_bytes(b"other library")
    (staging / "TeraTTS-NOTICE.txt").write_text("notice", encoding="utf-8")
    assert release.download_only_model_paths([staging]) == ["core/renamed.bin"]
    (staging / "renamed.bin").unlink()
    assert release.download_only_model_paths([staging]) == []


def test_preinstaller_rejects_model_cache_outside_core(tmp_path):
    for name in ("Iris.exe", "core/neuroasist-core.exe", "avatar/NeuroAsistAvatar.exe"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    (tmp_path / "models/teratts-v2").mkdir(parents=True)
    result = subprocess.run([sys.executable, str(release.ROOT / "scripts/check_preinstaller_app.py"), "--app", str(tmp_path), "--output", str(tmp_path / "manifest.json")], capture_output=True, text=True)
    assert result.returncode != 0
    assert "Download-only model resources" in result.stderr
    assert not (tmp_path / "manifest.json").exists()
