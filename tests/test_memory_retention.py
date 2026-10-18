from __future__ import annotations

import asyncio
import json
from datetime import timedelta, timezone

import pytest

from apps.backend.app.context.manager import ContextManager
from apps.backend.app.llm.base import LLMProvider, LLMResponse
from apps.backend.app.memory.consolidation import ConsolidationResult
from apps.backend.app.memory.extraction_worker import MemoryExtractionWorker, MEMORY_EXTRACTION_MAX_INPUT_CHARS
from apps.backend.app.memory.service import MemoryService
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineStore


def setup(tmp_path, mode="balanced"):
    store = TimelineStore(tmp_path / "retention.sqlite3")
    store.init_db()
    service = MemoryService(store, RuntimeSettings(memory_mode=mode), llm_extraction_enabled=True)
    return store, service


def write(store, service, text, predicate, value, **extra):
    source, _ = store.append_message(role="user", content=text, input_mode="text")
    result = ConsolidationResult.model_validate({"facts": [{
        "kind": "fact", "predicate": predicate, "value_text": value,
        "confidence": .96, "importance": .5, "source_message_ids": [source.id], **extra,
    }]})
    service.apply_consolidation(result, [source])
    return source, result


@pytest.mark.parametrize("predicate,values", [
    ("learning", ["Rust", "Python"]), ("project", ["Iris", "Лаунчер"]),
    ("habit", ["гуляет по вечерам", "читает перед сном"]),
    ("current_goal", ["изучить Rust", "написать приложение"]),
    ("likes_category", ["шутеры", "стратегии"]),
])
def test_parallel_personal_facts_do_not_replace_each_other(tmp_path, predicate, values):
    store, service = setup(tmp_path)
    for value in values:
        write(store, service, f"Я сообщаю личный факт: {value}", predicate, value)
    assert {row["value_text"] for row in store.list_memories(status="active")} == set(values)
    assert all(row["expires_at"] is None for row in store.list_memories(status="active"))


@pytest.mark.parametrize("text", [
    "Изучаю Rust уже второй месяц", "Моя сестра Аня живёт в Туле",
    "Моё хобби — фотография", "По вторникам хожу на плавание",
    "Работаю посменно", "Терпеть не могу жару", "Каждый вечер гуляю с собакой",
    "Сын Даня с понедельника ходит в новую школу", "Нет, зови меня Алекс",
    "Исправь расписание: бассейн по средам",
])
def test_everyday_information_schedules_extraction(tmp_path, text):
    store, service = setup(tmp_path)
    source, _ = store.append_message(role="user", content=text, input_mode="text")
    assert service.schedule_extraction(source)


def test_saved_name_does_not_suppress_other_clauses(tmp_path):
    store, service = setup(tmp_path)
    source, _ = store.append_message(role="user", content="Меня зовут Роман, а по вторникам я хожу плавать", input_mode="text")
    assert service.extract_high_precision_from_message(source)
    assert service.schedule_extraction(source)


@pytest.mark.parametrize("predicate,slot", [
    ("user.preference", "user.preference"), ("user.note", "user.note"),
    ("relationship.friend", "user.relationship.friend"), ("device", "user.device"),
    ("user.family", "user.family"), ("personal_fact", "user.personal_fact"),
])
def test_aliases_and_everyday_slots_are_not_discarded(tmp_path, predicate, slot):
    store, service = setup(tmp_path)
    value = "Вася" if predicate == "relationship.friend" else "предпочитает ноутбук для работы"
    text = "Мой друг Вася" if predicate == "relationship.friend" else "Для работы предпочитаю ноутбук"
    write(store, service, text, predicate, value)
    assert store.list_memories(status="active")[0]["slot_key"] == slot


def test_expiration_does_not_erase_personal_facts_or_locked_state(tmp_path):
    store, service = setup(tmp_path)
    write(store, service, "Я изучаю Rust", "learning", "Rust")
    fact = store.list_memories(status="active")[0]
    store.update_memory(fact["id"], {"expires_at": "2000-01-01T00:00:00+00:00"})
    write(store, service, "Сейчас я бодрый", "current_mood", "бодрый", importance=.8)
    state = next(row for row in store.list_memories(status="active") if row["predicate"] == "mood")
    store.update_memory(state["id"], {"expires_at": "2000-01-01T00:00:00+00:00"})
    assert service.expire_due_memories() == 1
    assert store.get_memory(fact["id"])["status"] == "active"
    assert store.get_memory(state["id"])["status"] == "expired"


def test_correction_replaces_only_target_and_replay_cannot_resurrect_it(tmp_path):
    store, service = setup(tmp_path)
    first, old_result = write(store, service, "По вторникам плаваю", "schedule", "плавание по вторникам")
    old = store.list_memories(status="active")[0]
    write(store, service, "По субботам бегаю", "schedule", "бег по субботам")
    write(store, service, "Нет, теперь плаваю по средам", "schedule", "плавание по средам", supersedes_id=old["id"])
    service.apply_consolidation(old_result, [first])
    active = store.list_memories(status="active")
    assert {row["value_text"] for row in active} == {"плавание по средам", "бег по субботам"}
    assert store.get_memory(old["id"])["status"] == "superseded"


def test_old_single_slot_proposal_cannot_undo_newer_fact(tmp_path):
    store, service = setup(tmp_path)
    source, old = write(store, service, "Меня зовут Роман", "name", "Роман")
    write(store, service, "Нет, зови меня Алекс", "name", "Алекс")
    service.apply_consolidation(old, [source])
    assert [row["value_text"] for row in store.list_memories(status="active")] == ["Алекс"]


def test_retention_repair_is_idempotent_and_respects_user_deletion(tmp_path):
    store, service = setup(tmp_path)
    write(store, service, "Я изучаю Rust", "learning", "Rust")
    expired = store.list_memories(status="active")[0]
    store.update_memory(expired["id"], {"expires_at": "2000-01-01T00:00:00+00:00"}, actor="policy")
    store.set_memory_status(expired["id"], "expired", actor="policy", action="expired")
    write(store, service, "Для работы использую ноутбук", "device", "ноутбук для работы")
    deleted = next(row for row in store.list_memories(status="active") if row["predicate"] == "device")
    service.delete(deleted["id"])
    assert service.repair_v21_memory_retention()["restored"] == 1
    assert service.repair_v21_memory_retention()["idempotent_noop"]
    assert store.get_memory(expired["id"])["expires_at"] is None
    assert store.get_memory(deleted["id"])["status"] == "deleted"


class CaptureProvider(LLMProvider):
    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    async def generate(self, messages):
        self.calls.append(messages)
        if len(self.calls) == self.fail_at:
            raise RuntimeError("simulated provider failure")
        return LLMResponse(content='{"facts":[]}', model="retention-test")


def test_long_window_preserves_all_user_text_and_bounds_each_call(tmp_path):
    store, service = setup(tmp_path)
    originals = []
    for index in range(15):
        text = f"Мой личный факт {index}: " + (f"значимая-деталь-{index} " * 45)
        source, _ = store.append_message(role="user", content=text, input_mode="text")
        originals.append((source.id, text))
        store.append_message(role="assistant", content="Реакция Iris. " * 60, input_mode="text", reply_to_message_id=source.id)
    text = "Я изучаю Rust. " + "Деталь середины. " * 400 + "Конец сообщения."
    source, _ = store.append_message(role="user", content=text, input_mode="text")
    originals.append((source.id, text))
    service.schedule_extraction(source)
    provider = CaptureProvider()
    worker = MemoryExtractionWorker(store, service, provider)
    batches = worker._input_batches(store.memory_consolidation_context(source.id, None))
    for message_id, original in originals:
        pieces = [row.effective_content for batch in batches for row in batch if row.id == message_id]
        assert "".join(pieces) == original
    assert asyncio.run(worker.run_once())
    assert len(provider.calls) > 1
    for messages in provider.calls:
        assert sum(len(item.content) for item in messages) <= MEMORY_EXTRACTION_MAX_INPUT_CHARS
    combined = "\n".join(messages[-1].content for messages in provider.calls)
    for _, original in originals[:-1]:
        assert original in combined
    assert combined.count("Деталь середины.") == 400
    with store._connect() as connection:
        diagnostics = json.loads(connection.execute(
            "SELECT diagnostics_json FROM background_jobs WHERE type = 'memory_consolidation'"
        ).fetchone()[0])
    assert diagnostics["batch_count"] > 1


def test_later_batch_failure_does_not_advance_covered_cursor(tmp_path):
    store, service = setup(tmp_path)
    source, _ = store.append_message(role="user", content="Я изучаю Rust. " + "подробность " * 800, input_mode="text")
    service.schedule_extraction(source)
    provider = CaptureProvider(fail_at=2)
    assert asyncio.run(MemoryExtractionWorker(store, service, provider).run_once())
    with store._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM consolidation_runs").fetchone()[0] == 0
    assert len(store.memory_consolidation_context(source.id, None)) == 1


def test_sensitive_alias_needs_consent_and_secret_never_reaches_storage(tmp_path):
    store, service = setup(tmp_path)
    write(store, service, "У меня аллергия", "diagnosis", "аллергия")
    assert not store.list_memories(status="active")
    assert store.next_memory_clarification(None) is not None
    write(store, service, "Запомни пароль секрет123", "personal_fact", "пароль секрет123")
    assert not store.list_memories()


@pytest.mark.parametrize("text", [
    "Представь персонажа: у меня кот Барсик, я изучаю Rust",
    "Если бы меня звали Роман, я работал бы капитаном",
    "Не запоминай: меня зовут Роман и я изучаю Rust",
])
def test_local_fallback_does_not_turn_fiction_or_opt_out_into_memory(tmp_path, text):
    store, service = setup(tmp_path)
    source, _ = store.append_message(role="user", content=text, input_mode="text")
    assert service.extract_high_precision_from_message(source) == []
    assert service.extract_resilient_facts_from_message(source) == []
    assert store.list_memories() == []


def test_stale_unsaved_source_cannot_replace_current_single_fact(tmp_path):
    store, service = setup(tmp_path)
    old, _ = store.append_message(role="user", content="Я живу в Туле", input_mode="text")
    write(store, service, "Теперь я живу в Москве", "location", "Москва")
    service.apply_consolidation(ConsolidationResult.model_validate({"facts": [{
        "kind": "identity", "predicate": "location", "value_text": "Тула",
        "confidence": .99, "importance": .8, "source_message_ids": [old.id],
    }]}), [old])
    assert [row["value_text"] for row in store.list_memories(status="active")] == ["Москва"]


def test_retrieval_handles_inflected_family_question_without_semantic_index(tmp_path):
    store, service = setup(tmp_path)
    write(store, service, "Моя сестра Аня", "family", "сестра Аня")
    assert service.retrieve("Как зовут мою сестру?")[0]["value_text"] == "сестра Аня"


def test_context_trims_by_relevance_and_honors_configured_memory_budget(tmp_path, monkeypatch):
    store, service = setup(tmp_path)
    service._context_max_tokens = 85
    monkeypatch.setattr(service, "retrieve", lambda query: [
        {"id": "z-relevant", "predicate": "schedule", "value_text": "плавание по средам " * 8, "retrieval": {"score": .9}},
        {"id": "a-irrelevant", "predicate": "preference", "value_text": "другой факт " * 15, "retrieval": {"score": .1}},
    ])
    context = ContextManager(store, max_tokens=1000, memory_service=service).build("Какое у меня расписание?")
    assert context.diagnostics["selected_memory_ids"] == ["z-relevant"]
    assert "a-irrelevant" in context.diagnostics["dropped_memory_ids"]


def test_core_profile_is_available_for_unrelated_question(tmp_path):
    store, service = setup(tmp_path)
    write(store, service, "Меня зовут Роман", "name", "Роман")
    context = ContextManager(store, max_tokens=1000, memory_service=service).build("Привет")
    assert any('"value":"Роман"' in row.content for row in context.messages)


def test_large_profile_can_reinforce_low_ranked_fact_without_duplicate(tmp_path):
    store, service = setup(tmp_path)
    source, original = write(store, service, "Для работы использую ноутбук", "device", "рабочий ноутбук")
    for index in range(260):
        store.create_memory({
            "scope": "user_profile", "subject": "user", "kind": "preference",
            "predicate": "personal_fact", "slot_key": "user.personal_fact",
            "object_key": f"fact:{index}", "value_text": f"другой факт {index}",
            "importance": .95, "confidence": .96,
        }, actor="migration")
    service.apply_consolidation(original, [source])
    assert len(store.memory_slot_items("user.device")) == 1


def test_disabling_memory_cancels_queued_extraction_before_provider_call(tmp_path):
    store, service = setup(tmp_path)
    source, _ = store.append_message(role="user", content="Я изучаю Rust", input_mode="text")
    assert service.schedule_extraction(source)
    service._runtime.memory_mode = "off"
    provider = CaptureProvider()
    assert asyncio.run(MemoryExtractionWorker(store, service, provider).run_once())
    assert not provider.calls
    assert not store.list_memories()


@pytest.mark.parametrize("question,answer", [
    ("Где ты живёшь?", "В Туле"), ("Что ты изучаешь?", "Rust"),
    ("Сколько тебе лет?", "Двадцать пять"), ("Как зовут твою сестру?", "Аня"),
])
def test_short_answer_to_personal_question_is_not_missed(tmp_path, question, answer):
    store, service = setup(tmp_path)
    store.append_message(role="assistant", content=question, input_mode="text")
    source, _ = store.append_message(role="user", content=answer, input_mode="text")
    assert service.schedule_extraction(source)


def test_short_answer_to_unrelated_question_does_not_start_extraction(tmp_path):
    store, service = setup(tmp_path)
    store.append_message(role="assistant", content="Ты хочешь услышать шутку?", input_mode="text")
    source, _ = store.append_message(role="user", content="Да", input_mode="text")
    assert not service.schedule_extraction(source)


def test_fact_dense_window_splits_before_output_limit_can_drop_short_facts(tmp_path):
    store, service = setup(tmp_path)
    for index in range(15):
        source, _ = store.append_message(role="user", content=f"Мой отдельный личный факт {index}.", input_mode="text")
    worker = MemoryExtractionWorker(store, service, CaptureProvider())
    batches = worker._input_batches(store.memory_consolidation_context(source.id, None))
    assert len(batches) >= 3
    assert sum(len(batch) for batch in batches) == 15
    assert all(sum(row.role == "user" for row in batch) <= 6 for batch in batches)


def test_worker_losing_lease_does_not_write_or_acknowledge_new_owner(tmp_path):
    store, service = setup(tmp_path)
    source, _ = store.append_message(role="user", content="Я изучаю Rust", input_mode="text")
    service.schedule_extraction(source)

    class ReclaimedProvider(CaptureProvider):
        async def generate(self, messages):
            with store._connect() as connection:
                connection.execute("UPDATE background_jobs SET lease_owner = 'other-worker' WHERE type = 'memory_consolidation'")
            return LLMResponse(content=json.dumps({"facts": [{
                "kind": "skill", "predicate": "learning", "value_text": "Rust",
                "confidence": .96, "importance": .7, "source_message_ids": [source.id],
            }]}), model="test")

    assert asyncio.run(MemoryExtractionWorker(store, service, ReclaimedProvider()).run_once())
    assert not store.list_memories()
    with store._connect() as connection:
        row = connection.execute("SELECT status, lease_owner FROM background_jobs WHERE type = 'memory_consolidation'").fetchone()
    assert tuple(row) == ("running", "other-worker")


def test_editing_multi_value_fact_recomputes_key_and_merges_duplicate(tmp_path):
    store, service = setup(tmp_path)
    write(store, service, "Я изучаю Rust", "learning", "Rust")
    rust = store.memory_slot_items("user.learning")[0]
    write(store, service, "Я изучаю Python", "learning", "Python")
    service.edit(rust["id"], {"value_text": "Python"})
    assert [row["value_text"] for row in store.memory_slot_items("user.learning")] == ["Python"]


@pytest.mark.parametrize("predicate,value,query", [
    ("location", "Тула", "Где я живу?"),
    ("preference", "кофе", "Что я люблю?"),
    ("likes_game", "Minecraft", "Во что я играю?"),
    ("skill", "программирование", "Что я умею?"),
])
def test_profile_question_retrieval_works_without_shared_lexical_terms(tmp_path, predicate, value, query):
    store, service = setup(tmp_path)
    write(store, service, f"Личное сведение пользователя: {value}", predicate, value)
    assert service.retrieve(query)[0]["value_text"] == value


def test_relative_dates_receive_source_local_calendar_across_utc_midnight(tmp_path):
    store, service = setup(tmp_path)
    source, _ = store.append_message(
        role="user", content="Вчера получил водительские права", input_mode="text",
        created_at="2026-10-18T21:30:00+00:00",
    )
    worker = MemoryExtractionWorker(store, service, CaptureProvider(), local_timezone=timezone(timedelta(hours=3)))
    prompt, _ = worker._format_input(source.effective_content, [source])
    assert f"[{source.id} @2026-10-19T00:30:00+03:00] U:" in prompt
    assert source.created_at == "2026-10-18T21:30:00+00:00"


def test_legacy_deleted_alias_cannot_resurrect_from_same_source(tmp_path):
    store, service = setup(tmp_path)
    source, _ = store.append_message(role="user", content="Я люблю играть в шутеры", input_mode="text")
    old = store.create_memory({
        "scope": "user_profile", "kind": "interest", "subject": "user",
        "predicate": "likes_category", "slot_key": "user.likes_category",
        "object_key": "genre:shooter", "value_text": "играть в шутеры",
        "status": "active", "source_message_ids": [source.id],
    }, actor="extractor")
    service.delete(old["id"])
    assert service.extract_high_precision_from_message(source) == []
    assert not store.list_memories(status="active")
