import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from apps.backend.app.api.routes import chat, memory
from apps.backend.app.conversation.turn_coordinator import ConversationTurnCoordinator
from apps.backend.app.schemas.chat import ChatRequest
from apps.backend.app.storage.timeline import TimelineStore


def test_memory_pages_filter_before_limit_and_expose_every_record(tmp_path: Path):
    store = TimelineStore(tmp_path / "memory.sqlite3")
    store.init_db()
    for index in range(205):
        store.create_memory({
            "scope": "user_profile", "kind": "preference", "subject": "user",
            "predicate": f"record_{index}", "value_text": f"value {index}",
            "importance": 0.9 if index < 100 else 0.3,
            "status": "deleted" if index < 100 else "active",
        }, actor="user")
    app = FastAPI()
    app.include_router(memory.router)
    app.state.memory_service = SimpleNamespace(store=store)
    with TestClient(app) as client:
        first = client.get("/memory?status=active").json()
        second = client.get(f"/memory?status=active&offset={first['next_offset']}").json()
        assert len(first["items"]) == 100
        assert len(second["items"]) == 5
        assert second["next_offset"] is None
        assert len({item["id"] for item in first["items"] + second["items"]}) == 105
        archive = client.get("/memory?status=archive").json()
        assert len(archive["items"]) == 100
        assert {item["status"] for item in archive["items"]} == {"deleted"}
        assert client.get("/memory?status=active&q=value&offset=100").json()["items"] == second["items"]
        assert client.get("/memory?offset=-1").status_code == 422


@pytest.mark.parametrize("terminal", [None, "completed", "interrupted", "failed"])
def test_live_retry_returns_the_original_reply_without_starting_generation(tmp_path, monkeypatch, terminal):
    async def scenario():
        store = TimelineStore(tmp_path / "chat.sqlite3")
        store.init_db()
        coordinator = ConversationTurnCoordinator(store)
        accepted = await coordinator.accept_user_turn(session_id="chat", content="hello", input_mode="text", client_message_id="client-1", utterance_id="original-stream")
        lease = await coordinator.begin_assistant(accepted, metadata={"voice_request_id": "original-request"})
        if terminal:
            store.finish_assistant_turn(session_key="chat", assistant_message_id=lease.assistant_message_id, generation=lease.generation, content="saved answer", status=terminal)
        manager = SimpleNamespace(connected=lambda _: True, start=AsyncMock())
        state = SimpleNamespace(
            settings=SimpleNamespace(voice_tts_enabled=True, chat_history_limit=20),
            voice_session_manager=manager, timeline_store=store, turn_coordinator=coordinator,
            history=None, context_manager=None, memory_service=None,
            event_bus=SimpleNamespace(publish=Mock()),
            runtime_settings=SimpleNamespace(personality="default", voice_language="ru", voice_tts_voice=None),
            voice_service=SimpleNamespace(resolve_tts_voice=lambda *_: "test"),
        )
        monkeypatch.setattr(chat, "require_active_session_async", AsyncMock())
        monkeypatch.setattr(chat, "DeepSeekProvider", Mock())
        monkeypatch.setattr(chat, "CharacterAgent", Mock())
        request = SimpleNamespace(app=SimpleNamespace(state=state))
        payload = ChatRequest(session_id="chat", message="hello", client_message_id="client-1")
        result = await chat.live_chat(payload, request)
        assert result.replayed
        assert result.utterance_id == "original-stream"
        assert result.assistant_message_id == lease.assistant_message_id
        assert result.status == (terminal or "streaming")
        assert result.reply == ("saved answer" if terminal else "")
        manager.start.assert_not_called()
        assert len(store.list_messages(20)[0]) == 2
        if terminal is None:
            with pytest.raises(HTTPException) as raised:
                await chat.chat(payload, request)
            assert raised.value.status_code == 409
        else:
            batch = await chat.chat(payload, request)
            assert batch.reply == "saved answer"
            assert batch.status == terminal
    asyncio.run(scenario())
