from pathlib import Path

from fastapi.testclient import TestClient

from apps.backend import main as backend_main
from apps.backend.app.core.config import Settings
from apps.backend.app.memory.service import MemoryService
from apps.backend.app.context.manager import ContextManager
from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.llm.base import LLMResponse
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineStore


def _service(tmp_path: Path, mode: str = "automatic") -> tuple[TimelineStore, MemoryService]:
    store = TimelineStore(tmp_path / "memory.sqlite3")
    store.init_db()
    return store, MemoryService(store, RuntimeSettings(memory_mode=mode), sensitive_mode="ask")


def test_memory_has_user_source_and_deleted_memory_never_enters_context(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    message, _ = store.append_message(role="user", content="Меня зовут Роман", input_mode="text")

    created = service.extract_from_message(message)

    assert len(created) == 1
    memory = created[0]
    assert memory["status"] == "active"
    assert memory["source_message_ids"] == [message.id]
    assert service.retrieve("как меня зовут")[0]["id"] == memory["id"]
    context = ContextManager(store, max_tokens=200, memory_service=service).build("как меня зовут")
    assert context.diagnostics["selected_memory_ids"] == [memory["id"]]
    service.delete(str(memory["id"]))
    assert service.retrieve("как меня зовут") == []
    assert ContextManager(store, max_tokens=200, memory_service=service).build("как меня зовут").diagnostics["selected_memory_ids"] == []
    assert {item["action"] for item in store.memory_audit(str(memory["id"]))} >= {"candidate_created", "deleted"}


def test_memory_deduplicates_and_supersedes_conflicting_user_fact(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    first_message, _ = store.append_message(role="user", content="Меня зовут Роман", input_mode="text")
    first = service.extract_from_message(first_message)[0]
    duplicate_message, _ = store.append_message(role="user", content="Меня зовут Роман", input_mode="text")
    assert service.extract_from_message(duplicate_message)[0]["id"] == first["id"]

    changed_message, _ = store.append_message(role="user", content="Меня зовут Алекс", input_mode="text")
    changed = service.extract_from_message(changed_message)[0]

    assert store.get_memory(str(first["id"]))["status"] == "superseded"
    assert store.get_memory(str(changed["id"]))["supersedes_id"] == first["id"]
    assert service.retrieve("как меня зовут")[0]["value_text"] == "Алекс"


def test_balanced_memory_saves_valid_identity_and_returns_it_for_identity_variants(tmp_path: Path) -> None:
    store, service = _service(tmp_path, mode="balanced")
    message, _ = store.append_message(
        role="user", content="Запомни: меня зовут Роман Петров, приятно познакомиться.", input_mode="text",
    )

    memory = service.extract_from_message(message)[0]

    assert memory["predicate"] == "name"
    assert memory["value_text"] == "Роман Петров"
    assert memory["status"] == "active"
    for query in ("Ты помнишь моё имя?", "Как меня называть?", "Who am I?"):
        assert service.retrieve(query)[0]["id"] == memory["id"]
    assert service.memory_update(memory) == {
        "id": memory["id"], "status": "active", "action": "saved", "predicate": "name",
    }


def test_balanced_memory_keeps_preferences_and_sensitive_facts_for_review(tmp_path: Path) -> None:
    store, service = _service(tmp_path, mode="balanced")
    preference, _ = store.append_message(role="user", content="Я предпочитаю короткие ответы", input_mode="text")
    sensitive, _ = store.append_message(role="user", content="Запомни: у меня диагноз аллергия", input_mode="text")

    assert service.extract_from_message(preference)[0]["status"] == "candidate"
    assert service.extract_from_message(sensitive)[0]["status"] == "candidate"


def test_explicit_memory_is_normalized_and_developer_relationship_is_structured(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    developer_message, _ = store.append_message(
        role="user", content="Привет, запомни, что твоих разработчиков зовут Олег и Федя.", input_mode="text",
    )
    generic_message, _ = store.append_message(
        role="user", content="Запомни такой факт, что я люблю чай.", input_mode="text",
    )

    developer = service.extract_from_message(developer_message)[0]
    generic = service.extract_from_message(generic_message)[0]

    assert (developer["scope"], developer["kind"], developer["subject"], developer["predicate"], developer["value_text"]) == (
        "relationship", "relationship", "assistant", "developers", "Олег и Федя",
    )
    assert generic["value_text"] == "я люблю чай"


def test_explicit_vague_fact_is_not_saved(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    message, _ = store.append_message(role="user", content="Запомни: это, он очень плохой человек.", input_mode="text")
    assert service.extract_from_message(message) == []


def test_name_extraction_rejects_invalid_value_and_repairs_legacy_candidate_from_source(tmp_path: Path) -> None:
    store, service = _service(tmp_path, mode="balanced")
    invalid, _ = store.append_message(role="user", content="Меня зовут 123", input_mode="text")
    source, _ = store.append_message(
        role="user", content="Меня зовут Роман, а ещё я люблю игры", input_mode="text",
    )
    legacy = store.create_memory({
        "scope": "user_profile", "kind": "identity", "subject": "user", "predicate": "name",
        "value_text": "Роман а ещё я люблю игры", "importance": .9, "confidence": .75,
        "status": "candidate", "source_message_ids": [source.id], "source_episode_id": source.episode_id,
        "extractor_version": "deterministic-v1",
    }, actor="extractor")

    assert service.extract_from_message(invalid) == []
    repaired = service.repair_legacy_identity_candidates()

    assert len(repaired) == 1
    assert repaired[0]["value_text"] == "Роман"
    assert repaired[0]["status"] == "active"
    assert store.get_memory(str(legacy["id"]))["status"] == "superseded"
    assert service.repair_legacy_identity_candidates() == []


def test_sensitive_and_ask_mode_candidates_require_confirmation(tmp_path: Path) -> None:
    store, automatic = _service(tmp_path, mode="automatic")
    sensitive, _ = store.append_message(role="user", content="Запомни: у меня диагноз аллергия", input_mode="text")
    candidate = automatic.extract_from_message(sensitive)[0]
    assert candidate["status"] == "candidate"
    assert automatic.retrieve("диагноз") == []
    automatic.confirm(str(candidate["id"]))
    assert automatic.retrieve("диагноз")[0]["id"] == candidate["id"]

    ask_message, _ = store.append_message(role="user", content="Я предпочитаю короткие ответы", input_mode="text")
    ask = MemoryService(store, RuntimeSettings(memory_mode="ask"))
    assert ask.extract_from_message(ask_message)[0]["status"] == "candidate"


def test_memory_routes_enforce_sources_and_keep_memory_clear_separate(monkeypatch, tmp_path: Path) -> None:
    settings = Settings(
        sqlite_path=str(tmp_path / "api.sqlite3"), log_to_file=False,
        voice_preload_stt_model=False, voice_preload_tts_model=False,
        voice_stt_provider="mock", voice_tts_provider="mock",
    )
    monkeypatch.setattr(backend_main, "get_settings", lambda: settings)
    with TestClient(backend_main.create_app()) as client:
        message = client.post("/timeline/messages", json={"role": "user", "content": "Источник", "input_mode": "text"}).json()["message"]
        rejected = client.post("/memory", json={"predicate": "note", "value_text": "Без источника"})
        created = client.post("/memory", json={"predicate": "note", "value_text": "С источником", "source_message_ids": [message["id"]]})
        memory_id = created.json()["memory"]["id"]
        assert client.post(f"/memory/{memory_id}/reindex").status_code == 404
        assert client.post("/memory/reindex").json()["indexed"] == 1
        explanation = client.get("/memory/retrieval/explain", params={"q": "источником"})
        assert explanation.status_code == 200
        assert explanation.json()["items"][0]["id"] == memory_id
        assert client.post("/memory/clear", json={}).json()["deleted"] == 1
        assert client.get("/timeline/messages?limit=10").json()["items"]

    assert rejected.status_code == 422
    assert created.status_code == 200


def test_incognito_skips_timeline_and_memory_writes(tmp_path: Path) -> None:
    class Provider:
        async def generate(self, _messages):
            return LLMResponse(content='{"reply":"Поняла","emotion":"neutral","intent":"casual_chat"}', model="test")

    store = TimelineStore(tmp_path / "incognito.sqlite3")
    store.init_db()
    runtime = RuntimeSettings(memory_mode="automatic", memory_incognito=True)
    service = MemoryService(store, runtime)
    from apps.backend.app.storage.timeline import TimelineHistoryAdapter
    import asyncio

    agent = CharacterAgent(Provider(), TimelineHistoryAdapter(store), history_limit=5, memory_service=service)
    asyncio.run(agent.handle_user_message("default", "Запомни: секретный разговор"))

    assert store.list_messages(20)[0] == []
    assert store.list_memories(limit=20) == []


def test_agent_persists_user_memory_before_llm_failure(tmp_path: Path) -> None:
    class FailingProvider:
        async def generate(self, _messages):
            raise RuntimeError("provider unavailable")

    store = TimelineStore(tmp_path / "failure.sqlite3")
    store.init_db()
    runtime = RuntimeSettings(memory_mode="balanced")
    service = MemoryService(store, runtime)
    from apps.backend.app.storage.timeline import TimelineHistoryAdapter
    import asyncio

    agent = CharacterAgent(FailingProvider(), TimelineHistoryAdapter(store), history_limit=5, memory_service=service)
    try:
        asyncio.run(agent.handle_user_message("default", "Меня зовут Роман"))
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected provider failure")

    assert store.list_messages(10)[0][0].content == "Меня зовут Роман"
    assert service.retrieve("Ты помнишь моё имя?")[0]["value_text"] == "Роман"
    assert agent.last_memory_updates[0]["action"] == "saved"
