from __future__ import annotations

import asyncio
import contextlib
import os
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

    async def availability(self) -> tuple[bool, str | None]:
        try:
            result = await self._exec(["docker", "version", "--format", "{{.Server.Version}}"], timeout=8)
        except OSError:
            return False, "Docker CLI is not installed or unavailable"
        if result["exit_code"] != 0:
            return False, "Docker daemon is unavailable"
        image = await self._exec(["docker", "image", "inspect", self.settings.coding_docker_image], timeout=8)
        if image["exit_code"] != 0:
            return False, f"Docker image {self.settings.coding_docker_image} is not built"
        return True, None

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
            "docker", "run", "--rm", "--name", container_name,
            "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
            "--mount", mount, "--workdir", "/workspace",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", str(self.settings.coding_pids_limit),
            "--memory", f"{self.settings.coding_memory_mb}m",
            "--cpus", str(self.settings.coding_cpus),
            "--user", "10001:10001", self.settings.coding_docker_image,
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
            await self._exec(["docker", "kill", container_name], timeout=8)

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
