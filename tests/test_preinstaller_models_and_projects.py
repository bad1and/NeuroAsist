import hashlib
import json
import threading
import time
from pathlib import Path

import pytest

from apps.backend.app.model_manager.service import ModelManager, ModelSpec
from apps.backend.app.core.config import Settings
from apps.backend.app.coding.setup import register_project


def wait(manager, name):
    for _ in range(200):
        state = manager.model_state(name)
        if state["status"] not in {"downloading", "verifying"}:
            return state
        time.sleep(.01)
    pytest.fail("Model operation did not finish")


def test_directory_install_verifies_every_file_and_removes_only_managed_model(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"pinned weights")
    file = {"path": "nested/weights.bin", "url": source.as_uri(), "size_bytes": source.stat().st_size, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    spec = ModelSpec("bundle", "Bundle", "revision", "", "bundle/revision", "manifest", source.stat().st_size, files=(file,))
    manager = ModelManager(tmp_path / "models", specs=(spec,))
    manager.install_async("bundle")
    assert wait(manager, "bundle")["installed"]
    assert (manager.path_for("bundle") / "nested/weights.bin").read_bytes() == source.read_bytes()
    unrelated = manager.root / "unrelated"
    unrelated.write_text("keep")
    assert manager.remove("bundle")["installed"] is False
    assert unrelated.read_text() == "keep"


def test_directory_bad_checksum_never_publishes_installed(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"wrong")
    file = {"path": "weights.bin", "url": source.as_uri(), "size_bytes": 5, "sha256": "0" * 64}
    manager = ModelManager(tmp_path / "models", specs=(ModelSpec("bundle", "Bundle", "revision", "", "bundle", "manifest", 5, files=(file,)),))
    manager.install_async("bundle")
    state = wait(manager, "bundle")
    assert state["status"] == "failed" and not state["installed"]


def test_cancel_during_download_discards_partial_file(monkeypatch, tmp_path):
    entered, release = threading.Event(), threading.Event()
    class Response:
        headers = {"Content-Length": "6"}
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, _size):
            entered.set()
            assert release.wait(5)
            return b"secret"
    monkeypatch.setattr("apps.backend.app.model_manager.service.urlopen", lambda *_args, **_kwargs: Response())
    manager = ModelManager(tmp_path, specs=(ModelSpec("single", "Single", "1", "https://example.test/file", "weights.bin", hashlib.sha256(b"secret").hexdigest(), 6),))
    manager.install_async("single")
    assert entered.wait(5)
    manager.cancel("single")
    release.set()
    state = wait(manager, "single")
    assert state["status"] == "cancelled" and not state["installed"]
    assert not manager.path_for("single").exists()
    manager.close()


def test_projects_require_explicit_registration_and_workspace_is_in_profile(tmp_path):
    settings = Settings(_env_file=None, app_data_dir=str(tmp_path / "profile"), coding_allowed_project_roots="")
    assert settings.coding_allowed_project_paths == ()
    assert settings.coding_workspace_path == (tmp_path / "profile/coding-workspaces").resolve()
    project = tmp_path / "project"
    project.mkdir()
    assert register_project(settings, str(project)) == [str(project.resolve())]
    assert register_project(settings, str(project)) == [str(project.resolve())]
    with pytest.raises(ValueError):
        register_project(settings, str(settings.app_data_path))


def test_python_checker_tracks_transitive_extras():
    from scripts.check_python_dependencies import resolved_closure
    class Distribution:
        def __init__(self, *requires): self.requires = requires
    graph = {"root": Distribution("server[standard]"), "server": Distribution('watcher; extra == "standard"'), "watcher": Distribution()}
    assert resolved_closure({"root"}, graph) == ({"root", "server", "watcher"}, [])


def test_managed_runtime_rejects_corrupt_weights_before_loading(monkeypatch, tmp_path):
    import apps.backend.app.model_manager.service as models
    spec = ModelSpec("single", "Single", "1", "", "weights.bin", hashlib.sha256(b"valid").hexdigest(), 5)
    monkeypatch.setenv("NEUROASIST_MANAGED_MODELS", "1")
    monkeypatch.setenv("NEUROASIST_APP_DATA_DIR", str(tmp_path))
    factory = models.ModelManager
    monkeypatch.setattr(models, "ModelManager", lambda root: factory(root, specs=(spec,)))
    path = tmp_path / "models/weights.bin"
    path.parent.mkdir()
    path.write_bytes(b"valid")
    models.require_managed_model("single", path)
    path.write_bytes(b"wrong")
    with pytest.raises(RuntimeError, match="повреждена"):
        models.require_managed_model("single", path)


def test_registered_projects_are_available_alongside_explicit_configuration(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir(); second.mkdir()
    settings = Settings(_env_file=None, app_data_dir=str(tmp_path / "profile"), coding_allowed_project_roots=str(first))
    assert register_project(settings, str(second)) == [str(first.resolve()), str(second.resolve())]


def test_insufficient_space_leaves_model_uninstalled_and_retry_recovers(monkeypatch, tmp_path):
    import shutil
    source = tmp_path / "source.bin"
    source.write_bytes(b"weights")
    spec = ModelSpec("single", "Single", "1", source.as_uri(), "weights.bin", hashlib.sha256(b"weights").hexdigest(), 7)
    manager = ModelManager(tmp_path / "models", specs=(spec,))
    with monkeypatch.context() as patch:
        patch.setattr(shutil, "disk_usage", lambda _: shutil._ntuple_diskusage(100, 100, 0))
        manager.install_async("single")
        state = wait(manager, "single")
        assert state["status"] == "failed" and not state["installed"]
        assert "места" in state["error"]
        manager.close()
    manager.install_async("single")
    assert wait(manager, "single")["installed"]
    manager.close()


def test_network_failure_is_retryable_without_publishing_partial_weights(monkeypatch, tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"weights")
    manager = ModelManager(tmp_path / "models", specs=(ModelSpec("single", "Single", "1", source.as_uri(), "weights.bin", hashlib.sha256(b"weights").hexdigest(), 7),))
    with monkeypatch.context() as patch:
        patch.setattr("apps.backend.app.model_manager.service.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("network disconnected")))
        manager.install_async("single")
        state = wait(manager, "single")
        assert state["status"] == "failed" and not state["installed"]
        assert "network disconnected" in state["error"]
        manager.close()
    manager.install_async("single")
    assert wait(manager, "single")["installed"]
    manager.close()


def test_image_preparation_without_docker_is_actionable(monkeypatch):
    import asyncio
    from apps.backend.app.coding.setup import CodingImagePreparation, DockerSandboxRunner
    monkeypatch.setattr(DockerSandboxRunner, "_docker_executable", lambda: (_ for _ in ()).throw(FileNotFoundError("Docker CLI missing")))
    preparation = CodingImagePreparation(Settings(_env_file=None))
    async def run():
        preparation.start()
        await preparation.task
    asyncio.run(run())
    assert preparation.state["status"] == "failed"
    assert "Docker" in preparation.state["error"]
    assert preparation.process is None
