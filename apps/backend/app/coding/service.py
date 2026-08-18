from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from apps.backend.app.coding.policy import CodingPolicyError
from apps.backend.app.coding.runner import CommandPolicyError, DockerAvailability, DockerSandboxRunner
from apps.backend.app.coding.sandbox import SnapshotLimitError, TaskSandbox
from apps.backend.app.core.config import Settings
from apps.backend.app.llm.base import ChatMessage, LLMProvider, LLMProviderError
from apps.backend.app.llm.providers.deepseek import DeepSeekProvider
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineStore

logger = logging.getLogger(__name__)

_DOCKER_AVAILABILITY_TTL_SECONDS = 5.0

_SYSTEM_PROMPT = """You are the Coding Agent in NeuroAsist. Work only inside an isolated
task workspace. It may be an empty new workspace or a copy of explicitly approved files.
You may inspect files, make focused edits, execute tests, and iterate.
Never claim a command passed unless its returned output says so. Return exactly one
JSON object, no markdown, with one of these shapes:
{"action":"read_file","path":"relative/file.py"}
{"action":"list_files"}
{"action":"write_file","path":"relative/file.py","content":"full UTF-8 file content"}
{"action":"delete_file","path":"relative/file.py"}
{"action":"run_command","argv":["python","-m","pytest","-q"]}
{"action":"finish","summary":"what changed and verification","tests":"result"}
{"action":"wait_for_input","question":"specific blocker or decision"}
Paths must be relative and can only address files in the task workspace. Do not install
packages, access network, use a shell, or ask for access outside the workspace.
Prefer small edits and run relevant checks before finish."""


class CodingAgentService:
    """Durable, review-first coding loop built from intentionally narrow tools."""

    def __init__(
        self,
        settings: Settings,
        runtime_settings: RuntimeSettings,
        store: TimelineStore | None,
        event_publisher,
        llm_provider_factory=None,
        notification_speaker: Callable[[str, str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.runtime_settings = runtime_settings
        self.store = store
        self.event_publisher = event_publisher
        self.runner = DockerSandboxRunner(settings)
        self._active_task_id: str | None = None
        self._availability: DockerAvailability | None = None
        self._availability_checked_at = 0.0
        self._llm_provider_factory = llm_provider_factory or self._provider
        self._notification_speaker = notification_speaker

    def bind_notification_speaker(self, speaker: Callable[[str, str], None] | None) -> None:
        """Bind the shared voice path after the application creates it."""
        self._notification_speaker = speaker

    def _provider(self, model: str) -> LLMProvider:
        return DeepSeekProvider(
            self.settings,
            model=model,
            api_key=self.settings.coding_llm_api_key,
            base_url=self.settings.coding_llm_base_url,
            timeout=self.settings.coding_llm_timeout_seconds,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.settings.coding_agent_enabled and self.runtime_settings.coding_agent_enabled)

    async def status(self, *, refresh: bool = False) -> dict[str, object]:
        docker = await self._docker_availability(refresh=refresh)
        available, reason = docker.sandbox_available, docker.reason
        workspace_issue = self._workspace_issue()
        if workspace_issue:
            available, reason = False, workspace_issue
        elif not self.settings.coding_llm_api_key:
            available, reason = False, "Coding API key is not configured"
        tasks = self.store.list_coding_tasks(limit=100) if self.store is not None else []
        active = next((item for item in tasks if item["status"] == "running"), None)
        return {
            "enabled": self.enabled,
            "configured_enabled": self.settings.coding_agent_enabled,
            "available": available,
            "availability_reason": reason,
            "docker_cli_available": docker.cli_available,
            "docker_daemon_available": docker.daemon_available,
            "docker_image_available": docker.image_available,
            "docker_image_name": docker.image_name,
            "model": self.runtime_settings.coding_model,
            "available_models": ["deepseek-v4-flash", "deepseek-v4-pro"],
            "project_root": str(self._project_root()),
            "allowed_project_roots": [str(item) for item in self.settings.coding_allowed_project_paths],
            "workspace_name": self.runtime_settings.coding_workspace_name,
            "workspace_root": str(self.settings.coding_workspace_path),
            "auto_delegate": self.runtime_settings.coding_auto_delegate,
            "active_task_id": str(active["id"]) if active else None,
            "active_task_status": str(active["status"]) if active else None,
            "queued_count": sum(1 for item in tasks if item["status"] == "pending"),
        }

    def create_task(
        self,
        objective: str,
        *,
        session_id: str | None = None,
        source_message_id: str | None = None,
        context_files: list[str] | None = None,
        project_root: str | None = None,
    ) -> dict[str, object]:
        if self.store is None:
            raise RuntimeError("Coding Agent requires timeline storage")
        if not self.enabled:
            raise PermissionError("Coding Agent is disabled")
        if workspace_issue := self._workspace_issue():
            raise ValueError(workspace_issue)
        # No source root means a standalone task: files live only in its
        # configured workspace. Supplying context files opts into a read-only
        # project snapshot of just those files.
        root = self._project_root(project_root) if project_root or context_files else None
        task = self.store.create_coding_task(
            objective=objective.strip(), model=self.runtime_settings.coding_model,
            project_root=str(root) if root is not None else "", workspace_name=self.runtime_settings.coding_workspace_name,
            session_id=session_id, source_message_id=source_message_id, context_files=context_files,
        )
        return task

    async def run_once(self) -> bool:
        if self.store is None or not self.enabled or self._active_task_id is not None:
            return False
        job = self.store.claim_coding_task_job()
        if job is None:
            return False
        payload = self._load_json(job.get("payload_json"))
        task_id = str(payload.get("task_id", ""))
        task = self.store.get_coding_task(task_id)
        if task is None:
            self.store.finish_background_job(str(job["id"]), result={"outcome": "missing_task"}, diagnostics={})
            return True
        if task["status"] in {"cancelled", "applied", "failed", "conflicted"}:
            if task["status"] == "failed":
                # Recover a notification if a process stopped after persisting
                # the failure but before Iris could update the chat.
                self._notify_task_failed(task)
            self.store.finish_background_job(str(job["id"]), result={"outcome": str(task["status"])}, diagnostics={})
            return True
        if task["status"] == "review_ready":
            # A process can stop after the durable task update but before its
            # chat notification.  The notification is idempotent, so recover
            # it when the queued job is observed again.
            self._notify_review_ready(task)
            self.store.finish_background_job(str(job["id"]), result={"outcome": "review_ready"}, diagnostics={})
            return True
        self._active_task_id = task_id
        try:
            await self._run_task(task)
            self.store.finish_background_job(str(job["id"]), result={"outcome": "processed"}, diagnostics={})
        except Exception as error:
            logger.exception("Coding task failed: %s", task_id)
            self.store.update_coding_task(task_id, status="failed", error=f"{type(error).__name__}: {error}")
            self.store.append_coding_event(task_id, "task.failed", "error", "Coding task failed", {"error": str(error)[:1000]})
            self._notify_task_failed(task)
            self.store.finish_background_job(
                str(job["id"]), result={"outcome": "failed"}, diagnostics={}, status="failed", error=str(error),
            )
        finally:
            self._active_task_id = None
        return True

    async def cancel(self, task_id: str) -> dict[str, object] | None:
        if self.store is None:
            return None
        task = self.store.request_coding_cancel(task_id)
        await self.runner.cancel(task_id)
        return task

    def add_instruction(self, task_id: str, text: str) -> dict[str, object] | None:
        if self.store is None:
            return None
        task = self.store.add_coding_instruction(task_id, text.strip())
        if task is not None and task["status"] == "waiting_for_input":
            task = self.store.requeue_coding_task(task_id)
        return task

    def retry(self, task_id: str) -> dict[str, object] | None:
        if self.store is None:
            return None
        task = self.store.get_coding_task(task_id, include_events=False)
        # Tasks created before standalone workspaces were introduced stored
        # the selected project even with no requested context.  Retrying the
        # reported snapshot-limit error must not repeat that unsafe full copy.
        if (
            task is not None
            and not task.get("context_files")
            and str(task.get("project_root") or "")
            and "SnapshotLimitError" in str(task.get("error_text") or "")
        ):
            self.store.detach_coding_task_from_project(task_id)
            self.store.append_coding_event(
                task_id, "workspace.detached", "info",
                "Retry changed to a new standalone task workspace",
            )
        return self.store.requeue_coding_task(task_id)

    def clear_completed_tasks(self) -> int:
        if self.store is None:
            return 0
        active_statuses = {"pending", "running", "waiting_for_input"}
        if any(item["status"] in active_statuses for item in self.store.list_coding_tasks(limit=300)):
            raise ValueError("Stop or finish the active Coding Agent task before clearing the task list")
        return self.store.clear_completed_coding_tasks()

    def apply(self, task_id: str) -> dict[str, object]:
        if self.store is None:
            raise RuntimeError("Coding Agent requires timeline storage")
        task = self.store.get_coding_task(task_id, include_events=False)
        if task is None:
            raise KeyError(task_id)
        if task["status"] != "review_ready":
            raise ValueError("Only a reviewed task can be applied")
        sandbox = self._sandbox_from_task(task)
        changes = sandbox.apply_to_source()
        result = dict(task["result"])
        result["applied_files"] = [item.path for item in changes]
        self.store.update_coding_task(task_id, status="applied", result=result)
        self.store.append_coding_event(task_id, "task.applied", "info", "Reviewed changes applied to source project", {"files": result["applied_files"]})
        return self.store.get_coding_task(task_id) or task

    async def _run_task(self, task: dict[str, object]) -> None:
        assert self.store is not None
        task_id = str(task["id"])
        docker = await self._docker_availability(refresh=True)
        if not docker.sandbox_available:
            raise RuntimeError(docker.reason or "Docker sandbox is unavailable")
        project_root = Path(str(task["project_root"])) if str(task["project_root"]) else None
        sandbox = TaskSandbox(
            self.settings, task_id=task_id, project_root=project_root,
            workspace_name=str(task["workspace_name"]),
        )
        existing_manifest = task.get("base_manifest")
        # An empty ``files`` manifest is valid for a standalone task.  It must
        # still be reused on retry, otherwise a cancelled task that already
        # created files would be recreated and lose its isolated work.
        reused_workspace = (
            sandbox.base.exists()
            and isinstance(existing_manifest, dict)
            and isinstance(existing_manifest.get("files"), dict)
            and "version" in existing_manifest
        )
        if reused_workspace:
            # Retrying a failed/cancelled task keeps its isolated work intact;
            # it never reaches back into the live source project.
            sandbox.open_existing(existing_manifest)
            manifest = sandbox.manifest
            self.store.append_coding_event(task_id, "workspace.reused", "info", "Resuming existing isolated workspace")
        else:
            try:
                manifest = (
                    sandbox.create_snapshot(list(task["context_files"]))
                    if project_root is not None
                    else sandbox.create_empty_workspace()
                )
            except Exception:
                # A malformed selection can leave only a partial task copy.
                # It contains no live source and may be safely removed so a
                # corrected retry is possible.
                if sandbox.base.exists():
                    shutil.rmtree(sandbox.base, ignore_errors=True)
                raise
        self.store.update_coding_task(task_id, status="running", workspace_path=str(sandbox.base), base_manifest=manifest)
        if not reused_workspace:
            self.store.append_coding_event(
                task_id,
                "workspace.created",
                "info",
                "Created isolated source snapshot" if project_root is not None else "Created standalone task workspace",
                {"files": len(manifest["files"]), "path": str(sandbox.base), "standalone": project_root is None},
            )
        messages = [
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(role="user", content=self._task_prompt(task, sandbox)),
        ]
        provider = self._llm_provider_factory(str(task["model"]))
        successful_command = False
        for iteration in range(1, self.settings.coding_max_iterations + 1):
            if self.store.coding_task_cancel_requested(task_id):
                self.store.update_coding_task(task_id, status="cancelled")
                self.store.append_coding_event(task_id, "task.cancelled", "warning", "Coding task cancelled")
                return
            instructions = self.store.consume_coding_instructions(task_id)
            if instructions:
                messages.append(ChatMessage(role="user", content="Additional user instruction(s):\n" + "\n".join(instructions)))
            self.store.append_coding_event(task_id, "agent.thinking", "info", f"Planning step {iteration}")
            try:
                answer = await provider.generate_structured(messages, temperature=0.1)
                action = self._parse_action(answer.content)
            except (LLMProviderError, ValueError, json.JSONDecodeError) as error:
                messages.append(ChatMessage(role="user", content=f"The previous response was invalid ({error}). Return one valid action JSON."))
                self.store.append_coding_event(task_id, "agent.invalid_response", "warning", "Invalid model action; retrying", {"error": str(error)[:500]})
                continue
            tool_result, terminal = await self._dispatch(task_id, sandbox, action)
            if action.get("action") == "run_command" and bool(tool_result.get("ok")):
                successful_command = True
            if terminal == "review_ready" and sandbox.changed_files() and not successful_command:
                tool_result = {
                    "ok": False,
                    "error": "Changed code requires at least one successful sandbox verification command before finish.",
                }
                terminal = None
                self.store.append_coding_event(
                    task_id, "verification.required", "warning",
                    "Finish blocked until a sandbox verification command succeeds",
                )
            messages.append(ChatMessage(role="assistant", content=json.dumps(action, ensure_ascii=False)))
            messages.append(ChatMessage(role="user", content="Tool result:\n" + json.dumps(tool_result, ensure_ascii=False)[: self.settings.coding_max_output_bytes]))
            if terminal == "review_ready":
                patch = sandbox.diff_text(self.settings.coding_max_patch_bytes)
                result = dict(tool_result.get("result") or {})
                result["changed_files"] = [item.__dict__ for item in sandbox.changed_files()]
                self.store.update_coding_task(task_id, status="review_ready", result=result, patch_text=patch)
                self.store.append_coding_event(task_id, "task.review_ready", "info", "Changes are ready for review", {"changed_files": result["changed_files"], "tests": result.get("tests")})
                self._notify_review_ready(task)
                return
            if terminal == "waiting_for_input":
                self.store.update_coding_task(task_id, status="waiting_for_input", result=tool_result)
                self.store.append_coding_event(task_id, "task.waiting_for_input", "warning", "Coding Agent needs a user decision", tool_result)
                return
        raise RuntimeError("Coding Agent reached the iteration limit without a reviewable result")

    async def _docker_availability(self, *, refresh: bool = False) -> DockerAvailability:
        """Refresh negative states immediately and successful probes at a short TTL.

        Docker Desktop can briefly reject its named pipe while it starts.  A
        failed probe therefore must never become an indefinitely cached
        "Docker is unavailable" state in the UI.
        """
        now = time.monotonic()
        stale = now - self._availability_checked_at >= _DOCKER_AVAILABILITY_TTL_SECONDS
        if (
            refresh
            or self._availability is None
            or not self._availability.sandbox_available
            or stale
        ):
            self._availability = await self.runner.availability()
            self._availability_checked_at = now
        return self._availability

    def _notify_review_ready(self, task: dict[str, object]) -> None:
        """Append and speak a single review-only Iris notification.

        The text is deterministic and contains no generated code.  The durable
        message is written before TTS is scheduled; ``client_message_id``
        makes worker recovery safe and prevents duplicate spoken notices.
        """
        if self.store is None:
            return
        session_id = str(task.get("session_id") or "").strip()
        task_id = str(task.get("id") or "").strip()
        if not session_id or not task_id:
            return
        message, created = self.store.append_message(
            role="assistant",
            content=self._review_ready_notification(task),
            input_mode="system",
            session_id=session_id,
            client_message_id=f"coding-review-ready:{task_id}",
            metadata={"kind": "coding_review_ready", "coding_task_id": task_id},
        )
        if not created:
            return
        self._speak_notification(session_id, message.content)
        if self.event_publisher is not None:
            self.event_publisher(
                "coding.review_notification",
                "info",
                "Coding Agent task is ready for review",
                {
                    "task_id": task_id,
                    "session_id": session_id,
                    "message_id": message.id,
                    "notification": message.content,
                },
            )

    def _notify_task_failed(self, task: dict[str, object]) -> None:
        """Tell the originating chat about a durable task failure once."""
        if self.store is None:
            return
        session_id = str(task.get("session_id") or "").strip()
        task_id = str(task.get("id") or "").strip()
        if not session_id or not task_id:
            return
        message, created = self.store.append_message(
            role="assistant",
            content=self._failed_task_notification(task),
            input_mode="system",
            session_id=session_id,
            client_message_id=f"coding-task-failed:{task_id}",
            metadata={"kind": "coding_task_failed", "coding_task_id": task_id},
        )
        if not created:
            return
        self._speak_notification(session_id, message.content)
        if self.event_publisher is not None:
            self.event_publisher(
                "coding.attention_notification",
                "warning",
                "Coding Agent task failed and needs attention",
                {
                    "task_id": task_id,
                    "session_id": session_id,
                    "message_id": message.id,
                    "notification": message.content,
                },
            )

    def _speak_notification(self, session_id: str, text: str) -> None:
        if self._notification_speaker is None:
            return
        try:
            self._notification_speaker(session_id, text)
        except Exception:
            # A notification must remain durable even if the optional voice
            # layer is momentarily unavailable. SpeechOrchestrator itself
            # handles asynchronous synthesis failures as recoverable events.
            logger.warning("Could not queue Coding Agent notification for speech", exc_info=True)

    @staticmethod
    def _review_ready_notification(task: dict[str, object]) -> str:
        objective = str(task.get("objective") or "")
        has_project_changes = bool(str(task.get("project_root") or ""))
        if any("А" <= char <= "я" or char in "Ёё" for char in objective):
            action = "нажми «Применить изменения»" if has_project_changes else "нажми «Подтвердить результат»"
            return (
                "Coding Agent закончил задачу. Результат готов к проверке: открой раздел Coding Agent, "
                f"посмотри изменения, логи и тесты, затем, если всё устраивает, {action}. "
                "Я ничего не применяю автоматически."
            )
        action = "choose \"Apply changes\"" if has_project_changes else "choose \"Confirm result\""
        return (
            "Coding Agent has finished the task. The result is ready for review: open the Coding Agent section, "
            f"check the changes, logs, and tests, then {action} if everything looks right. "
            "Nothing is applied automatically."
        )

    @staticmethod
    def _failed_task_notification(task: dict[str, object]) -> str:
        objective = str(task.get("objective") or "")
        if any("А" <= char <= "я" or char in "Ёё" for char in objective):
            return (
                "Coding Agent остановил задачу с ошибкой. Открой раздел Coding Agent: там доступны логи, "
                "команды и подробности ошибки. Рабочая папка задачи сохранена, ничего не применено автоматически."
            )
        return (
            "Coding Agent stopped the task with an error. Open the Coding Agent section for logs, commands, "
            "and error details. The task workspace is preserved and nothing was applied automatically."
        )

    async def _dispatch(self, task_id: str, sandbox: TaskSandbox, action: dict[str, object]) -> tuple[dict[str, object], str | None]:
        name = str(action["action"])
        try:
            if name == "list_files":
                files = sorted(sandbox.manifest["files"])
                return {"ok": True, "files": files[: self.settings.coding_max_files]}, None
            if name == "read_file":
                path = str(action.get("path", ""))
                return {"ok": True, "path": path, "content": sandbox.read_text(path)}, None
            if name == "write_file":
                path, content = str(action.get("path", "")), action.get("content")
                if not isinstance(content, str):
                    raise CodingPolicyError("write_file.content must be a string")
                sandbox.write_text(path, content)
                self.store.append_coding_event(task_id, "file.written", "info", "File edited in isolated workspace", {"path": path, "bytes": len(content.encode("utf-8"))})
                return {"ok": True, "path": path, "message": "File written"}, None
            if name == "delete_file":
                path = str(action.get("path", ""))
                sandbox.delete_file(path)
                self.store.append_coding_event(task_id, "file.deleted", "warning", "File deleted in isolated workspace", {"path": path})
                return {"ok": True, "path": path, "message": "File deleted"}, None
            if name == "run_command":
                result = await self.runner.run(task_id, sandbox.work_root, action.get("argv"))
                details = {
                    "ok": result.exit_code == 0 and not result.timed_out,
                    "command": result.command, "exit_code": result.exit_code,
                    "stdout": result.stdout, "stderr": result.stderr, "timed_out": result.timed_out,
                }
                self.store.append_coding_event(task_id, "command.completed", "info" if details["ok"] else "error", "Sandbox command completed", details)
                return details, None
            if name == "finish":
                result = {"summary": str(action.get("summary", ""))[:4000], "tests": str(action.get("tests", ""))[:4000]}
                return {"ok": True, "result": result}, "review_ready"
            if name == "wait_for_input":
                return {"ok": True, "question": str(action.get("question", ""))[:2000]}, "waiting_for_input"
            raise ValueError("Unknown coding action")
        except (CodingPolicyError, CommandPolicyError, OSError) as error:
            self.store.append_coding_event(task_id, "tool.rejected", "warning", "Coding tool action was rejected", {"action": name, "error": str(error)[:1000]})
            return {"ok": False, "error": str(error)}, None

    def _task_prompt(self, task: dict[str, object], sandbox: TaskSandbox) -> str:
        files = sorted(sandbox.manifest["files"])
        if sandbox.project_root is None:
            return (
                f"Objective:\n{task['objective']}\n\n"
                "This is a new, empty standalone workspace. Create the requested files here. "
                "Do not assume or mention files outside this workspace."
            )
        return (
            f"Objective:\n{task['objective']}\n\n"
            f"Approved files ({len(files)}):\n" + "\n".join(files[:500]) +
            "\n\nWork iteratively. Your edits remain isolated until the user explicitly applies a reviewed diff."
        )

    @staticmethod
    def _parse_action(content: str) -> dict[str, object]:
        value = json.loads(content)
        if not isinstance(value, dict) or not isinstance(value.get("action"), str):
            raise ValueError("Coding model response does not contain an action")
        return value

    def _project_root(self, requested_root: str | None = None) -> Path:
        allowed = self.settings.coding_allowed_project_paths
        selected = requested_root or self.runtime_settings.coding_project_root
        if selected:
            try:
                candidate = Path(selected).resolve()
            except OSError as error:
                raise ValueError("Invalid coding project root") from error
            if candidate in allowed:
                return candidate
            raise ValueError("Project root is not server-approved")
        return allowed[0]

    def _workspace_issue(self) -> str | None:
        workspace_root = self.settings.coding_workspace_path.resolve()
        for project_root in self.settings.coding_allowed_project_paths:
            try:
                workspace_root.relative_to(project_root)
                return "CODING_WORKSPACE_ROOT must be outside every allowed project root"
            except ValueError:
                try:
                    project_root.relative_to(workspace_root)
                    return "CODING_WORKSPACE_ROOT must be outside every allowed project root"
                except ValueError:
                    continue
        return None

    def _sandbox_from_task(self, task: dict[str, object]) -> TaskSandbox:
        project_root = str(task["project_root"])
        sandbox = TaskSandbox(
            self.settings, task_id=str(task["id"]),
            project_root=self._project_root(project_root) if project_root else None,
            workspace_name=str(task["workspace_name"]),
        )
        sandbox.open_existing(dict(task["base_manifest"]))
        return sandbox

    @staticmethod
    def _load_json(value: object) -> dict[str, object]:
        try:
            decoded = json.loads(str(value))
            return decoded if isinstance(decoded, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}
