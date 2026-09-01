from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from apps.backend.app.core.config import Settings


class CommandPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(frozen=True)
class DockerAvailability:
    """Independent readiness facts for the Docker-backed task sandbox."""

    cli_available: bool
    daemon_available: bool
    image_available: bool
    image_name: str
    reason: str | None = None

    @property
    def sandbox_available(self) -> bool:
        return self.daemon_available and self.image_available


class DockerSandboxRunner:
    """Run only policy-approved commands inside a task-specific Docker container.

    The host only invokes Docker with server-authored arguments. Model-provided
    command text is converted into an argv array, validated, and never sent to
    a shell. The live project is never mounted into the container.
    """

    _executables = {"python", "python3", "pytest", "node", "npm", "npx"}
    _forbidden_tokens = {"install", "ci", "publish", "login", "logout", "config", "exec"}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._active_containers: dict[str, str] = {}

    async def availability(self) -> DockerAvailability:
        image_name = self._image_reference(self.settings.coding_docker_image)
        try:
            result = await self._exec([self._docker_executable(), "version", "--format", "{{.Server.Version}}"], timeout=8)
        except OSError:
            return DockerAvailability(False, False, False, image_name, "Docker CLI is not installed or unavailable")
        if result["timed_out"] or result["exit_code"] != 0:
            return DockerAvailability(True, False, False, image_name, "Docker daemon is unavailable")
        try:
            image = await self._exec([self._docker_executable(), "image", "inspect", image_name], timeout=8)
        except OSError:
            return DockerAvailability(True, False, False, image_name, "Docker daemon became unavailable")
        if image["timed_out"]:
            return DockerAvailability(True, True, False, image_name, "Docker image check timed out")
        if image["exit_code"] != 0:
            return DockerAvailability(True, True, False, image_name, f"Docker image {image_name} is not built")
        return DockerAvailability(True, True, True, image_name)

    @staticmethod
    def _docker_executable() -> str:
        """Find Docker Desktop even when the desktop app inherited an old PATH.

        On Windows a newly installed per-user Docker Desktop keeps its CLI in
        ``%LOCALAPPDATA%\\Programs\\DockerDesktop``.  A running Iris process
        does not receive the updated PATH until it is restarted, so relying on
        ``docker`` alone creates a false "CLI is not installed" diagnostic.
        """
        if executable := shutil.which("docker"):
            return executable
        if os.name == "nt":
            candidates = [
                Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "DockerDesktop" / "resources" / "bin" / "docker.exe",
                Path(os.environ.get("ProgramFiles", "")) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe",
            ]
            for candidate in candidates:
                if candidate.is_file():
                    return str(candidate)
        return "docker"

    @staticmethod
    def _image_reference(image_name: str) -> str:
        """Use Docker's explicit ``latest`` tag for untagged local images.

        Docker's CLI normally implies this tag, but recent Docker Desktop
        builds can list ``name:latest`` while rejecting ``image inspect name``.
        Keeping the reference explicit makes the availability probe identical
        to the sandbox container invocation.
        """
        reference = image_name.strip()
        if not reference or "@" in reference:
            return reference
        final_component = reference.rsplit("/", 1)[-1]
        return reference if ":" in final_component else f"{reference}:latest"

    def validate_argv(self, value: object) -> list[str]:
        if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
            raise CommandPolicyError("A command must be a non-empty argv list")
        argv = [item.strip() for item in value]
        if not argv[0] or argv[0] not in self._executables:
            raise CommandPolicyError("Executable is not allowed")
        if any(not item or len(item) > 500 or "\x00" in item for item in argv):
            raise CommandPolicyError("Invalid command argument")
        if any(item.casefold() in self._forbidden_tokens for item in argv[1:]):
            raise CommandPolicyError("Dependency or publishing commands are not allowed")
        # No arbitrary paths outside /workspace and no shell interpreters.
        if any(item.startswith(("/", "\\")) or ".." in Path(item).parts for item in argv[1:] if not item.startswith("-")):
            raise CommandPolicyError("Absolute paths and parent traversal are not allowed")
        # The base image intentionally ships Debian's ``python3`` binary.
        # Keep ``python`` as a convenient model-facing alias, but execute the
        # real binary so Node's inherited docker-entrypoint cannot mistake a
        # missing ``python`` command for a JavaScript file.
        if argv[0] == "python":
            argv[0] = "python3"
        return argv

    async def run(self, task_id: str, workspace: Path, argv: object) -> CommandResult:
        command = self.validate_argv(argv)
        image_name = self._image_reference(self.settings.coding_docker_image)
        container_name = f"neuroasist-coding-{task_id[:24]}"
        self._active_containers[task_id] = container_name
        # Docker requires an absolute host source path. Workspace is created
        # locally by TaskSandbox and contains only copied allowed files.
        # With ``--mount`` the bind is read-write by default.  ``rw`` is valid
        # for ``-v`` volume syntax, but Docker Desktop rejects it here because
        # every --mount option must be a key=value pair (or ``readonly``).
        # Omitting it preserves the intended writable task workspace on both
        # Windows Docker Desktop and Linux Docker Engine.
        mount = f"type=bind,src={workspace.resolve()},dst=/workspace"
        docker_argv = [
            self._docker_executable(), "run", "--rm", "--name", container_name,
            "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
            "--mount", mount, "--workdir", "/workspace",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", str(self.settings.coding_pids_limit),
            "--memory", f"{self.settings.coding_memory_mb}m",
            "--cpus", str(self.settings.coding_cpus),
            "--user", "10001:10001", image_name,
            *command,
        ]
        try:
            result = await self._exec(docker_argv, timeout=self.settings.coding_command_timeout_seconds)
            return CommandResult(command=command, **result)
        finally:
            self._active_containers.pop(task_id, None)

    async def cancel(self, task_id: str) -> None:
        container_name = self._active_containers.get(task_id)
        if not container_name:
            return
        with contextlib.suppress(Exception):
            await self._exec([self._docker_executable(), "kill", container_name], timeout=8)

    async def _exec(self, argv: list[str], *, timeout: float) -> dict[str, object]:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Windows should not open a visible console window for docker.exe.
            creationflags=getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            timed_out = False
        except TimeoutError:
            process.kill()
            stdout, stderr = await process.communicate()
            timed_out = True
        limit = self.settings.coding_max_output_bytes
        return {
            "exit_code": process.returncode,
            "stdout": stdout[:limit].decode("utf-8", errors="replace"),
            "stderr": stderr[:limit].decode("utf-8", errors="replace"),
            "timed_out": timed_out,
        }
