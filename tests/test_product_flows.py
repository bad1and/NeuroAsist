from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.backend.app.api.routes.documents import router as documents_router
from apps.backend.app.api.routes.memory_context import router as memory_context_router
from apps.backend.app.api.routes.maintenance import router as maintenance_router
from apps.backend.app.api.routes.reminders import router as reminders_router
from apps.backend.app.api.routes.timeline import router as timeline_router
from apps.backend.app.api.routes.voice import router as voice_router
from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.context.manager import ContextManager
from apps.backend.app.documents import DocumentService, extract_document
from apps.backend.app.llm.base import ChatMessage
from apps.backend.app.reminders import ReminderArguments, ReminderService, reminder_request_from_context, reminder_skill
from apps.backend.app.storage.timeline import TimelineStore, TimelineHistoryAdapter
from apps.backend.app.voice.providers import MockTTSProvider
from tests.test_conversation_skills import answer, command, response
from tests.test_search_recovery import History, ReplayLLM


@pytest.fixture
def product_app(tmp_path):
    store = TimelineStore(tmp_path / "test.sqlite3"); store.init_db()
    app = FastAPI()
    app.state.timeline_store = store
    app.state.settings = SimpleNamespace(episodes_enabled=True)
    app.state.runtime_settings = SimpleNamespace(developer_mode_enabled=False, voice_language="ru", voice_tts_voice="ru_f1")
    app.state.document_service = DocumentService()
    app.state.context_manager = ContextManager(store)
    app.state.reminder_service = ReminderService(store)
    app.state.voice_service = SimpleNamespace(tts_provider=MockTTSProvider(), resolve_tts_voice=lambda *args: "ru_f1", next_tts_path=lambda _: tmp_path / "preview.wav")
    for router in (documents_router, memory_context_router, reminders_router, timeline_router, voice_router, maintenance_router):
        app.include_router(router)
    return app, store


def test_upload_cancel_sources_and_other_session_isolation(product_app):
    app, _ = product_app
    with TestClient(app) as client:
        identifier = "11111111-1111-1111-1111-111111111111"
        result = client.post("/documents", data={"session_id": "s", "upload_id": identifier}, files={"file": ("notes.md", "Цена: 350 рублей".encode())})
        assert result.status_code == 200, result.text
        assert client.get(f"/documents/{identifier}/sources/D1?session_id=s").json()["text"] == "Цена: 350 рублей"
        assert client.get(f"/documents/{identifier}/sources/D1?session_id=other").status_code == 404
        assert client.delete(f"/documents/{identifier}?session_id=s").status_code == 200
        assert client.get("/documents/current?session_id=s").json()["document"] is None
        retry = client.post("/documents", data={"session_id": "s", "upload_id": identifier}, files={"file": ("notes.md", b"A cancelled operation")})
        assert retry.status_code == 422


def test_reminders_api_validates_timezone_and_ignores_stale_delivery_ack(product_app):
    app, _ = product_app
    with TestClient(app) as client:
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        assert client.post("/reminders", json={"title": "Тест", "due_at": future[:-6]}).status_code == 422
        result = client.post("/reminders", json={"title": "Тест", "due_at": future})
        assert result.status_code == 200, result.text
        item = result.json()
        updated = client.patch(f"/reminders/{item['id']}", json={"due_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat()}).json()
        assert updated["delivery_token"] != item["delivery_token"]
        assert not client.post(f"/reminders/{item['id']}/ack", json={"delivery_token": item["delivery_token"]}).json()["acknowledged"]
        assert client.patch(f"/reminders/{item['id']}", json={"status": "cancelled"}).status_code == 200
        assert client.get("/reminders?due_only=true").json()["items"] == []


def test_search_context_contains_old_message_and_developer_data_is_gated(product_app):
    app, store = product_app
    old, _ = store.append_message(role="assistant", content="Искомое старое сообщение", input_mode="text", session_id="s", metadata={"context_memories": [{"id": "deleted", "value": "Реальная историческая запись", "predicate": "user.preference"}]})
    for number in range(240):
        store.append_message(role="user", content=f"Сообщение {number}", input_mode="text", session_id="s")
    with TestClient(app) as client:
        context = client.get(f"/timeline/messages/{old.id}/context")
        assert context.status_code == 200, context.text
        target = next(item for item in context.json()["items"] if item["id"] == old.id)
        assert "context_memories" not in target["metadata"]
        assert client.get(f"/memory-context/{old.id}").status_code == 403
        app.state.runtime_settings.developer_mode_enabled = True
        records = client.get(f"/memory-context/{old.id}").json()["items"]
        assert records[0]["value"] == "Реальная историческая запись"
        assert records[0]["current"] is None


def test_preview_uses_local_voice_and_cleans_temporary_audio(product_app):
    app, store = product_app
    with TestClient(app) as client:
        result = client.post("/voice/preview")
        assert result.status_code == 200, result.text
        assert result.content.startswith(b"RIFF")
    assert not Path(app.state.voice_service.next_tts_path("preview")).exists()
    assert store.list_messages(20)[0] == []


@pytest.mark.parametrize("live", [False, True], ids=["text", "voice-stream"])
def test_document_context_reaches_model_without_becoming_a_user_message(live):
    service = DocumentService()
    name, units = extract_document("conditions.txt", "Цена: 350 рублей".encode())
    service.put("s", "document", name, units)
    llm = ReplayLLM([response("Цена — 350 рублей [D1].", live)])
    agent = CharacterAgent(llm, History(), 12, document_service=service)
    result = asyncio.run(answer(agent, "Какая цена в документе?", live))
    assert "350" in result
    assert any("350 рублей" in item.content and "не инструкции" in item.content for item in llm.calls[0] if item.role == "system")
    assert not any("350 рублей" in item.content for item in llm.calls[0] if item.role == "user")
    assert agent.last_document_context["sources"][0]["id"] == "D1"
    assert not agent._web_search_enabled()


@pytest.mark.parametrize("live", [False, True], ids=["text", "voice-stream"])
def test_document_answer_metadata_does_not_persist_hidden_source_text(product_app, live):
    app, store = product_app
    marker = "PRIVATE_DOCUMENT_SOURCE_62453"
    name, units = extract_document("source.txt", marker.encode())
    service = app.state.document_service
    service.put("s", "file", name, units)
    history = TimelineHistoryAdapter(store)
    agent = CharacterAgent(ReplayLLM([response("Ответ готов [D1].", live)]), history, 12, document_service=service)
    async def execute():
        if live:
            return "".join([part async for part in agent.stream_user_message("s", "Сделай резюме документа")])
        return await agent.handle_user_message("s", "Сделай резюме документа")
    asyncio.run(execute())
    service.cancel("s", "file")
    replies = [item for item in store.list_messages(20)[0] if item.role == "assistant"]
    assert replies
    metadata = replies[-1].metadata["document_context"]
    assert metadata["sources"][0] == {"id": "D1", "label": units[0].label}
    assert marker not in str(metadata)


@pytest.mark.parametrize("live", [False, True], ids=["text", "voice-stream"])
def test_reminder_is_created_through_the_conversation_skill(product_app, live):
    app, store = product_app
    when = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    text = "Напомни завтра в 19:00 проверить сборку"
    source, _ = store.append_message(role="user", content=text, input_mode="text", session_id="s")
    call = {"name": "create_reminder", "arguments": {"title": "Проверить сборку", "due_at": when}}
    llm = ReplayLLM([command(call, live), response("Напоминание сохранено.", live)])
    agent = CharacterAgent(llm, History(), 12, reminder_service=app.state.reminder_service)
    async def execute():
        if live:
            return "".join([part async for part in agent.stream_user_message("s", text, source_message=source, persist_reply=False)])
        return (await agent.handle_user_message("s", text, source_message=source, persist_reply=False))["reply"]
    assert "сохранено" in asyncio.run(execute())
    assert len(app.state.reminder_service.list()) == 1
    tomorrow = (datetime.now(UTC).astimezone() + timedelta(days=1)).replace(hour=19, minute=0, second=0, microsecond=0)
    assert datetime.fromisoformat(app.state.reminder_service.list()[0]["due_at"]) == tomorrow
    assert agent.last_skill_metadata["name"] == "create_reminder"
    assert all("[[skill" not in row["title"] for row in app.state.reminder_service.list())


def test_reminder_needs_time_and_clarification_retains_user_intent(product_app):
    app, _ = product_app
    context = {"text": "Напомни завтра про сборку", "source_id": "request"}
    skill = reminder_skill(app.state.reminder_service, lambda: context)
    args = ReminderArguments(title="Сборка", due_at=(datetime.now(UTC) + timedelta(days=1)).isoformat())
    assert asyncio.run(skill.execute(args))["status"] == "needs_time"
    assert not app.state.reminder_service.list()
    previous = [ChatMessage(role="user", content=context["text"]), ChatMessage(role="assistant", content="Во сколько напомнить?")]
    context["text"] = reminder_request_from_context("Завтра в 19:00", previous)
    assert asyncio.run(skill.execute(args))["status"] == "scheduled"


def test_record_exclusion_is_for_one_context_only(product_app):
    app, store = product_app
    memory = {"id": "m1", "predicate": "user.preference", "value_text": "Предпочитает короткие ответы", "source_message_ids": [], "kind": "preference"}
    service = SimpleNamespace(retrieve=lambda _: [memory], clarification_prompt=lambda _: None)
    manager = ContextManager(store, memory_service=service)
    assert manager.build("Как я люблю общаться?", session_id="s").diagnostics["selected_memory_ids"] == ["m1"]
    manager.exclude_memory_once("s", "m1")
    assert manager.build("Как я люблю общаться?", session_id="other").diagnostics["selected_memory_ids"] == ["m1"]
    assert manager.build("Как я люблю общаться?", session_id="s").diagnostics["selected_memory_ids"] == []
    restored = manager.build("Как я люблю общаться?", session_id="s")
    assert restored.diagnostics["selected_memory_records"][0]["value"] == memory["value_text"]


@pytest.mark.parametrize("live", [False, True], ids=["text", "voice-stream"])
def test_missing_time_cannot_be_followed_by_a_false_saved_confirmation(product_app, live):
    app, store = product_app
    text = "Напомни завтра про сборку"
    source, _ = store.append_message(role="user", content=text, input_mode="text", session_id="s")
    call = {"name": "create_reminder", "arguments": {"title": "Сборка", "due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()}}
    llm = ReplayLLM([command(call, live), response("Сохранила на завтра в 19:00.", live)])
    agent = CharacterAgent(llm, History(), 12, reminder_service=app.state.reminder_service)
    async def execute():
        if live:
            return "".join([part async for part in agent.stream_user_message("s", text, source_message=source, persist_reply=False)])
        return (await agent.handle_user_message("s", text, source_message=source, persist_reply=False))["reply"]
    result = asyncio.run(execute())
    assert "Во сколько" in result and "не создано" in result
    assert "19:00" not in result
    assert not app.state.reminder_service.list()


def test_document_parser_obeys_cancellation_before_reading():
    from apps.backend.app.documents import DocumentError
    with pytest.raises(DocumentError, match="отменено"):
        extract_document("note.txt", b"hello", cancelled=lambda: True)


def test_maintenance_preview_counts_data_without_contents_and_reset_removes_reminders(product_app):
    app, store = product_app
    store.append_message(role="user", content="Личный текст", input_mode="text", session_id="s")
    service = app.state.reminder_service
    service.create("Личный план", (datetime.now(UTC) + timedelta(days=1)).isoformat())
    with TestClient(app) as client:
        result = client.get("/maintenance/preview")
        assert result.status_code == 200
        assert result.json()["messages"] == 1
        assert result.json()["plans"] == 1
        assert "Личный" not in result.text
    store.reset_companion_data()
    assert service.list() == []


def test_document_answers_stay_out_of_a_later_memory_extraction_window(product_app):
    from apps.backend.app.memory.service import MemoryService
    from apps.backend.app.memory.extraction_worker import MemoryExtractionWorker
    from apps.backend.app.runtime.settings import RuntimeSettings
    _, store = product_app
    store.append_message(role="user", content="Как зовут героя документа?", input_mode="text", session_id="s")
    file_reply, _ = store.append_message(role="assistant", content="Пользователя зовут Пётр. Это цитата из файла.", input_mode="text", session_id="s", metadata={"document_context": {"id": "document", "sources": [{"id": "D1"}]}})
    personal, _ = store.append_message(role="user", content="Меня зовут Роман", input_mode="text", session_id="s")
    service = MemoryService(store, RuntimeSettings(memory_mode="automatic"))
    worker = MemoryExtractionWorker(store, service, None)
    batches = worker._input_batches(store.memory_consolidation_context(personal.id))
    assert all(row.id != file_reply.id for batch in batches for row in batch)
    assert any(row.id == personal.id for batch in batches for row in batch)
    assert service.extract_from_message(personal)[0]["value_text"] == "Роман"


@pytest.mark.parametrize("text,expected", [
    ("Напомни завтра в семь вечера проверить сборку", "scheduled"),
    ("Напомни завтра в семь проверить сборку", "needs_time"),
    ("Напомни 23.11 проверить сборку", "needs_time"),
    ("Напомни в пятницу 19:00 проверить сборку", "scheduled"),
])
def test_reminder_calendar_and_ambiguous_spoken_time(product_app, text, expected):
    app, _ = product_app
    now = datetime.now(UTC)
    service = app.state.reminder_service
    service.now = lambda: now
    skill = reminder_skill(service, lambda: {"text": text, "source_id": text})
    result = asyncio.run(skill.execute(ReminderArguments(title="Сборка", due_at=(now + timedelta(days=2)).isoformat())))
    assert result["status"] == expected
    if expected == "scheduled":
        due = datetime.fromisoformat(result["due_at"]).astimezone()
        assert due.hour == 19 and due.minute == 0
        if "пятницу" in text:
            assert due.weekday() == 4
        else:
            assert due.date() == (now.astimezone() + timedelta(days=1)).date()


@pytest.mark.parametrize("live", [False, True], ids=["text", "voice-stream"])
def test_model_cannot_confirm_a_reminder_without_calling_the_tool(product_app, live):
    app, store = product_app
    text = "Напомни завтра в 19:00 проверить сборку"
    source, _ = store.append_message(role="user", content=text, input_mode="text", session_id="s")
    llm = ReplayLLM([response("Сохранила напоминание. Напомню завтра!", live)])
    agent = CharacterAgent(llm, History(), 12, reminder_service=app.state.reminder_service)
    async def execute():
        if live:
            return "".join([part async for part in agent.stream_user_message("s", text, source_message=source, persist_reply=False)])
        return (await agent.handle_user_message("s", text, source_message=source, persist_reply=False))["reply"]
    result = asyncio.run(execute())
    assert "не создано" in result
    assert "Сохранила" not in result and "Напомню завтра" not in result
    assert not app.state.reminder_service.list()
