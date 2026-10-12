"""Explicit project registration and preparation of the fixed Docker sandbox."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
from pathlib import Path

from apps.backend.app.core.config import ROOT_DIR
from .runner import DockerSandboxRunner

_PROJECT_LOCK = threading.Lock()


def register_project(settings, value: str) -> list[str]:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute() or not candidate.is_dir():
        raise ValueError("Выберите существующую папку проекта.")
    candidate = candidate.resolve()
    workspace = settings.coding_workspace_path.resolve()
    if not (ROOT_DIR / ".git").exists() and (candidate.is_relative_to(ROOT_DIR.resolve()) or ROOT_DIR.resolve().is_relative_to(candidate)):
        raise ValueError("Папка приложения не является пользовательским проектом.")
    if candidate == Path(candidate.anchor) or candidate.is_relative_to(workspace) or workspace.is_relative_to(candidate):
        raise ValueError("Папка проекта должна быть отдельно от рабочих каталогов Iris.")
    path = settings.app_data_path / "coding-projects.json"
    with _PROJECT_LOCK:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = []
        roots = [p for p in existing if isinstance(p, str)] if isinstance(existing, list) else []
        if str(candidate) not in roots:
            roots.append(str(candidate))
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(roots, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return [str(p) for p in settings.coding_allowed_project_paths]


class CodingImagePreparation:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.task: asyncio.Task | None = None
        self.process: asyncio.subprocess.Process | None = None
        self.state: dict[str, object] = {"status": "idle", "output": "", "error": None}

    def start(self) -> dict[str, object]:
        if self.task and not self.task.done():
            return dict(self.state)
        self.state = {"status": "preparing", "output": "", "error": None}
        self.task = asyncio.create_task(self._prepare(), name="coding-image-preparation")
        return dict(self.state)

    async def _prepare(self) -> None:
        try:
            image = DockerSandboxRunner._image_reference(self.settings.coding_docker_image)
            context = ROOT_DIR / "apps/backend/docker"
            if not (context / "coding.Dockerfile").is_file():
                raise ValueError("В поставке отсутствуют ресурсы песочницы.")
            self.process = await asyncio.create_subprocess_exec(
                DockerSandboxRunner._docker_executable(), "build", "--progress=plain", "--tag", image,
                "--file", str(context / "coding.Dockerfile"), str(context),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            assert self.process.stdout is not None
            while line := await self.process.stdout.readline():
                self.state["output"] = (str(self.state["output"]) + line.decode("utf-8", errors="replace"))[-8000:]
            code = await self.process.wait()
            if code:
                raise RuntimeError("Docker не смог подготовить образ. Проверьте сеть и журнал подготовки.")
            self.state["status"] = "ready"
        except asyncio.CancelledError:
            self.state["status"] = "cancelled"
        except (OSError, ValueError, RuntimeError) as error:
            self.state.update(status="failed", error=str(error))
        finally:
            if self.process and self.process.returncode is None:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=10)
                except asyncio.TimeoutError:
                    self.process.kill()
                    await self.process.wait()
            self.process = None

    async def close(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            await self.task
