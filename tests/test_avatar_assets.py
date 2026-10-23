from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts import avatar_assets as assets


def repo(root: Path) -> Path:
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "VERSION").write_text("1.0.0\n")
    source = root / "apps/avatar-unity/Assets/Code.cs"
    source.parent.mkdir(parents=True)
    source.write_text("public class Avatar {}")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], cwd=root, check=True)
    return root


def player(root: Path) -> Path:
    root.mkdir()
    (root / "NeuroAsistAvatar.exe").write_bytes(b"MZ player")
    (root / "UnityPlayer.dll").write_bytes(b"MZ engine")
    data = root / "NeuroAsistAvatar_Data"
    data.mkdir()
    (data / "sharedassets0.assets").write_bytes(b"compiled Unity resources")
    return root


@pytest.mark.parametrize("name", ["apps/avatar-unity/Assets/IRIS.vrm", "apps/web/public/avatar/IRIS.vrm",
    "renamed/AVATAR.VRM", "model.glb", "apps/avatar-unity/Assets/NeuroAsistAvatar/Animations/A.fbx",
    "apps/avatar-unity/Assets/NeuroAsistAvatar/Motion/Generated/Performances.asset"])
def test_private_paths(name):
    assert assets.private_source(name)


@pytest.mark.parametrize("name", ["apps/avatar-unity/Assets/IRIS.vrm.meta", "apps/avatar-unity/Packages/com.vrmc.vrm/Runtime/Loader.cs",
    "apps/avatar-unity/Packages/com.vrmc.gltf/Editor/UniGLTF/Gizmo/Models/Bone.fbx", "apps/avatar-unity/Assets/NeuroAsistAvatar/Runtime/Motion.cs"])
def test_public_code_and_importer_guid_are_kept(name):
    assert not assets.private_source(name)


def test_public_scan_checks_tracked_inputs_and_renamed_glb_but_allows_ignored_local_asset(tmp_path):
    root = repo(tmp_path / "repo")
    (root / "local.vrm").write_bytes(b"local")
    (root / "innocent.bin").write_bytes(b"glTF" + b"model")
    subprocess.run(["git", "add", "innocent.bin"], cwd=root, check=True)
    assert assets.public_findings(root) == ["innocent.bin"]


def test_private_export_and_import_validate_every_file_before_writing(tmp_path):
    source = repo(tmp_path / "source")
    name = "apps/avatar-unity/Assets/IRIS.vrm"
    (source / name).write_bytes(b"glTF avatar")
    subprocess.run(["git", "add", name], cwd=source, check=True)
    private = tmp_path / "private"
    assets.export_private(source, private)
    target = repo(tmp_path / "target")
    (private / "assets" / name).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Invalid private asset"):
        assets.import_private(target, private)
    assert not (target / name).exists()
    (private / "assets" / name).write_bytes(b"glTF avatar")
    assets.import_private(target, private)
    assert (target / name).read_bytes() == b"glTF avatar"
    with pytest.raises(ValueError, match="overwrite"):
        assets.import_private(target, private)


@pytest.mark.parametrize("name", ["../escape", "C:/escape", "player\\escape", "player/../escape", "player/CON", "player/trailing."])
def test_archive_paths_reject_windows_aliases_and_traversal(name):
    with pytest.raises(ValueError, match="Unsafe"):
        assets.safe_name(name)


def package(tmp_path):
    root = repo(tmp_path / "source")
    built = player(tmp_path / "player")
    archive = tmp_path / "avatar.zip"
    assets.package_player(built, archive, assets.source_record(root), "1.0.0")
    return root, archive


def rewrite(archive, mutate):
    with zipfile.ZipFile(archive) as bundle:
        entries = {n: bundle.read(n) for n in bundle.namelist()}
    mutate(entries)
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, data in entries.items(): bundle.writestr(name, data)


def test_player_roundtrip_and_archive_hash_binding(tmp_path):
    root, archive = package(tmp_path)
    destination = tmp_path / "installed"
    with pytest.raises(ValueError, match="SHA-256"):
        assets.install_player(archive, "0" * 64, destination, root)
    assert not destination.exists()
    manifest = assets.install_player(archive, assets.sha256(archive), destination, root)
    assert manifest["files"]["NeuroAsistAvatar.exe"]["sha256"] == assets.sha256(destination / "NeuroAsistAvatar.exe")
    with pytest.raises(ValueError, match="must not exist"):
        assets.install_player(archive, assets.sha256(archive), destination, root)


def test_player_rejects_stale_renderer_sources(tmp_path):
    root, archive = package(tmp_path)
    (root / "apps/avatar-unity/Assets/Code.cs").write_text("different source")
    with pytest.raises(ValueError, match="different renderer sources"):
        assets.install_player(archive, assets.sha256(archive), tmp_path / "installed", root)


@pytest.mark.parametrize("kind", ["unexpected", "tampered", "traversal", "case-collision"])
def test_player_rejects_invalid_inventory_without_leaving_destination(tmp_path, kind):
    root, archive = package(tmp_path)
    def mutate(entries):
        if kind == "unexpected": entries["player/extra.dll"] = b"extra"
        elif kind == "tampered": entries["player/UnityPlayer.dll"] = b"different"
        elif kind == "traversal": entries["../escape"] = b"escape"
        else: entries["PLAYER/UnityPlayer.dll"] = b"collision"
    rewrite(archive, mutate)
    destination = tmp_path / "installed"
    with pytest.raises(ValueError):
        assets.install_player(archive, assets.sha256(archive), destination, root)
    assert not destination.exists()
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("name,content", [("model.vrm", b"model"), ("renamed.bin", b"glTF model"), ("scene.unity", b"scene")])
def test_player_scan_rejects_source_assets(tmp_path, name, content):
    root = player(tmp_path / "player")
    (root / "NeuroAsistAvatar_Data" / name).write_bytes(content)
    assert "NeuroAsistAvatar_Data/" + name in assets.player_findings(root)
