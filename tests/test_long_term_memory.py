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


def test_ambient_live_speech_is_not_extracted_or_retrieved_as_memory(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    source, _ = store.append_message(
        role="user",
        content="Олег, запомни, кодовое число сорок два",
        input_mode="voice",
    )
    store.save_conversation_observation(
        message_id=source.id,
        session_id="live",
        turn_id="ambient-turn",
        utterance_id="ambient-utterance",
        generation=1,
        speaker_role="primary",
        speaker_confidence=0.9,
        addressedness=0.05,
        addressed_confidence=0.9,
        end_of_turn_confidence=1.0,
        significance=0.4,
        metadata={},
    )
    store.set_observation_decision(source.id, "observe", "other_person")

    assert service.extract_from_message(store.get_message(source.id)) == []
    legacy = store.create_memory({
        "scope": "user_profile",
        "kind": "decision",
        "subject": "user",
        "predicate": "code_number",
        "value_text": "сорок два",
        "importance": 0.8,
        "confidence": 0.9,
        "sensitivity": "normal",
        "status": "active",
        "source_message_ids": [source.id],
        "source_episode_id": source.episode_id,
        "extractor_version": "legacy-live",
    }, actor="extractor")

    assert store.get_memory(str(legacy["id"]))["status"] == "active"
    assert service.retrieve("сорок два") == []


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


def test_response_length_preference_replaces_previous_choice(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    short_message, _ = store.append_message(role="user", content="Я предпочитаю короткие ответы", input_mode="text")
    long_message, _ = store.append_message(role="user", content="Теперь я люблю длинные ответы", input_mode="text")

    short = service.apply_llm_candidates([
        {"kind": "preference", "subject": "user", "predicate": "prefers_response_length", "value_text": "короткие ответы", "importance": .7, "confidence": .95},
    ], short_message)[0]
    long = service.apply_llm_candidates([
        {"kind": "preference", "subject": "user", "predicate": "prefers_response_length", "value_text": "длинные ответы", "importance": .7, "confidence": .95},
    ], long_message)[0]

    assert store.get_memory(str(short["id"]))["status"] == "superseded"
    assert store.get_memory(str(long["id"]))["status"] == "active"
    active = store.list_memories(status="active")
    assert [(item["predicate"], item["value_text"]) for item in active] == [("prefers_response_length", "длинные ответы")]


def test_legacy_response_length_alias_is_repaired(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    source, _ = store.append_message(role="user", content="Я предпочитаю короткие ответы", input_mode="text")
    legacy = store.create_memory({
        "scope": "user_profile", "kind": "preference", "subject": "user", "predicate": "preferred",
        "value_text": "короткие ответы", "importance": .7, "confidence": .9, "sensitivity": "normal",
        "status": "active", "source_message_ids": [source.id], "source_episode_id": source.episode_id,
        "extractor_version": "deterministic-v2",
    }, actor="extractor")

    repaired = service.repair_legacy_response_length_preferences()

    assert len(repaired) == 1
    assert store.get_memory(str(legacy["id"]))["status"] == "superseded"
    active = store.list_memories(status="active")
    assert [(item["predicate"], item["value_text"]) for item in active] == [("prefers_response_length", "короткие ответы")]


def test_memory_policy_marks_allergy_sensitive_and_never_keeps_password(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    allergy, _ = store.append_message(role="user", content="У меня аллергия на цветение", input_mode="text")
    secret, _ = store.append_message(role="user", content="Мой пароль от почты 123456", input_mode="text")

    stored_allergy = service.apply_llm_candidates([
        {"kind": "constraint", "subject": "user", "predicate": "allergy", "value_text": "аллергия на цветение", "importance": .9, "confidence": .99, "sensitivity": "normal"},
    ], allergy)
    stored_secret = service.apply_llm_candidates([
        {"kind": "decision", "subject": "user", "predicate": "email_password", "value_text": "123456", "importance": .9, "confidence": .99, "sensitivity": "sensitive"},
    ], secret)
    disguised_secret = service.apply_llm_candidates([
        {"kind": "decision", "subject": "user", "predicate": "note", "value_text": "123456", "importance": .9, "confidence": .99, "sensitivity": "normal"},
    ], secret)

    assert stored_allergy[0]["status"] == "candidate"
    assert stored_allergy[0]["sensitivity"] == "sensitive"
    assert stored_secret == []
    assert disguised_secret == []


def test_ambiguous_social_relation_requires_review_but_direct_one_is_saved(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    ambiguous, _ = store.append_message(
        role="user", content="Моего друга Федю и мы разрабатываем тебя вдвоём", input_mode="text",
    )
    direct, _ = store.append_message(role="user", content="Лука — мой друг.", input_mode="text")

    ambiguous_memory = service.apply_llm_candidates([
        {"kind": "relationship", "subject": "user", "predicate": "has_friend", "value_text": "Федя", "importance": .8, "confidence": .99},
    ], ambiguous)[0]
    direct_memory = service.apply_llm_candidates([
        {"kind": "relationship", "subject": "user", "predicate": "has_friend", "value_text": "Лука", "importance": .8, "confidence": .99},
    ], direct)[0]

    assert ambiguous_memory["status"] == "candidate"
    assert direct_memory["status"] == "active"


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

    developers = service.extract_from_message(developer_message)
    generic = service.extract_from_message(generic_message)[0]

    assert {
        (item["slot_key"], item["object_key"], item["value_text"])
        for item in developers
    } == {
        ("assistant.developer", "person:олег", "Олег"),
        ("assistant.developer", "person:федя", "Федя"),
        ("assistant.developer_count", "count:2", "2"),
    }
    assert generic["value_text"] == "я люблю чай"


def test_direct_developer_wording_is_saved_immediately(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    message, _ = store.append_message(
        role="user", content="Твой разработчик это Олег и Федя", input_mode="text",
    )

    saved = service.extract_high_precision_from_message(message)

    assert [(item["slot_key"], item["value_text"]) for item in saved] == [
        ("assistant.developer", "Олег"),
        ("assistant.developer", "Федя"),
        ("assistant.developer_count", "2"),
    ]


def test_ambiguous_legacy_relationship_is_moved_to_review(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    source, _ = store.append_message(
        role="user", content="Я буду часто упоминать Федю", input_mode="text",
    )
    memory = store.create_memory({
        "scope": "relationship", "kind": "relationship", "subject": "user", "predicate": "has_friend",
        "value_text": "Федя", "importance": .8, "confidence": .99, "sensitivity": "normal",
        "status": "active", "source_message_ids": [source.id], "source_episode_id": source.episode_id,
        "extractor_version": "deepseek-character-v1",
    }, actor="extractor")

    repaired = service.repair_ambiguous_relationship_memories()

    assert [item["id"] for item in repaired] == [memory["id"]]
    assert store.get_memory(str(memory["id"]))["status"] == "candidate"


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
