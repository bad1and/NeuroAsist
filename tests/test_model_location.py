from pathlib import Path

import pytest

from apps.backend.app.model_manager.location import model_root, set_model_directory


def test_default_keeps_existing_models(tmp_path):
    assert model_root(tmp_path) == tmp_path / "models"


def test_selected_parent_has_dedicated_persistent_child(tmp_path):
    profile = tmp_path / "profile"
    parent = tmp_path / "other-drive"
    parent.mkdir()
    old = profile / "models" / "keep.bin"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"existing model")
    result = set_model_directory(profile, parent)
    assert Path(result["directory"]) == parent / "Iris-models"
    assert model_root(profile) == parent / "Iris-models"
    assert old.read_bytes() == b"existing model"
    assert not list(profile.glob("*.tmp"))


@pytest.mark.parametrize("target", ["relative", "missing"])
def test_invalid_selection_preserves_previous_configuration(tmp_path, target):
    set_model_directory(tmp_path / "profile", tmp_path)
    original = model_root(tmp_path / "profile")
    with pytest.raises(ValueError):
        set_model_directory(tmp_path / "profile", Path("relative") if target == "relative" else tmp_path / "missing")
    assert model_root(tmp_path / "profile") == original


def test_unavailable_storage_does_not_fall_back_to_system_drive(tmp_path):
    profile = tmp_path / "profile"
    external = tmp_path / "external"
    external.mkdir()
    set_model_directory(profile, external)
    (external / "Iris-models").rmdir()
    external.rmdir()
    assert model_root(profile) == external / "Iris-models"
