from datetime import datetime, timedelta, timezone

import pytest

from apps.backend.app.context.manager import ContextManager
from apps.backend.app.memory.service import MemoryService
from apps.backend.app.memory.temporal import inherit_temporal_question, temporal_recall
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineStore


MSK = timezone(timedelta(hours=3))
NOW = datetime(2026, 10, 29, 15, 0, tzinfo=MSK)


@pytest.fixture
def memory(tmp_path):
    store = TimelineStore(tmp_path / "temporal.sqlite3")
    store.init_db()
    service = MemoryService(store, RuntimeSettings(memory_mode="balanced"))
    return store, service


def user(store, text, at="2026-10-29T10:39:00+00:00", session="earlier"):
    return store.append_message(role="user", content=text, input_mode="text", created_at=at, session_id=session)[0]


def fact(store, source, text=None):
    return store.create_memory({
        "scope": "profile", "kind": "fact", "subject": "user", "predicate": "personal_fact",
        "value_text": text or source.effective_content, "importance": .8, "confidence": .98,
        "source_message_ids": [source.id], "source_episode_id": source.episode_id,
        "metadata": {"lifecycle": {"scope": "durable", "last_confirmed_at": source.created_at}},
    }, actor="test")


@pytest.mark.parametrize("query", [
    "чем я занимался последний раз", "чем я занимался в прошлый раз",
    "последнее, что делал", "что мы обсуждали до перерыва",
    "да заебца я вот тут ходил подскажи пожалуйста чем я занимался последний раз",
])
def test_last_time_is_shared_temporal_intent(query):
    assert ContextManager._is_temporal_query(query)
    assert MemoryService._is_temporal_query(query)
    intent = temporal_recall(query, now=NOW)
    assert intent.latest and intent.day is None


@pytest.mark.parametrize("correction", ["сегодня", "ну разумеется то что сегодня", "нет, вчера", "я имел в виду вчера"])
def test_day_correction_keeps_user_subject(correction):
    query = inherit_temporal_question(correction, ["чем я занимался последний раз"])
    assert "чем я занимался" in query
    intent = temporal_recall(query, now=NOW)
    assert intent.day == (NOW - timedelta(days="вчера" in correction)).date()
    assert not intent.latest


def test_day_correction_replaces_previous_day_and_does_not_cross_topic():
    query = inherit_temporal_question("нет, вчера", ["чем я занимался сегодня", "сегодня"])
    assert "сегодня" not in query
    assert temporal_recall(query, now=NOW).day.day == 28
    assert inherit_temporal_question("сегодня", ["чем я занимался последний раз", "что приготовить на ужин?"]) == "сегодня"
    assert temporal_recall("Сегодня я исправил кнопки", now=NOW) is None
    assert temporal_recall("Напомни мне поесть сегодня", now=NOW) is None
    assert temporal_recall("Чем я занимался сегодня? Нет, вчера.", now=NOW).day.day == 28
    assert temporal_recall("ну разумеется то что сегодня\nА чем я занимался вчера?", now=NOW).day.day == 28


def test_original_dialogue_retains_dates_subject_and_completion(memory):
    store, service = memory
    start = user(store, "Я улучшаю кнопки аватара, они исчезают при наведении на панель", "2026-10-29T10:35:22+00:00")
    fact(store, start)
    user(store, "Я объяснял проблему второму разработчику, он плохо разбирается во фронтенде", "2026-10-29T10:39:19+00:00")
    outcome = user(store, "Я уже всё исправил: убрал конфликт обработчиков скрытия кнопок", "2026-10-29T10:40:31+00:00")
    user(store, "Все по правилам", "2026-10-29T10:40:34+00:00")
    store.close_current_episode("manual", now="2026-10-29T10:41:00+00:00")
    question = user(store, "чем я занимался последний раз", "2026-10-29T12:00:15+00:00", "now")
    manager = ContextManager(store, memory_service=service)
    built = manager.build(question.content, session_id="now", current_message_id=question.id)
    prompt = "\n".join(message.content for message in built.messages)
    assert "кнопки аватара" in prompt
    assert "уже всё исправил" in prompt
    assert outcome.id in built.diagnostics["temporal_source_message_ids"]
    assert built.diagnostics["temporal_recall"]["latest"]
    assert built.diagnostics["selected_summary_ids"]
    assert built.token_estimate <= 3000
    store.append_message(role="assistant", content="В конце октября ты занимался кнопками", input_mode="text", session_id="now", created_at="2026-10-29T12:00:48+00:00")
    correction = user(store, "ну разумеется то что сегодня", "2026-10-29T12:00:54+00:00", "now")
    corrected = manager.build(correction.content, session_id="now", current_message_id=correction.id)
    assert corrected.diagnostics["temporal_recall"]["inherited_subject"]
    assert corrected.diagnostics["temporal_recall"]["day"] == "2026-10-29"
    assert outcome.id in corrected.diagnostics["temporal_source_message_ids"]
    assert any(item["value"] == start.content for item in corrected.diagnostics["selected_memory_records"])


def test_today_filters_before_semantic_ranking_and_uses_source_not_save_time(memory):
    store, service = memory
    old = user(store, "Я настраивал кнопки интерфейса", "2026-10-21T10:00:00+00:00")
    old_fact = fact(store, old)
    fresh = user(store, "Я рисовал аватар для приложения")
    fresh_fact = fact(store, fresh)
    # Both records are saved now; the old source must still stay outside today.
    memories, _ = service.recall_temporal("чем я занимался сегодня", temporal_recall("чем я занимался сегодня", now=NOW))
    assert [item["id"] for item in memories] == [fresh_fact["id"]]
    assert old_fact["id"] not in [item["id"] for item in memories]


def test_newest_evidence_survives_context_budget_trimming(memory):
    store, service = memory
    pairs = []
    for index in range(3):
        source = user(store, f"Я исправлял кнопки аватара в варианте {index}")
        pairs.append((fact(store, source), source))
    # Make the newest source belong to the lexically last ID. ID order must
    # not decide which dated fact survives a tight context budget.
    pairs.sort(key=lambda pair: pair[0]["id"])
    with store._connect() as connection:
        for index, (_, source) in enumerate(pairs):
            connection.execute("UPDATE conversation_messages SET created_at = ? WHERE id = ?", (f"2026-10-29T10:{10 + index}:00+00:00", source.id))
    service._context_max_tokens = 200
    question = user(store, "Чем я занимался последний раз?", "2026-10-29T12:00:00+00:00", "now")
    built = ContextManager(store, memory_service=service).build(question.content, session_id="now", current_message_id=question.id)
    selected = [item["id"] for item in built.diagnostics["selected_memory_records"]]
    assert selected[0] == pairs[-1][0]["id"]
    assert pairs[0][0]["id"] not in selected


def test_local_midnight_and_explicit_event_date(memory):
    store, service = memory
    today = user(store, "Я починил кнопки аватара", "2026-10-28T22:30:00+00:00")
    today_fact = fact(store, today)
    yesterday = user(store, "Вчера я настраивал графику приложения", "2026-10-28T22:35:00+00:00")
    yesterday_fact = fact(store, yesterday, "2026-10-28 настраивал графику приложения")
    intent = temporal_recall("чем я занимался сегодня", now=NOW)
    memories, sources = service.recall_temporal("чем я занимался сегодня", intent)
    assert [item["id"] for item in memories] == [today_fact["id"]]
    assert {item["message_id"] for item in sources} == {today.id}
    assert sources[0]["reported_day"] == "сегодня"
    assert sources[0]["time_basis"] == "report"
    intent = temporal_recall("чем я занимался вчера", now=NOW)
    memories, sources = service.recall_temporal("чем я занимался вчера", intent)
    assert [item["id"] for item in memories] == [yesterday_fact["id"]]
    assert sources[0]["event_date"] == "2026-10-28"
    assert sources[0]["reported_day"] == "сегодня"


def test_last_known_is_not_automatically_today(memory):
    store, service = memory
    old = user(store, "Я чинил кнопки аватара", "2026-10-27T10:00:00+00:00")
    old_fact = fact(store, old)
    memories, _ = service.recall_temporal("чем я занимался последний раз", temporal_recall("чем я занимался последний раз", now=NOW))
    assert memories[0]["id"] == old_fact["id"]
    assert service.recall_temporal("чем я занимался сегодня", temporal_recall("чем я занимался сегодня", now=NOW)) == ([], [])


@pytest.mark.parametrize("mode", ["incognito", "off", "deleted", "suppressed", "ambient", "no_store"])
def test_temporal_recall_respects_memory_policy(memory, mode):
    store, service = memory
    source = user(store, "Я работаю над кнопками аватара")
    saved = fact(store, source)
    if mode == "incognito":
        service._runtime.memory_incognito = True
    elif mode == "off":
        service._runtime.memory_mode = "off"
    elif mode in {"deleted", "suppressed"}:
        service.delete(saved["id"]) if mode == "deleted" else service.forget_permanently(saved["id"])
    elif mode == "ambient":
        store.merge_message_metadata(source.id, {"dialogue_scope": "ambient"})
    else:
        with store._connect() as connection:
            connection.execute("UPDATE conversation_messages SET content = ? WHERE id = ?", ("Не запоминай: " + source.content, source.id))
    assert service.recall_temporal("чем я занимался сегодня", temporal_recall("чем я занимался сегодня", now=NOW)) == ([], [])


def test_evidence_does_not_include_later_turns(memory):
    store, service = memory
    old = user(store, "Я чинил кнопки аватара")
    saved = fact(store, old)
    question = user(store, "чем я занимался сегодня", "2026-10-29T12:00:00+00:00")
    future = user(store, "Я уже закончил новый проект", "2026-10-29T12:01:00+00:00")
    fact(store, future)
    memories, sources = service.recall_temporal(question.content, temporal_recall(question.content, now=NOW), before_sequence=question.sequence_no)
    assert [item["id"] for item in memories] == [saved["id"]]
    assert future.id not in {item["message_id"] for item in sources}


def test_short_outcome_is_preserved_in_source_evidence(memory):
    store, service = memory
    user(store, "Я разбираюсь с кнопками аватара")
    outcome = user(store, "Уже исправил", "2026-10-29T10:40:00+00:00")
    _, sources = service.recall_temporal("чем я занимался последний раз", temporal_recall("чем я занимался последний раз", now=NOW))
    assert outcome.id in {item["message_id"] for item in sources}


def test_later_summary_cannot_leak_future_turns_into_recall(memory):
    store, service = memory
    source = user(store, "Я чинил кнопки аватара")
    fact(store, source)
    question = user(store, "Чем я занимался сегодня?", "2026-10-29T10:45:00+00:00")
    user(store, "Мой секретный новый проект будет про космических котов", "2026-10-29T10:46:00+00:00")
    store.close_current_episode("manual", now="2026-10-29T10:47:00+00:00")
    built = ContextManager(store, memory_service=service).build(question.content, session_id="earlier", current_message_id=question.id)
    assert "космических котов" not in "\n".join(message.content for message in built.messages)
    assert source.id in built.diagnostics["temporal_source_message_ids"]


@pytest.mark.parametrize("text", [
    "У меня диагностировали диабет первого типа",
    "Мой адрес: улица Примерная, дом 17",
    "Мой пароль от сервиса — synthetic-password",
    "Запомни мой пароль от сервиса — synthetic-password",
])
def test_sensitive_source_needs_consent_even_in_raw_recall(memory, text):
    store, service = memory
    user(store, text)
    memories, sources = service.recall_temporal("чем я занимался сегодня", temporal_recall("чем я занимался сегодня", now=NOW))
    assert memories == sources == []


def test_explicit_consent_allows_sensitive_source_recall(memory):
    store, service = memory
    source = user(store, "Запомни: у меня диагностировали диабет первого типа")
    _, sources = service.recall_temporal("чем я занимался сегодня", temporal_recall("чем я занимался сегодня", now=NOW))
    assert [item["message_id"] for item in sources] == [source.id]


def test_new_summary_preserves_finished_outcome(memory):
    store, _ = memory
    user(store, "Мне нужно исправить кнопки аватара")
    for index in range(7):
        user(store, f"Нужно проверить поведение панели номер {index}")
    user(store, "Я уже всё исправил: убрал конфликт обработчиков")
    user(store, "Все по правилам")
    closed = store.close_current_episode("manual")
    assert "уже всё исправил" in store.get_episode_summary_for_episode(closed["id"])["summary_text"]
