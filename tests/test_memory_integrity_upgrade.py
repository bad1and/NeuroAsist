from __future__ import annotations

import json
import sqlite3

import pytest

from apps.backend.app.memory.consolidation import ConsolidationResult
from apps.backend.app.memory.service import MemoryService
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineStore
from apps.backend.app.context.manager import ContextManager
from apps.backend.app.memory.extraction_worker import MemoryExtractionWorker
from apps.backend.app.semantic.embedding import HashEmbeddingProvider
from apps.backend.app.semantic.vector_index import SqliteVecIndex


@pytest.fixture
def memory(tmp_path):
    store = TimelineStore(tmp_path / "integrity.sqlite3")
    store.init_db()
    return store, MemoryService(store, RuntimeSettings(memory_mode="balanced"), llm_extraction_enabled=True)


def user(store, text, session="audit"):
    return store.append_message(role="user", content=text, input_mode="text", session_id=session)[0]


def propose(service, source, value, predicate="preference", **extra):
    result = ConsolidationResult.model_validate({"facts": [{
        "kind": "fact", "predicate": predicate, "value_text": value, "confidence": .98,
        "importance": .8, "source_message_ids": [source.id], **extra,
    }]})
    service.apply_consolidation(result, [source])
    return result


@pytest.mark.parametrize("action", ["delete", "reject", "forget_permanently", "clear"])
def test_old_evidence_cannot_recreate_deleted_fact_with_paraphrase(memory, action):
    store, service = memory
    source = user(store, "Я люблю кофе без сахара, а ещё я люблю чай")
    old = propose(service, source, "кофе без сахара")
    saved = store.list_memories(status="active")[0]
    getattr(service, action)(saved["id"]) if action != "clear" else service.clear()
    service.apply_consolidation(old, [source])
    propose(service, source, "кофе без добавления сахара")
    assert not store.list_memories(status="active")
    # Suppression is per assertion, not every fact in the same message.
    propose(service, source, "чай")
    assert [item["value_text"] for item in store.list_memories(status="active")] == ["чай"]
    fresh = user(store, "Запомни заново: я люблю кофе без сахара")
    propose(service, fresh, "кофе без сахара")
    assert len(store.list_memories(status="active")) == 2


def test_purge_suppression_survives_restart_without_retaining_value(memory):
    store, service = memory
    source = user(store, "Я люблю кофе без сахара")
    old = propose(service, source, "кофе без сахара")
    service.forget_permanently(store.list_memories(status="active")[0]["id"])
    with sqlite3.connect(store._db_path) as connection:
        marks = connection.execute("SELECT fingerprint_json FROM memory_suppressions").fetchall()
    assert marks and "кофе" not in json.dumps(marks, ensure_ascii=False)
    store.init_db()
    service.apply_consolidation(old, [source])
    assert not store.list_memories(status="active")


def test_single_slot_cannot_resurrect_with_disjoint_location_alias(memory):
    store, service = memory
    source = user(store, "Я живу в Туле")
    propose(service, source, "Тула", "location")
    service.forget_permanently(store.list_memories(status="active")[0]["id"])
    propose(service, source, "Тульская область", "location")
    assert not store.list_memories(status="active")
    propose(service, user(store, "Запомни заново: я живу в Туле"), "Тула", "location")
    assert len(store.list_memories(status="active")) == 1


def test_explicit_restore_remains_authoritative(memory):
    store, service = memory
    source = user(store, "Я люблю кофе")
    propose(service, source, "кофе")
    item = store.list_memories(status="active")[0]
    service.delete(item["id"])
    service.restore(item["id"])
    assert service.retrieve("что я люблю")[0]["id"] == item["id"]


@pytest.mark.parametrize("consent", [False, True])
def test_sensitive_fact_cannot_bypass_consent_through_topic_or_commitment(memory, consent):
    store, service = memory
    source = user(store, ("Запомни: " if consent else "") + "у меня аллергия на арахис")
    result = ConsolidationResult.model_validate({
        "facts": [{"kind": "constraint", "predicate": "health_constraint", "value_text": "аллергия на арахис",
                   "confidence": .98, "importance": .9, "source_message_ids": [source.id]}],
        "topics": [{"title": "Питание", "summary_text": "У пользователя аллергия на арахис", "source_message_ids": [source.id]}],
        "commitments": [{"title": "Учитывать аллергию на арахис", "source_message_ids": [source.id]}],
    })
    service.apply_consolidation(result, [source])
    assert bool(store.list_topics(status="active")) is consent
    assert bool(store.list_commitments(status="open")) is consent
    assert bool(store.list_memories(status="active")) is consent


def test_ordinary_topic_is_preserved_beside_sensitive_fact(memory):
    store, service = memory
    source = user(store, "У меня аллергия на арахис. Я разрабатываю проект Iris")
    result = ConsolidationResult.model_validate({"topics": [{"title": "Разработка Iris", "summary_text": "Работа над проектом Iris", "source_message_ids": [source.id]}]})
    service.apply_consolidation(result, [source])
    assert len(store.list_topics(status="active")) == 1


@pytest.mark.parametrize("text", ["Уволился.", "Уволилась.", "Переехал в Тулу.", "Переехала в Тулу.",
                                 "Бросил курить.", "Купил ноутбук.", "Родилась дочь.", "Закончил университет.", "Развелись."])
def test_short_personal_events_schedule_the_existing_worker(memory, text):
    store, service = memory
    assert service.schedule_extraction(user(store, text))


@pytest.mark.parametrize("text", ["Переехал в Тулу?", "Представь: переехал в Тулу", "Он сказал: бросил курить", "Ага", "Пока"])
def test_event_gate_does_not_turn_questions_quotes_or_smalltalk_into_new_jobs(memory, text):
    store, service = memory
    assert not service.schedule_extraction(user(store, text))


def commitment(service, source, **extra):
    result = ConsolidationResult.model_validate({"commitments": [{
        "kind": "open_loop", "title": "Купить билеты", "confidence": .95,
        "source_message_ids": [source.id], **extra,
    }]})
    return service.apply_consolidation(result, [source])


def test_completed_commitment_updates_the_original_and_old_jobs_do_not_reopen_it(memory):
    store, service = memory
    first = user(store, "Нужно купить билеты")
    commitment(service, first)
    old = store.list_commitments()[0]
    done = user(store, "Билеты уже куплены")
    commitment(service, done, status="completed", commitment_id=old["id"], expected_updated_at=old["updated_at"])
    assert len(store.list_commitments()) == 1
    assert not store.list_commitments(status="open")
    commitment(service, first)
    assert not store.list_commitments(status="open")
    assert len(store.get_commitment(old["id"])["evidence"]) == 2


def test_legacy_commitment_completion_without_id_finds_exact_title(memory):
    store, service = memory
    commitment(service, user(store, "Нужно купить билеты"))
    commitment(service, user(store, "Билеты куплены"), status="completed")
    assert len(store.list_commitments()) == 1
    assert not store.list_commitments(status="open")


def test_commitment_lock_and_expected_version_are_respected(memory):
    store, service = memory
    commitment(service, user(store, "Нужно купить билеты"))
    item = store.list_commitments()[0]
    done = user(store, "Билеты куплены")
    commitment(service, done, status="completed", commitment_id=item["id"], expected_updated_at="wrong-version")
    assert store.get_commitment(item["id"])["status"] == "open"
    store.update_commitment(item["id"], {"user_locked": True})
    commitment(service, done, status="completed", commitment_id=item["id"])
    assert store.get_commitment(item["id"])["status"] == "open"


def test_opposite_preference_replaces_only_the_same_object(memory):
    store, service = memory
    propose(service, user(store, "Я люблю кофе"), "кофе")
    old = store.list_memories(status="active")[0]
    propose(service, user(store, "Я люблю чай"), "чай")
    propose(service, user(store, "Больше не люблю кофе"), "кофе", "dislikes", supersedes_id=old["id"])
    active = {(item["slot_key"], item["value_text"]) for item in store.list_memories(status="active")}
    assert active == {("user.preference", "чай"), ("user.dislike", "кофе")}
    assert store.get_memory(old["id"])["status"] == "superseded"


def test_cross_slot_id_cannot_replace_an_unrelated_fact(memory):
    store, service = memory
    propose(service, user(store, "Я изучаю Rust"), "Rust", "learning")
    rust = store.list_memories(status="active")[0]
    propose(service, user(store, "Нет, я предпочитаю чай"), "чай", supersedes_id=rust["id"])
    assert store.get_memory(rust["id"])["status"] == "active"


def test_evidence_quote_and_pet_source_are_checked(memory):
    store, service = memory
    source = user(store, "Я люблю кофе")
    propose(service, source, "кот Барсик", "pet")
    propose(service, source, "чай", evidence_text="Я люблю чай")
    assert not store.list_memories(status="active")
    propose(service, source, "кофе", evidence_text="Я люблю кофе")
    assert len(store.list_memories(status="active")) == 1


def test_transient_expiration_cannot_be_hidden_by_500_more_important_facts(memory):
    store, service = memory
    propose(service, user(store, "Сейчас я устал"), "устал", "current_mood")
    mood = store.memory_slot_items("user.current_mood")[0]
    store.update_memory(mood["id"], {"expires_at": "2000-01-01T00:00:00+00:00"})
    with store.consolidation_transaction():
        for index in range(501):
            store.create_memory({"scope": "user_profile", "kind": "fact", "subject": "user", "predicate": "device",
                                 "slot_key": "user.device", "value_text": f"Устройство {index}", "importance": 1}, actor="user")
    assert service.expire_due_memories() == 1
    assert store.get_memory(mood["id"])["status"] == "expired"
    assert len(store.list_memories(status="active", limit=1000)) == 501


def test_forgotten_fact_is_filtered_from_derived_recall_but_other_facts_remain(memory):
    store, service = memory
    first = user(store, "Я люблю кофе")
    propose(service, first, "кофе")
    service.forget_permanently(store.list_memories(status="active")[0]["id"])
    second = user(store, "Я изучаю Rust")
    summary = {"id": "synthetic", "summary_text": "Диалог: Я люблю кофе | Я изучаю Rust",
               "source_message_ids": [first.id, second.id]}
    safe = service.project_episode_summary(summary)
    assert safe and "кофе" not in safe["summary_text"] and "Rust" in safe["summary_text"]
    service.apply_consolidation(ConsolidationResult.model_validate({"topics": [{
        "title": "Напитки", "summary_text": "Пользователь любит кофе", "source_message_ids": [first.id, second.id],
    }]}), [first, second])
    assert not store.list_topics(status="active")


def test_restore_allows_original_assertion_in_derived_recall(memory):
    store, service = memory
    first = user(store, "Я люблю кофе")
    propose(service, first, "кофе")
    item = store.list_memories(status="active")[0]
    service.delete(item["id"])
    service.restore(item["id"])
    summary = {"id": "synthetic", "summary_text": "Диалог: Я люблю кофе", "source_message_ids": [first.id]}
    assert service.project_episode_summary(summary)


def test_filtering_factual_recall_does_not_discard_subjective_emotional_tone(memory):
    store, service = memory
    first = user(store, "Мой общий успех и радость — новый проект")
    propose(service, first, "общий успех и радость", "life_event")
    service.forget_permanently(store.list_memories(status="active")[0]["id"])
    summary = {"id": "synthetic", "summary_text": "Диалог: общий успех и радость — Эмоциональный фон: общий успех и радость",
               "source_message_ids": [first.id]}
    safe = service.project_episode_summary(summary)
    assert safe and safe["summary_text"] == "Эмоциональный фон: общий успех и радость"


def test_historical_query_finds_superseded_fact_and_labels_it_in_context(memory):
    store, service = memory
    propose(service, user(store, "Я живу в Туле"), "Тула", "location")
    propose(service, user(store, "Теперь я живу в Москве"), "Москва", "location")
    recalled = service.retrieve("Где я жил раньше, до переезда?")
    assert any(item["value_text"] == "Тула" and item["status"] == "superseded" for item in recalled)
    assert not any(item["status"] == "superseded" for item in service.retrieve("Где я живу?"))
    built = ContextManager(store, memory_service=service).build("Где я жил раньше, до переезда?", session_id="new")
    historical = [item for item in built.diagnostics["selected_memory_records"] if item.get("historical")]
    assert historical and historical[0]["status"] == "superseded"


@pytest.mark.parametrize("query", ["Предложи рецепт ужина", "Посоветуй перекус", "Какой десерт приготовить?"])
def test_food_task_recalls_accepted_food_constraint_without_explicit_allergy_word(memory, query):
    store, service = memory
    propose(service, user(store, "Запомни: у меня аллергия на арахис"), "аллергия на арахис", "health_constraint")
    recalled = service.retrieve(query)
    assert any(item["slot_key"] == "user.health_constraint" and "task_constraint" in item["retrieval"]["reasons"] for item in recalled)
    assert not service.retrieve("Объясни устройство звезды")


def test_enumeration_uses_compact_context_instead_of_silently_capping_at_six(memory):
    store, service = memory
    for index in range(10):
        service.create_manual({"kind": "fact", "predicate": "project", "value_text": f"Проект Альфа{index}"})
    built = ContextManager(store, memory_service=service).build("Перечисли все мои проекты", session_id="new")
    assert len(built.diagnostics["selected_memory_records"]) == 10
    assert built.token_estimate <= built.diagnostics["budget"]
    assert built.diagnostics["block_budgets"]["facts"] == service.context_max_tokens


def test_summary_retains_middle_event_and_emotional_section_with_long_prose(memory):
    store, service = memory
    for index, text in enumerate(["Привет " + "длинная реплика " * 150, "Сегодня солнечно", "Слушаю музыку", "Бросил курить.", "Устал после прогулки", "Сейчас поужинаю", "До завтра"]):
        source = user(store, text)
        if index == 3:
            store.append_character_state_event(relationship_id="primary", participant_key=None, event_kind="shared_success",
                                               confidence=.98, intensity=.8, cause_message_ids=[source.id], delta={"joy": .5})
    closed = store.close_current_episode()
    summary = store.get_episode_summary_for_episode(closed["id"])
    assert "Бросил курить" in summary["summary_text"]
    assert "общий успех и радость" in summary["summary_text"]
    assert len(summary["summary_text"]) <= 1000


def test_single_query_embedding_is_shared_and_not_cached_across_turns(tmp_path):
    class CountingHash(HashEmbeddingProvider):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def embed(self, text):
            self.calls += 1
            return super().embed(text)

    store = TimelineStore(tmp_path / "cache.sqlite3")
    store.init_db()
    provider = CountingHash()
    index = SqliteVecIndex(store._db_path, provider, store.semantic_index_items)
    service = MemoryService(store, RuntimeSettings(memory_mode="balanced"), vector_index=index, semantic_enabled=True)
    service.create_manual({"kind": "fact", "predicate": "preference", "value_text": "кофе"})
    service.reindex()
    provider.calls = 0
    manager = ContextManager(store, memory_service=service)
    manager.build("Расскажи о путешествиях", session_id="new")
    assert provider.calls == 1
    manager.build("Расскажи о путешествиях", session_id="new")
    assert provider.calls == 2


def test_worker_receives_open_commitment_id_and_version(memory):
    store, service = memory
    commitment(service, user(store, "Нужно купить билеты"))
    saved = store.list_commitments()[0]
    done = user(store, "Билеты уже куплены")
    prompt, _ = MemoryExtractionWorker(store, service, None)._format_input(done.content, [done])
    assert "LOOPS:" in prompt and saved["id"] in prompt and saved["updated_at"] in prompt


def test_schema_upgrade_and_memory_operations_preserve_character_state(memory):
    store, service = memory
    state = {"mood": "warm", "emotions": {"joy": .65, "interest": .4}, "relationship": {"trust": .7}}
    store.save_character_state_snapshot("primary", state)
    before = store.load_character_state_snapshot("primary")
    propose(service, user(store, "Я люблю кофе"), "кофе")
    service.forget_permanently(store.list_memories(status="active")[0]["id"])
    store.init_db()
    assert store.load_character_state_snapshot("primary") == before
