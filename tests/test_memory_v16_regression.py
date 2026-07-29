from __future__ import annotations

import asyncio
import json

from apps.backend.app.conversation.decision import ConversationDecisionEngine
from apps.backend.app.conversation.reflection import ReflectionService
from apps.backend.app.llm.base import LLMProvider, LLMResponse
from apps.backend.app.memory.extraction_worker import MemoryExtractionWorker
from apps.backend.app.memory.consolidation import ConsolidationResult
from apps.backend.app.memory.service import MemoryService
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineStore


class JsonProvider(LLMProvider):
    def __init__(self, content: str, model: str = "memory-v16-test") -> None:
        self.content = content
        self.model = model
        self.calls: list[list] = []

    async def generate(self, messages):
        self.calls.append(messages)
        return LLMResponse(content=self.content, model=self.model)


def _service(tmp_path):
    store = TimelineStore(tmp_path / "memory-v16.sqlite3")
    store.init_db()
    service = MemoryService(
        store,
        RuntimeSettings(memory_mode="automatic"),
        llm_extraction_enabled=True,
        async_extraction_enabled=True,
    )
    return store, service


def test_name_boundary_genre_and_affection_are_context_safe(tmp_path) -> None:
    store, service = _service(tmp_path)
    message, _ = store.append_message(
        role="user",
        content="очень приятно меня зовут федор как у тебя дела сейчас",
        input_mode="text",
    )
    saved = service.extract_high_precision_from_message(message)
    assert [(item["predicate"], item["value_text"]) for item in saved] == [("name", "Федор")]
    assert MemoryService._extract_name("меня зовут Анна Мария, рада знакомству") == "Анна Мария"
    assert MemoryService._extract_name("меня зовут Иван что ты любишь") == "Иван"
    assert MemoryService._extract_name("кстати ну как меня зовут ты же помнишь или нет") is None
    assert MemoryService._extract_name("ты помнишь как меня зовут или нет") is None

    genre, _ = store.append_message(
        role="user",
        content="я люблю очень играть в шутеры например дедлок валарант кс",
        input_mode="text",
    )
    assert service.extract_high_precision_from_message(genre)[0]["predicate"] == "likes_category"

    assert ConversationDecisionEngine.appraise(
        "я люблю играть в шутеры", "preference",
    ).event_kind == "neutral"
    assert ConversationDecisionEngine.appraise(
        "я тебя люблю", "affection",
    ).event_kind == "affection"
    assert ConversationDecisionEngine.appraise(
        "ну не репа а репо", "correction", previous_assistant_text="А вот репа — это игра?"
    ).event_kind == "iris_mistake_corrected"


def test_partial_output_keeps_valid_siblings_and_persists_diagnostics(tmp_path) -> None:
    store, service = _service(tmp_path)
    message, _ = store.append_message(role="user", content="Я люблю шутеры", input_mode="text")
    service.schedule_extraction(message)
    provider = JsonProvider(json.dumps({
        "facts": [
            {
                "kind": "interest", "subject": "user", "predicate": "likes_category",
                "value_text": "играть в шутеры", "importance": .7, "confidence": .95,
                "sensitivity": "normal", "source_message_ids": [message.id],
                "cardinality": "multi", "temporal_semantics": "atemporal",
            },
            {
                "kind": "interest", "subject": "user", "predicate": "likes",
                "value_text": "", "source_message_ids": [message.id],
            },
        ],
        "topics": [{
            "title": "Игровые предпочтения", "summary_text": "Пользователь любит шутеры.",
            "source_message_ids": [message.id],
        }],
        "commitments": [],
        "conflicts": [],
    }, ensure_ascii=False))

    assert asyncio.run(MemoryExtractionWorker(store, service, provider).run_once()) is True
    assert {item["predicate"] for item in store.list_memories(status="active")} == {"likes_category"}
    assert store.list_topics(status="active")[0]["title"] == "Игровые предпочтения"
    diagnostics = store.memory_diagnostics()
    assert diagnostics["runs"][0]["result"]["outcome"] == "partial"
    assert diagnostics["runs"][0]["result"]["discarded"] >= 1
    assert len(provider.calls) == 2
    assert "INVALID_JSON" in provider.calls[1][-1].content
    assert "JSON_SCHEMA" in provider.calls[1][-1].content
    # Simulate a lease recovery after the canonical transaction committed but
    # before the worker acknowledgement was durably observed.
    job_id = str(diagnostics["runs"][0]["id"])
    with store._connect() as connection:
        connection.execute(
            "UPDATE background_jobs SET status = 'pending', completed_at = NULL WHERE id = ?",
            (job_id,),
        )
    assert asyncio.run(MemoryExtractionWorker(store, service, provider).run_once()) is True
    assert len(provider.calls) == 2
    assert len(store.list_memories(status="active")) == 1
    assert len(store.list_topics(status="active")) == 1


def test_consolidation_coalesces_two_turns_and_correction_flushes_immediately(tmp_path) -> None:
    store, service = _service(tmp_path)
    first, _ = store.append_message(role="user", content="мне нравятся игры", input_mode="text")
    service.schedule_extraction(first)
    worker = MemoryExtractionWorker(
        store, service, JsonProvider('{"facts":[],"topics":[],"commitments":[],"conflicts":[]}'),
        respect_coalescing=True,
    )
    assert asyncio.run(worker.run_once()) is False

    second, _ = store.append_message(role="user", content="особенно кооперативные", input_mode="text")
    service.schedule_extraction(second)
    assert asyncio.run(worker.run_once()) is True
    diagnostics = store.memory_diagnostics(limit=10)
    assert any(run["result"].get("outcome") == "coalesced" for run in diagnostics["runs"])

    correction, _ = store.append_message(role="user", content="не репа а репо", input_mode="text")
    service.schedule_extraction(correction)
    delta = store.memory_consolidation_context(correction.id)
    assert [item.effective_content for item in delta] == ["особенно кооперативные", "не репа а репо"]
    assert asyncio.run(worker.run_once()) is True


def test_consolidation_rolls_back_all_sections_on_operational_failure(tmp_path, monkeypatch) -> None:
    store, service = _service(tmp_path)
    message, _ = store.append_message(role="user", content="я люблю шутеры", input_mode="text")
    result = ConsolidationResult.model_validate({
        "facts": [{
            "kind": "interest", "subject": "user", "predicate": "likes_category",
            "value_text": "играть в шутеры", "importance": .7, "confidence": .95,
            "sensitivity": "normal", "source_message_ids": [message.id],
            "cardinality": "multi", "temporal_semantics": "atemporal",
        }],
        "topics": [{
            "title": "Игровые предпочтения", "summary_text": "Любит шутеры",
            "source_message_ids": [message.id],
        }],
        "commitments": [], "conflicts": [],
    })

    def fail_topic(*_args, **_kwargs):
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(store, "create_topic", fail_topic)
    try:
        service.apply_consolidation(result, [message], model="test")
    except RuntimeError:
        pass
    else:
        raise AssertionError("operational failure must escape the transaction")
    assert store.list_memories(status="active") == []
    assert store.list_topics(status="active") == []


def test_invalid_question_name_and_assistant_only_facts_are_rejected(tmp_path) -> None:
    store, service = _service(tmp_path)
    question, _ = store.append_message(
        role="user", content="как меня зовут ты же помнишь или нет", input_mode="text",
    )
    assistant, _ = store.append_message(
        role="assistant", content="Я сейчас чиню космический корабль.", input_mode="text",
        reply_to_message_id=question.id,
    )
    store.create_memory({
        "scope": "user_profile", "kind": "identity", "subject": "user",
        "predicate": "name", "value_text": "Ты Же Помнишь", "status": "active",
        "source_message_ids": [question.id], "extractor_version": "deterministic-v3-high-precision",
    }, actor="test")
    store.create_memory({
        "scope": "user_profile", "kind": "state", "subject": "assistant",
        "predicate": "current_activity", "value_text": "чинит космический корабль",
        "status": "active", "source_message_ids": [assistant.id],
        "extractor_version": "consolidation-v11",
    }, actor="test")

    assert len(service.reject_invalid_interrogative_identity_memories()) == 1
    assert len(service.reject_assistant_only_profile_memories()) == 1
    assert store.list_memories(status="active") == []


def test_full_unpunctuated_acquaintance_creates_cards_topic_and_one_note(tmp_path) -> None:
    store, service = _service(tmp_path)
    turns = [
        ("user", "привет как твои дела и как тебя зовут"),
        ("assistant", "Привет! Я Iris, приятно познакомиться."),
        ("user", "очень приятно меня зовут федор как у тебя дела сейчас"),
        ("assistant", "Да дела нормально, Федор."),
        ("user", "я люблю очень играть в шутеры например дедлок валарант кс"),
        ("assistant", "Дедлок, Валарант и КС — отличная компания."),
        ("user", "ну не репа а репо"),
        ("assistant", "А, поняла: R.E.P.O., не репа."),
        ("user", "это кооперативный хоррор про роботов которые собирают предметы"),
    ]
    stored = []
    latest_user = None
    for role, text in turns:
        item, _ = store.append_message(
            role=role,
            content=text,
            input_mode="text",
            reply_to_message_id=latest_user.id if role == "assistant" and latest_user else None,
        )
        stored.append(item)
        if role == "user":
            latest_user = item
            service.extract_high_precision_from_message(item)
    final_reply, _ = store.append_message(
        role="assistant",
        content="Теперь ясно, почему тебе нравится R.E.P.O.",
        input_mode="text",
        reply_to_message_id=latest_user.id,
    )
    stored.append(final_reply)
    ids = {item.effective_content: item.id for item in stored}
    extraction = {
        "facts": [
            {"kind": "identity", "subject": "user", "predicate": "name", "value_text": "Федор", "importance": .9, "confidence": .99, "sensitivity": "normal", "source_message_ids": [ids["очень приятно меня зовут федор как у тебя дела сейчас"]], "cardinality": "single", "temporal_semantics": "atemporal"},
            {"kind": "interest", "subject": "user", "predicate": "likes_game", "value_text": "Deadlock", "importance": .65, "confidence": .95, "sensitivity": "normal", "source_message_ids": [ids["я люблю очень играть в шутеры например дедлок валарант кс"]], "cardinality": "multi", "temporal_semantics": "atemporal"},
            {"kind": "interest", "subject": "user", "predicate": "likes_game", "value_text": "Valorant", "importance": .65, "confidence": .95, "sensitivity": "normal", "source_message_ids": [ids["я люблю очень играть в шутеры например дедлок валарант кс"]], "cardinality": "multi", "temporal_semantics": "atemporal"},
            {"kind": "interest", "subject": "user", "predicate": "likes_game", "value_text": "Counter-Strike", "importance": .65, "confidence": .95, "sensitivity": "normal", "source_message_ids": [ids["я люблю очень играть в шутеры например дедлок валарант кс"]], "cardinality": "multi", "temporal_semantics": "atemporal"},
            {"kind": "interest", "subject": "user", "predicate": "likes_game", "value_text": "R.E.P.O.", "importance": .75, "confidence": .98, "sensitivity": "normal", "source_message_ids": [ids["ну не репа а репо"], ids["это кооперативный хоррор про роботов которые собирают предметы"]], "cardinality": "multi", "temporal_semantics": "atemporal"},
        ],
        "topics": [{"title": "Игровые предпочтения", "summary_text": "Любит шутеры и кооперативный хоррор R.E.P.O.", "source_message_ids": [ids["я люблю очень играть в шутеры например дедлок валарант кс"], ids["это кооперативный хоррор про роботов которые собирают предметы"]]}],
        "commitments": [], "conflicts": [],
    }
    service.schedule_extraction(latest_user)
    assert asyncio.run(MemoryExtractionWorker(
        store, service, JsonProvider(json.dumps(extraction, ensure_ascii=False)),
    ).run_once()) is True

    active = {(item["predicate"], item["value_text"]) for item in store.list_memories(status="active")}
    assert ("name", "федор") in active or ("name", "Федор") in active
    assert ("likes_category", "играть в шутеры") in active
    assert {value for predicate, value in active if predicate == "likes_game"} == {
        "Deadlock", "Valorant", "Counter-Strike", "R.E.P.O.",
    }
    assert len(store.list_topics(status="active")) == 1

    reflection_provider = JsonProvider(
        '{"text":"Мне запомнилось это знакомство как живое и искреннее. Я почувствовала интерес, когда разговор перешёл к любимым играм и уточнению моей ошибки."}',
        model="reflection-v16-test",
    )
    assert asyncio.run(ReflectionService(store, reflection_provider).run_once()) is True
    assert len(store.list_reflections("primary")) == 1
    assert asyncio.run(ReflectionService(store, reflection_provider).run_once()) is False
