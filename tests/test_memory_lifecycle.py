from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

import pytest

from apps.backend.app.context.manager import ContextManager
from apps.backend.app.memory.consolidation import ConsolidationResult
from apps.backend.app.memory.extraction_worker import MemoryExtractionWorker
from apps.backend.app.memory.lifecycle import freshness, session_style_prompt, style_request
from apps.backend.app.memory.service import MemoryService
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineStore


@pytest.fixture
def memory(tmp_path):
    store = TimelineStore(tmp_path / "lifecycle.sqlite3")
    store.init_db()
    return store, MemoryService(store, RuntimeSettings(memory_mode="balanced"), llm_extraction_enabled=True)


def propose(store, service, text, value, predicate="prefers_response_length", session="a", **extra):
    source, _ = store.append_message(role="user", content=text, input_mode="text", session_id=session)
    fact = {"kind": "preference", "predicate": predicate, "value_text": value,
            "importance": .7, "confidence": .96, "source_message_ids": [source.id], **extra}
    result = ConsolidationResult.model_validate({"facts": [fact]})
    service.apply_consolidation(result, [source])
    return source, result


@pytest.mark.parametrize("text,scope", [
    ("Говори короче", "session"), ("Отвечай кратко сегодня", "session"),
    ("В этом диалоге всегда отвечай коротко", "session"),
    ("На этот раз объясни подробно", "turn"), ("В этом ответе пиши коротко", "turn"),
    ("Я предпочитаю короткие ответы", "durable"), ("На будущее отвечай подробно", "durable"),
    ("Когда разбираем код, отвечай подробно", "conditional"),
    ("Говори короче. Я всегда пью чай", "session"),
    ("Please answer briefly", "session"), ("I prefer short answers", "durable"),
    ("Мне нравятся короткие ответы", "durable"),
    ("Мне удобнее, когда ответы короткие и по делу", "durable"),
    ("Меня раздражают длинные ответы", "durable"),
])
def test_style_scope_depends_on_source_meaning(text, scope):
    assert style_request(text).scope == scope


@pytest.mark.parametrize("text", [
    "Почему ты говоришь коротко?", "Ты всегда говоришь кратко",
    'Он сказал: «Говори короче»', 'Переведи «отвечай кратко»',
    "Я люблю короткие рассказы", "Какие короткие ответы бывают?",
    "Я когда-то просил говорить короче", "Раньше я просил короткие ответы",
])
def test_style_mentions_do_not_become_instructions(text):
    assert style_request(text) is None


@pytest.mark.parametrize("predicate", ["prefers_response_length", "preference", "note", "personal_fact", "constraint"])
def test_one_time_request_cannot_be_laundered_into_any_profile_slot(memory, predicate):
    store, service = memory
    propose(store, service, "Говори короче", "Короткие ответы", predicate)
    assert not store.list_memories(status="active")
    assert not service.core_profile()


def test_local_request_does_not_replace_explicit_global_preference(memory):
    store, service = memory
    propose(store, service, "Обычно предпочитаю подробные ответы", "Подробные ответы")
    global_memory = service.core_profile()[0]
    propose(store, service, "На этот раз говори короче", "Короткие ответы", memory_scope="durable")
    assert service.core_profile()[0]["id"] == global_memory["id"]
    assert store.get_memory(global_memory["id"])["status"] == "active"


def test_condition_survives_extractor_dropping_it_and_never_replaces_global(memory):
    store, service = memory
    propose(store, service, "Всегда отвечай кратко", "Короткие ответы")
    propose(store, service, "Когда разбираем код, отвечай подробно", "Подробные ответы")
    active = store.list_memories(status="active")
    assert len(active) == 2
    conditional = next(item for item in active if item["slot_key"] == "user.preference")
    assert "разбираем код" in conditional["value_text"]
    assert conditional["metadata"]["lifecycle"]["scope"] == "conditional"
    assert service.core_profile()[0]["value_text"] == "Короткие ответы"
    assert conditional["id"] in {item["id"] for item in service.retrieve("Помоги с кодом")}
    assert conditional["id"] not in {item["id"] for item in service.retrieve("Какие ответы ты даёшь о путешествиях?")}
    assert conditional["id"] in {item["id"] for item in service.retrieve("Какие у меня предпочтения?")}


def test_session_style_survives_compaction_but_not_a_new_session(memory):
    store, service = memory
    store.append_message(role="user", content="Говори короче", input_mode="text", session_id="a")
    for index in range(20):
        store.append_message(role="user", content=f"Тема номер {index}", input_mode="text", session_id="a")
    source, _ = store.append_message(role="user", content="Что дальше?", input_mode="text", session_id="a")
    built = ContextManager(store, memory_service=service, recent_turns=2).build(source.content, session_id="a", current_message_id=source.id)
    assert any("Отвечай кратко, сохраняя" in item.content for item in built.messages)
    other, _ = store.append_message(role="user", content="Что дальше?", input_mode="text", session_id="b")
    built = ContextManager(store, memory_service=service).build(other.content, session_id="b", current_message_id=other.id)
    assert not any("Текущий запрос пользователя о стиле:" in item.content for item in built.messages)


def test_one_answer_exception_does_not_overwrite_session_style():
    turns = [{"content": "Говори короче"}, {"content": "В этом ответе объясни подробно"}]
    assert "Отвечай подробно" in session_style_prompt(turns, turns[-1]["content"])
    assert "Отвечай кратко" in session_style_prompt(turns, "Теперь ещё вопрос")
    assert "обычную уместную" in session_style_prompt(turns, "Отвечай теперь обычно")
    assert session_style_prompt([{"content": "Я предпочитаю короткие ответы"}],
                                "Я тогда имел в виду только тот ответ") is None


def test_ambient_style_is_not_a_user_instruction():
    assert session_style_prompt([{"content": "Говори короче", "dialogue_scope": "ambient"}], "Привет") is None


def test_current_ambient_message_cannot_become_a_style_request(memory):
    store, service = memory
    source, _ = store.append_message(role="user", content="Говори короче", input_mode="voice", metadata={"dialogue_scope": "ambient"})
    built = ContextManager(store, memory_service=service).build(source.content, current_message_id=source.id)
    assert not any("Текущий запрос пользователя о стиле:" in item.content for item in built.messages)


@pytest.mark.parametrize("text", ["Не отвечай длинно", "Перестань говорить подробно", "Не люблю длинные ответы"])
def test_negative_style_request_preserves_direction(text):
    assert style_request(text).style == "short"


def test_local_style_cannot_create_a_topic_or_open_loop_or_trigger_a_model_call(memory):
    store, service = memory
    source, _ = store.append_message(role="user", content="Пожалуйста, сейчас говори короче", input_mode="text")
    assert not service.schedule_extraction(source)
    counts = service.apply_consolidation(ConsolidationResult.model_validate({
        "facts": [{"kind": "goal", "predicate": "current_goal", "value_text": "Краткость общения", "importance": .8, "confidence": .99, "source_message_ids": [source.id]}],
        "topics": [{"title": "Краткие ответы", "summary_text": "Пользователь хочет краткость", "source_message_ids": [source.id]}],
        "commitments": [{"title": "Всегда отвечать кратко", "source_message_ids": [source.id]}],
    }), [source])
    assert counts == {"facts": 0, "topics": 0, "commitments": 0, "conflicts": 0}


def test_local_style_does_not_suppress_other_facts_in_same_turn(memory):
    store, service = memory
    propose(store, service, "Говори короче. Я изучаю Rust", "Rust", "learning")
    assert store.list_memories(status="active")[0]["value_text"] == "Rust"


def test_two_different_preferences_in_one_source_keep_their_own_scope(memory):
    store, service = memory
    text = "Обычно отвечай кратко. Когда разбираем код, отвечай подробно"
    propose(store, service, text, "Короткие ответы")
    propose(store, service, text, "Когда разбираем код: подробные ответы", memory_scope="conditional")
    assert service.core_profile()[0]["value_text"] == "Короткие ответы"
    assert len(store.list_memories(status="active")) == 2


def test_explicit_restore_of_retired_preference_is_authoritative(memory):
    store, service = memory
    item = legacy_style(store, "Говори короче")
    service.repair_v22_memory_lifecycle()
    restored = service.restore(item["id"])
    assert restored["metadata"]["lifecycle"]["scope"] == "durable"
    assert service.core_profile()[0]["id"] == item["id"]


def test_natural_scope_correction_retires_preference_without_manual_memory_edit(memory):
    store, service = memory
    propose(store, service, "Я предпочитаю короткие ответы", "Короткие ответы")
    item = service.core_profile()[0]
    source, result = propose(store, service, "Я тогда имел в виду только тот ответ, а не все разговоры", "Короткие ответы",
                             memory_scope="turn", supersedes_id=item["id"])
    assert not service.core_profile()
    assert store.get_memory(item["id"])["status"] == "rejected"
    assert store.get_memory(item["id"])["metadata"]["lifecycle"]["scope_revision_source_ids"] == [source.id]
    service.apply_consolidation(result, [source])
    assert not store.list_memories(status="active")


@pytest.mark.parametrize("text", ["Говори короче", 'Он сказал: «Я тогда имел в виду тот ответ»'])
def test_new_local_request_or_quoted_retraction_cannot_retire_global_preference(memory, text):
    store, service = memory
    propose(store, service, "Я предпочитаю короткие ответы", "Короткие ответы")
    item = service.core_profile()[0]
    propose(store, service, text, "Короткие ответы", memory_scope="turn", supersedes_id=item["id"])
    assert store.get_memory(item["id"])["status"] == "active"


@pytest.mark.parametrize("question,reply,durable", [
    ("Какие ответы ты обычно предпочитаешь, короткие или подробные?", "Короткие", True),
    ("Ты обычно предпочитаешь короткие ответы?", "Да", True),
    ("Какие ответы ты сейчас предпочитаешь, короткие или подробные?", "Короткие", False),
    ("Ты обычно предпочитаешь короткие ответы или подробные?", "Да", False),
])
def test_short_preference_answer_inherits_scope_from_question(memory, question, reply, durable):
    store, service = memory
    store.append_message(role="assistant", content=question, input_mode="text", session_id="a")
    propose(store, service, reply, "Короткие ответы")
    assert bool(service.core_profile()) is durable


def test_scope_correction_can_find_the_known_id_without_fts_overlap(memory):
    store, service = memory
    propose(store, service, "Я предпочитаю короткие ответы", "Короткие ответы")
    item = service.core_profile()[0]
    text = "Я тогда имел в виду только тот ответ, а не все разговоры"
    source, _ = store.append_message(role="user", content=text, input_mode="text")
    formatted, _ = MemoryExtractionWorker(store, service, None)._format_input(text, [source])
    known = json.loads(next(line.removeprefix("KNOWN:") for line in formatted.splitlines() if line.startswith("KNOWN:")))
    assert known[0]["id"] == item["id"]


def test_weekday_schedule_keeps_its_slot_when_model_calls_it_a_habit(memory):
    store, service = memory
    propose(store, service, "По вторникам и четвергам в 19:00 хожу в бассейн", "Бассейн по вторникам и четвергам в 19:00", "habit")
    assert store.list_memories(status="active")[0]["slot_key"] == "user.schedule"


def test_old_preference_cannot_return_with_new_wording_after_scope_correction(memory):
    store, service = memory
    original, _ = propose(store, service, "Я предпочитаю короткие ответы", "Короткие ответы")
    item = service.core_profile()[0]
    propose(store, service, "Я тогда имел в виду только тот ответ, а не все разговоры", "Короткие ответы",
            memory_scope="turn", supersedes_id=item["id"])
    replay = ConsolidationResult.model_validate({"facts": [{
        "kind": "preference", "predicate": "prefers_response_length", "value_text": "Любит краткие ответы по делу",
        "confidence": .96, "importance": .7, "source_message_ids": [original.id],
    }]})
    service.apply_consolidation(replay, [original])
    assert not service.core_profile()
    assert not store.list_memories(status="active")
    # A new, explicit preference from the user remains allowed.
    propose(store, service, "На будущее я всё-таки предпочитаю короткие ответы", "Любит краткие ответы по делу")
    assert service.core_profile()


def age_source(store, source_id, days):
    old = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="milliseconds")
    with store._connect() as connection:
        connection.execute("UPDATE conversation_messages SET created_at=? WHERE id=?", (old, source_id))
    return old


def test_reads_reindex_and_old_job_replay_do_not_reconfirm(memory):
    store, service = memory
    source, result = propose(store, service, "Я изучаю Rust", "Rust", "learning")
    old = age_source(store, source.id, 365)
    item = store.list_memories(status="active")[0]
    store.update_memory(item["id"], {"metadata": {}}, actor="policy")
    service.repair_v22_memory_lifecycle()
    before = store.get_memory(item["id"])
    assert before["metadata"]["lifecycle"]["last_confirmed_at"] == old
    assert freshness(before)["state"] == "aging"
    for _ in range(3):
        service.retrieve("Что я изучаю Rust?")
    service.reindex()
    service.apply_consolidation(result, [store.get_message(source.id)])
    after = store.get_memory(item["id"])
    assert after["metadata"]["lifecycle"] == before["metadata"]["lifecycle"]
    assert freshness(after) == freshness(before)
    assert after["status"] == "active" and after["expires_at"] is None


def test_independent_user_confirmation_refreshes_fact_and_counts_sessions(memory):
    store, service = memory
    source, _ = propose(store, service, "Я изучаю Rust", "Rust", "learning")
    age_source(store, source.id, 365)
    item = store.list_memories(status="active")[0]
    store.update_memory(item["id"], {"metadata": {}}, actor="policy")
    service.repair_v22_memory_lifecycle()
    propose(store, service, "Я по-прежнему изучаю Rust", "Rust", "learning", session="b")
    updated = store.get_memory(item["id"])
    assert updated["source_count"] == 2
    assert updated["metadata"]["lifecycle"]["confirmation_sessions"] == 2
    assert freshness(updated)["state"] == "recent"


def test_weak_duplicate_is_not_confirmation(memory):
    store, service = memory
    propose(store, service, "Я изучаю Rust", "Rust", "learning")
    item = store.list_memories(status="active")[0]
    propose(store, service, "Кажется, я изучаю Rust", "Rust", "learning", session="b", confidence=.72)
    assert store.get_memory(item["id"])["source_count"] == 1


def test_delayed_transient_extraction_uses_assertion_date(memory):
    store, service = memory
    source, result = propose(store, service, "Сейчас я бодрый", "бодрый", "current_mood")
    item = store.list_memories(status="active")[0]
    service.delete(item["id"])
    old = age_source(store, source.id, 4)
    # New isolated source: no resurrection of a user's deleted record.
    other, _ = store.append_message(role="user", content="Сейчас я устал", input_mode="text")
    age_source(store, other.id, 4)
    service.apply_consolidation(ConsolidationResult.model_validate({"facts": [{
        "kind": "fact", "predicate": "current_mood", "value_text": "устал",
        "confidence": .96, "importance": .8, "source_message_ids": [other.id],
    }]}), [store.get_message(other.id)])
    state = next(row for row in store.list_memories(status="active") if row["value_text"] == "устал")
    assert datetime.fromisoformat(state["expires_at"]) < datetime.now(UTC)
    assert service.expire_due_memories() == 1
    assert store.get_memory(item["id"])["status"] == "deleted"


def legacy_style(store, text, value="Короткие ответы", **extra):
    source, _ = store.append_message(role="user", content=text, input_mode="text")
    return store.create_memory({"scope": "user_profile", "kind": "preference", "subject": "user",
        "predicate": "prefers_response_length", "slot_key": "user.prefers_response_length",
        "object_key": "user", "cardinality": "single", "value_text": value,
        "source_message_ids": [source.id], "importance": .8, "confidence": .96, **extra}, actor="extractor")


def test_migration_retires_legacy_local_style_and_preserves_user_data(memory):
    store, service = memory
    local = legacy_style(store, "Говори короче")
    assert not service.core_profile()  # Safe even before startup migration.
    result = service.repair_v22_memory_lifecycle()
    assert result["local_style_retired"] == 1
    assert service.repair_v22_memory_lifecycle()["idempotent_noop"]
    assert store.get_memory(local["id"])["status"] == "rejected"
    assert store.get_message(local["source_message_ids"][0]) is not None


def test_migration_restores_global_preference_displaced_by_local_rule(memory):
    store, service = memory
    old = legacy_style(store, "Я предпочитаю подробные ответы", "Подробные ответы")
    store.set_memory_status(old["id"], "superseded", actor="policy", action="superseded")
    new = legacy_style(store, "Говори короче")
    with store._connect() as connection:
        connection.execute("UPDATE memory_items SET supersedes_id=? WHERE id=?", (old["id"], new["id"]))
    assert service.repair_v22_memory_lifecycle()["global_style_restored"] == 1
    assert service.core_profile()[0]["id"] == old["id"]


def test_manual_style_survives_migration_without_artificial_reconfirmation(memory):
    store, service = memory
    item = service.create_manual({"kind": "preference", "predicate": "prefers_response_length", "value_text": "Короткие ответы"})
    before = item["metadata"]["lifecycle"]["last_confirmed_at"]
    service.repair_v22_memory_lifecycle()
    after = store.get_memory(item["id"])
    assert after["status"] == "active" and after["user_locked"]
    assert after["metadata"]["lifecycle"]["last_confirmed_at"] == before


def test_stable_identity_does_not_age_like_current_state():
    old = (datetime.now(UTC) - timedelta(days=1000)).isoformat()
    base = {"metadata": {"lifecycle": {"last_confirmed_at": old, "confirmation_sessions": 1}}}
    assert freshness({**base, "slot_key": "user.name"})["state"] == "stable"
    assert freshness({**base, "slot_key": "user.schedule"})["state"] == "aging"
