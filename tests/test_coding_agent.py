import asyncio
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.backend import main as backend_main
from apps.backend.app.coding import runner as runner_module
from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.coding.orchestration import CodingBridge
from apps.backend.app.coding.runner import DockerAvailability, DockerSandboxRunner
from apps.backend.app.coding.sandbox import SnapshotLimitError, TaskSandbox
from apps.backend.app.coding.service import CodingAgentService
from apps.backend.app.core.config import ROOT_DIR, Settings
from apps.backend.app.llm.base import LLMResponse
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineHistoryAdapter, TimelineStore


def coding_settings(tmp_path: Path, project: Path) -> Settings:
    return Settings(
        deepseek_api_key="test-key",
        app_data_dir=str(tmp_path / "app-data"),
        sqlite_path=str(tmp_path / "timeline.sqlite3"),
        coding_workspace_root=str(tmp_path / "coding-workspaces"),
        coding_allowed_project_roots=str(project),
        coding_agent_enabled=True,
        log_to_file=False,
    )


def test_coding_defaults_are_portable_between_project_locations() -> None:
    settings = Settings(_env_file=None)

    assert settings.coding_docker_image == "neuroasist-coding"
    assert settings.coding_workspace_path == (ROOT_DIR.parent / "CodingAgentWorkspace")


def test_task_sandbox_copies_then_applies_only_after_explicit_review(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "answer.py"
    source.write_text("ANSWER = 1\n", encoding="utf-8")
    # Secrets and ignored build folders cannot reach the snapshot.
    (project / ".env").write_text("secret=never-copy", encoding="utf-8")
    settings = coding_settings(tmp_path, project)
    sandbox = TaskSandbox(settings, task_id="task-one", project_root=project, workspace_name="default")

    manifest = sandbox.create_snapshot()
    assert set(manifest["files"]) == {"answer.py"}
    sandbox.write_text("answer.py", "ANSWER = 2\n")

    assert source.read_text(encoding="utf-8") == "ANSWER = 1\n"
    assert [item.path for item in sandbox.changed_files()] == ["answer.py"]
    sandbox.apply_to_source()
    assert source.read_text(encoding="utf-8") == "ANSWER = 2\n"


def test_task_sandbox_blocks_apply_when_original_source_changed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "answer.py"
    source.write_text("ANSWER = 1\n", encoding="utf-8")
    sandbox = TaskSandbox(coding_settings(tmp_path, project), task_id="task-two", project_root=project, workspace_name="default")
    sandbox.create_snapshot()
    sandbox.write_text("answer.py", "ANSWER = 2\n")
    source.write_text("ANSWER = 3\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed since the task snapshot"):
        sandbox.apply_to_source()
    assert source.read_text(encoding="utf-8") == "ANSWER = 3\n"


def test_task_sandbox_reports_the_limit_that_was_exceeded(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "one.py").write_text("one = 1\n", encoding="utf-8")
    (project / "two.py").write_text("two = 2\n", encoding="utf-8")
    settings = coding_settings(tmp_path, project).model_copy(update={"coding_max_files": 1})
    sandbox = TaskSandbox(settings, task_id="task-limit", project_root=project, workspace_name="default")

    with pytest.raises(SnapshotLimitError, match="file limit"):
        sandbox.create_snapshot()


def test_standalone_workspace_never_copies_or_modifies_the_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "original.py"
    source.write_text("VALUE = 'original'\n", encoding="utf-8")
    workspace_root = tmp_path / "coding-work"
    settings = coding_settings(tmp_path, project).model_copy(update={"coding_workspace_root": str(workspace_root)})
    sandbox = TaskSandbox(settings, task_id="standalone", project_root=None, workspace_name="default")

    manifest = sandbox.create_empty_workspace()
    sandbox.write_text("hello_world.py", "print('hello')\n")

    assert manifest["files"] == {}
    assert (sandbox.work_root / "hello_world.py").is_file()
    assert not (sandbox.work_root / "original.py").exists()
    assert sandbox.apply_to_source()[0].path == "hello_world.py"
    assert source.read_text(encoding="utf-8") == "VALUE = 'original'\n"


def test_coding_tasks_are_durable_and_main_bridge_queues_explicit_request(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "module.py").write_text("x = 1\n", encoding="utf-8")
    settings = coding_settings(tmp_path, project)
    store = TimelineStore(settings.database_path)
    store.init_db()
    runtime = RuntimeSettings(coding_agent_enabled=True, coding_project_root=str(project))
    service = CodingAgentService(settings, runtime, store, lambda *_: None)
    bridge = CodingBridge(service)

    coordination = bridge.observe_user_message("session-a", "Исправь баг в Python файле и добавь тесты")

    assert coordination is not None
    tasks = store.list_coding_tasks()
    assert len(tasks) == 1
    assert tasks[0]["status"] == "pending"
    assert store.claim_coding_task_job() is not None
    store.append_coding_event(tasks[0]["id"], "command.completed", "info", "Sandbox command completed", {"exit_code": 0})
    loaded = store.get_coding_task(tasks[0]["id"])
    assert loaded is not None
    assert loaded["events"][-1]["payload"]["exit_code"] == 0

    queued = service.create_task("Добавь тест для Python модуля")
    cancelled = store.request_coding_cancel(str(queued["id"]))
    assert cancelled is not None
    assert cancelled["status"] == "cancelled"


def test_disabled_coding_agent_never_allows_iris_to_claim_delegation(tmp_path: Path) -> None:
    class NeverCalledProvider:
        calls = 0

        async def generate(self, _messages):
            self.calls += 1
            return LLMResponse(
                content='{"reply":"I sent it to Coding Agent","emotion":"happy","intent":"task_request"}',
                model="test",
            )

    project = tmp_path / "project"
    project.mkdir()
    settings = coding_settings(tmp_path, project)
    store = TimelineStore(settings.database_path)
    store.init_db()
    service = CodingAgentService(settings, RuntimeSettings(coding_agent_enabled=False), store, lambda *_: None)
    bridge = CodingBridge(service)
    provider = NeverCalledProvider()
    agent = CharacterAgent(provider, TimelineHistoryAdapter(store), history_limit=5, coding_bridge=bridge)

    result = asyncio.run(agent.handle_user_message("session", "Сможешь сейчас дать задачу агенту и создать Python файл?"))

    assert "выключен" in result["reply"]
    assert "не могу передать" in result["reply"]
    assert provider.calls == 0
    assert store.list_coding_tasks() == []


def test_enabling_agent_accepts_recent_deferred_task_without_model_hallucination(tmp_path: Path) -> None:
    class NeverCalledProvider:
        calls = 0

        async def generate(self, _messages):
            self.calls += 1
            raise AssertionError("A deferred Coding Agent task must not ask the main model for a reply")

    project = tmp_path / "project"
    project.mkdir()
    settings = coding_settings(tmp_path, project)
    store = TimelineStore(settings.database_path)
    store.init_db()
    runtime = RuntimeSettings(coding_agent_enabled=False, coding_auto_delegate=True)
    bridge = CodingBridge(CodingAgentService(settings, runtime, store, lambda *_: None))
    provider = NeverCalledProvider()
    agent = CharacterAgent(provider, TimelineHistoryAdapter(store), history_limit=5, coding_bridge=bridge)

    disabled = asyncio.run(agent.handle_user_message("session", "Передай агенту задачу: напиши тестовый Python файл"))
    runtime.coding_agent_enabled = True
    queued = asyncio.run(agent.handle_user_message("session", "Ирис, ну а сейчас"))

    assert "выключен" in disabled["reply"]
    assert "поставлена в очередь" in queued["reply"]
    assert provider.calls == 0
    tasks = store.list_coding_tasks()
    assert len(tasks) == 1
    assert tasks[0]["objective"] == "Передай агенту задачу: напиши тестовый Python файл"


def test_enabled_coding_request_is_queued_without_main_model_generating_code(tmp_path: Path) -> None:
    class NeverCalledProvider:
        calls = 0

        async def generate(self, _messages):
            self.calls += 1
            raise AssertionError("Coding delegation must not ask the main model for a code reply")

    project = tmp_path / "project"
    project.mkdir()
    settings = coding_settings(tmp_path, project)
    store = TimelineStore(settings.database_path)
    store.init_db()
    service = CodingAgentService(settings, RuntimeSettings(coding_agent_enabled=True), store, lambda *_: None)
    provider = NeverCalledProvider()
    agent = CharacterAgent(provider, TimelineHistoryAdapter(store), history_limit=5, coding_bridge=CodingBridge(service))

    result = asyncio.run(agent.handle_user_message("session", "Дай агенту задачу написать простой Python файл для теста"))

    assert "поставлена в очередь" in result["reply"]
    assert "Идентификатор" not in result["reply"]
    assert str(store.list_coding_tasks()[0]["id"]) not in result["reply"]
    assert "```" not in result["reply"]
    assert provider.calls == 0
    assert len(store.list_coding_tasks()) == 1


def test_natural_language_request_to_code_agent_is_queued_when_auto_delegate_is_enabled(tmp_path: Path) -> None:
    class NeverCalledProvider:
        calls = 0

        async def generate(self, _messages):
            self.calls += 1
            raise AssertionError("A Coding Agent delegation must not be answered by the main model")

    project = tmp_path / "project"
    project.mkdir()
    settings = coding_settings(tmp_path, project)
    store = TimelineStore(settings.database_path)
    store.init_db()
    runtime = RuntimeSettings(coding_agent_enabled=True, coding_auto_delegate=True)
    service = CodingAgentService(settings, runtime, store, lambda *_: None)
    provider = NeverCalledProvider()
    agent = CharacterAgent(provider, TimelineHistoryAdapter(store), history_limit=5, coding_bridge=CodingBridge(service))
    request = "Ирис, я хочу, чтобы агент накодил мне питоновский файл с простой пузырьковой сортировкой"

    result = asyncio.run(agent.handle_user_message("session", request))

    assert "поставлена в очередь" in result["reply"]
    assert "автоделегирование выключено" not in result["reply"]
    assert provider.calls == 0
    tasks = store.list_coding_tasks()
    assert len(tasks) == 1
    assert tasks[0]["objective"] == request


def test_task_request_with_a_result_file_is_queued_not_misread_as_status(tmp_path: Path) -> None:
    class NeverCalledProvider:
        calls = 0

        async def generate(self, _messages):
            self.calls += 1
            raise AssertionError("A concrete Coding Agent task must not be answered by the main model")

    project = tmp_path / "project"
    project.mkdir()
    settings = coding_settings(tmp_path, project)
    store = TimelineStore(settings.database_path)
    store.init_db()
    runtime = RuntimeSettings(coding_agent_enabled=True, coding_auto_delegate=True)
    service = CodingAgentService(settings, runtime, store, lambda *_: None)
    previous = service.create_task("Старый Python файл")
    store.update_coding_task(str(previous["id"]), status="applied")
    provider = NeverCalledProvider()
    agent = CharacterAgent(provider, TimelineHistoryAdapter(store), history_limit=5, coding_bridge=CodingBridge(service))
    request = (
        "Ирис, дай задачу Coding Agent: создай файл numbers.txt, запиши в него числа от 1 до 100, "
        "затем посчитай сумму и запиши результат в файл sum.txt"
    )

    result = asyncio.run(agent.handle_user_message("session", request))

    assert "поставлена в очередь" in result["reply"]
    assert "Активной задачи" not in result["reply"]
    assert provider.calls == 0
    assert store.list_coding_tasks()[0]["objective"] == request


def test_unspecified_new_task_request_never_claims_it_was_delegated(tmp_path: Path) -> None:
    class NeverCalledProvider:
        calls = 0

        async def generate(self, _messages):
            self.calls += 1
            raise AssertionError("An incomplete Coding Agent request must receive a factual forced reply")

    project = tmp_path / "project"
    project.mkdir()
    settings = coding_settings(tmp_path, project)
    store = TimelineStore(settings.database_path)
    store.init_db()
    service = CodingAgentService(
        settings, RuntimeSettings(coding_agent_enabled=True, coding_auto_delegate=True), store, lambda *_: None,
    )
    provider = NeverCalledProvider()
    agent = CharacterAgent(provider, TimelineHistoryAdapter(store), history_limit=5, coding_bridge=CodingBridge(service))

    result = asyncio.run(agent.handle_user_message("session", "Так новую задачу дай"))

    assert "Сформулируй задачу целиком" in result["reply"]
    assert "поставлена в очередь" not in result["reply"]
    assert provider.calls == 0
    assert store.list_coding_tasks() == []


def test_explicit_status_question_still_reports_the_latest_coding_task(tmp_path: Path) -> None:
    class NeverCalledProvider:
        calls = 0

        async def generate(self, _messages):
            self.calls += 1
            raise AssertionError("A Coding Agent status request must not be answered by the main model")

    project = tmp_path / "project"
    project.mkdir()
    settings = coding_settings(tmp_path, project)
    store = TimelineStore(settings.database_path)
    store.init_db()
    service = CodingAgentService(settings, RuntimeSettings(coding_agent_enabled=True), store, lambda *_: None)
    previous = service.create_task("Напиши Python файл")
    store.update_coding_task(str(previous["id"]), status="failed")
    provider = NeverCalledProvider()
    agent = CharacterAgent(provider, TimelineHistoryAdapter(store), history_limit=5, coding_bridge=CodingBridge(service))

    result = asyncio.run(agent.handle_user_message("session", "Какой результат последней задачи Coding Agent?"))

    assert "failed" in result["reply"]
    assert provider.calls == 0
    assert len(store.list_coding_tasks()) == 1


def test_disabled_agent_keeps_follow_up_code_detail_for_a_later_confirmation(tmp_path: Path) -> None:
    class NeverCalledProvider:
        calls = 0

        async def generate(self, _messages):
            self.calls += 1
            raise AssertionError("A deferred Coding Agent conversation must not generate code in chat")

    project = tmp_path / "project"
    project.mkdir()
    settings = coding_settings(tmp_path, project)
    store = TimelineStore(settings.database_path)
    store.init_db()
    runtime = RuntimeSettings(coding_agent_enabled=False, coding_auto_delegate=True)
    bridge = CodingBridge(CodingAgentService(settings, runtime, store, lambda *_: None))
    provider = NeverCalledProvider()
    agent = CharacterAgent(provider, TimelineHistoryAdapter(store), history_limit=5, coding_bridge=bridge)

    asyncio.run(agent.handle_user_message("session", "Можешь передать задачу агенту?"))
    deferred = asyncio.run(agent.handle_user_message("session", "Простой Python файл для теста"))
    runtime.coding_agent_enabled = True
    queued = asyncio.run(agent.handle_user_message("session", "А сейчас"))

    assert "выключен" in deferred["reply"]
    assert "поставлена в очередь" in queued["reply"]
    assert provider.calls == 0
    assert store.list_coding_tasks()[0]["objective"] == "Простой Python файл для теста"


def test_coding_task_result_is_reported_without_returning_code_to_chat(tmp_path: Path) -> None:
    class NeverCalledProvider:
        calls = 0

        async def generate(self, _messages):
            self.calls += 1
            raise AssertionError("Coding Agent status must not ask the main model to generate code")

    project = tmp_path / "project"
    project.mkdir()
    settings = coding_settings(tmp_path, project)
    store = TimelineStore(settings.database_path)
    store.init_db()
    service = CodingAgentService(settings, RuntimeSettings(coding_agent_enabled=True), store, lambda *_: None)
    task = service.create_task("Напиши Python файл")
    store.update_coding_task(
        str(task["id"]),
        status="review_ready",
        result={"summary": "Created hello.py with print('hello')"},
    )
    provider = NeverCalledProvider()
    agent = CharacterAgent(provider, TimelineHistoryAdapter(store), history_limit=5, coding_bridge=CodingBridge(service))

    result = asyncio.run(agent.handle_user_message("session", "Что выполнил агент?"))

    assert "review_ready" in result["reply"]
    assert "hello.py" not in result["reply"]
    assert "```" not in result["reply"]
    assert provider.calls == 0


def test_review_ready_coding_task_notifies_its_source_chat_once(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    settings = coding_settings(tmp_path, project)
    store = TimelineStore(settings.database_path)
    store.init_db()
    events: list[tuple[str, str, str, dict[str, object]]] = []
    spoken: list[tuple[str, str]] = []
    service = CodingAgentService(
        settings,
        RuntimeSettings(coding_agent_enabled=True),
        store,
        lambda event_type, level, message, metadata: events.append((event_type, level, message, metadata)),
        notification_speaker=lambda session_id, text: spoken.append((session_id, text)),
    )
    task = service.create_task("Напиши Python файл", session_id="chat-session")

    service._notify_review_ready(task)
    service._notify_review_ready(task)

    messages, _ = store.list_messages(limit=20, session_id="chat-session")
    notifications = [message for message in messages if message.metadata.get("kind") == "coding_review_ready"]
    assert len(notifications) == 1
    assert notifications[0].role == "assistant"
    assert "готов к проверке" in notifications[0].content
    assert "```" not in notifications[0].content
    assert spoken == [("chat-session", notifications[0].content)]
    assert events == [
        (
            "coding.review_notification",
            "info",
            "Coding Agent task is ready for review",
            {
                "task_id": task["id"],
                "session_id": "chat-session",
                "message_id": notifications[0].id,
                "notification": notifications[0].content,
            },
        )
    ]


def test_failed_coding_task_notifies_its_source_chat_once(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    settings = coding_settings(tmp_path, project)
    store = TimelineStore(settings.database_path)
    store.init_db()
    events: list[tuple[str, str, str, dict[str, object]]] = []
    spoken: list[tuple[str, str]] = []
    service = CodingAgentService(
        settings,
        RuntimeSettings(coding_agent_enabled=True),
        store,
        lambda event_type, level, message, metadata: events.append((event_type, level, message, metadata)),
        notification_speaker=lambda session_id, text: spoken.append((session_id, text)),
    )
    task = service.create_task("Проверь Python файл", session_id="chat-session")

    service._notify_task_failed(task)
    service._notify_task_failed(task)

    messages, _ = store.list_messages(limit=20, session_id="chat-session")
    notifications = [message for message in messages if message.metadata.get("kind") == "coding_task_failed"]
    assert len(notifications) == 1
    assert notifications[0].role == "assistant"
    assert "ошибкой" in notifications[0].content
    assert "```" not in notifications[0].content
    assert spoken == [("chat-session", notifications[0].content)]
    assert events == [
        (
            "coding.attention_notification",
            "warning",
            "Coding Agent task failed and needs attention",
            {
                "task_id": task["id"],
                "session_id": "chat-session",
                "message_id": notifications[0].id,
                "notification": notifications[0].content,
            },
        )
    ]


def test_coding_settings_and_task_api_contract(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "module.py").write_text("x = 1\n", encoding="utf-8")
    settings = Settings(
        deepseek_api_key="test-key",
        app_data_dir=str(tmp_path / "app-data"),
        sqlite_path=str(tmp_path / "timeline.sqlite3"),
        coding_workspace_root=str(tmp_path / "coding-workspaces"),
        coding_allowed_project_roots=str(project),
        log_to_file=False,
        voice_preload_stt_model=False,
        voice_preload_tts_model=False,
        voice_stt_provider="mock",
        voice_tts_provider="mock",
    )
    monkeypatch.setattr(backend_main, "get_settings", lambda: settings)

    with TestClient(backend_main.create_app()) as client:
        initial = client.get("/settings/public")
        assert initial.status_code == 200
        assert initial.json()["coding_agent_enabled"] is False
        assert initial.json()["coding_allowed_project_roots"] == [str(project.resolve())]

        patched = client.patch("/settings/runtime", json={
            "coding_agent_enabled": True,
            "coding_model": "deepseek-v4-pro",
            "coding_project_root": str(project),
            "coding_workspace_name": "qa-workspace",
        })
        assert patched.status_code == 200
        assert patched.json()["coding_model"] == "deepseek-v4-pro"

        session = client.post("/conversation/session")
        assert session.status_code == 200
        created = client.post("/coding/tasks", json={
            "objective": "Добавь тест к Python модулю",
            "session_id": session.json()["session_id"],
        })
        assert created.status_code == 201
        assert created.json()["status"] == "pending"
        assert created.json()["session_id"] == session.json()["session_id"]
        assert client.get("/coding/tasks").json()[0]["id"] == created.json()["id"]

        blocked_clear = client.delete("/coding/tasks")
        assert blocked_clear.status_code == 409
        client.app.state.timeline_store.update_coding_task(created.json()["id"], status="failed")
        cleared = client.delete("/coding/tasks")
        assert cleared.status_code == 200
        assert cleared.json() == {"removed_tasks": 1, "preserved_workspaces": True}
        assert client.get("/coding/tasks").json() == []


def test_docker_availability_accepts_successful_cli_and_image(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    runner = DockerSandboxRunner(coding_settings(tmp_path, project))

    async def successful_exec(argv: list[str], *, timeout: float) -> dict[str, object]:
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": False}

    monkeypatch.setattr(runner, "_exec", successful_exec)

    availability = asyncio.run(runner.availability())

    assert availability.cli_available is True
    assert availability.daemon_available is True
    assert availability.image_available is True
    assert availability.sandbox_available is True
    assert availability.reason is None


def test_runner_finds_per_user_docker_desktop_cli_when_path_is_stale(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    cli = tmp_path / "Programs" / "DockerDesktop" / "resources" / "bin" / "docker.exe"
    cli.parent.mkdir(parents=True)
    cli.touch()
    runner = DockerSandboxRunner(coding_settings(tmp_path, project))

    monkeypatch.setattr(runner_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(runner_module.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert runner._docker_executable() == str(cli)


def test_docker_availability_distinguishes_running_daemon_from_missing_image(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    runner = DockerSandboxRunner(coding_settings(tmp_path, project))

    async def image_missing(argv: list[str], *, timeout: float) -> dict[str, object]:
        exit_code = 1 if argv[1:3] == ["image", "inspect"] else 0
        return {"exit_code": exit_code, "stdout": "", "stderr": "", "timed_out": False}

    monkeypatch.setattr(runner, "_exec", image_missing)
    availability = asyncio.run(runner.availability())

    assert availability.cli_available is True
    assert availability.daemon_available is True
    assert availability.image_available is False
    assert availability.sandbox_available is False
    assert "is not built" in str(availability.reason)


def test_status_rechecks_a_transient_docker_failure_without_manual_refresh(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    settings = coding_settings(tmp_path, project)
    store = TimelineStore(settings.database_path)
    store.init_db()
    service = CodingAgentService(settings, RuntimeSettings(coding_agent_enabled=True), store, lambda *_: None)
    responses = iter([
        DockerAvailability(True, False, False, settings.coding_docker_image, "Docker daemon is unavailable"),
        DockerAvailability(True, True, True, settings.coding_docker_image),
    ])
    calls = 0

    async def availability() -> DockerAvailability:
        nonlocal calls
        calls += 1
        return next(responses)

    monkeypatch.setattr(service.runner, "availability", availability)

    first = asyncio.run(service.status())
    second = asyncio.run(service.status())

    assert calls == 2
    assert first["docker_daemon_available"] is False
    assert second["docker_daemon_available"] is True
    assert second["docker_image_available"] is True
    assert second["available"] is True


def test_docker_runner_uses_portable_writable_bind_mount(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = DockerSandboxRunner(coding_settings(tmp_path, project))
    captured: list[list[str]] = []

    async def successful_exec(argv: list[str], *, timeout: float) -> dict[str, object]:
        captured.append(argv)
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": False}

    monkeypatch.setattr(runner, "_exec", successful_exec)

    result = asyncio.run(runner.run("mount-test", workspace, ["python", "hello_world.py"]))

    assert result.exit_code == 0
    assert result.command == ["python3", "hello_world.py"]
    mount = captured[0][captured[0].index("--mount") + 1]
    assert mount == f"type=bind,src={workspace.resolve()},dst=/workspace"


def test_v09_repairs_pre_release_coding_task_table_with_v20_marker(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = TimelineStore(coding_settings(tmp_path, project).database_path)
    store.init_db()
    with sqlite3.connect(store._db_path) as connection:
        connection.execute("DROP TABLE coding_task_events")
        connection.execute("DROP TABLE coding_task_instructions")
        connection.execute("DROP TABLE coding_tasks")
        connection.execute(
            """CREATE TABLE coding_tasks (
                id TEXT PRIMARY KEY, session_id TEXT, source_message_id TEXT,
                status TEXT NOT NULL, objective TEXT NOT NULL, task_json TEXT NOT NULL,
                result_json TEXT, diagnostics_json TEXT, patch_text TEXT, workspace_dir TEXT,
                error_text TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                completed_at TEXT, applied_at TEXT
            )"""
        )
        connection.execute(
            """INSERT INTO coding_tasks VALUES (
                'legacy-task', NULL, NULL, 'succeeded', 'old task',
                '{"model":"deepseek-v4-pro"}', '{}', NULL, NULL, NULL, NULL,
                '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', NULL, NULL
            )"""
        )

    store.init_db()

    task = store.get_coding_task("legacy-task")
    assert task is not None
    assert task["model"] == "deepseek-v4-pro"
    assert task["status"] == "review_ready"
    with sqlite3.connect(store._db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(coding_tasks)")}
        assert {"model", "project_root", "workspace_name"}.issubset(columns)
