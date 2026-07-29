from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from apps.backend.app.memory.consolidation import ConsolidationResult
from apps.backend.app.memory.service import MemoryService
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import LATEST_SCHEMA_VERSION, TimelineStore


def _service(tmp_path: Path) -> tuple[TimelineStore, MemoryService]:
    store = TimelineStore(tmp_path / "memory-v11.sqlite3")
    store.init_db()
    return store, MemoryService(store, RuntimeSettings(memory_mode="automatic"))


def test_v11_migration_backfills_evidence_and_is_repeatable(tmp_path: Path) -> None:
    store, _ = _service(tmp_path)
    message, _ = store.append_message(role="user", content="Меня зовут Роман", input_mode="text")
    memory = store.create_memory({"scope": "user_profile", "kind": "identity", "subject": "user", "predicate": "name", "value_text": "Роман", "source_message_ids": [message.id]}, actor="test")
    # A second initialization must be a no-op and preserve canonical IDs.
    TimelineStore(tmp_path / "memory-v11.sqlite3").init_db()
    connection = sqlite3.connect(tmp_path / "memory-v11.sqlite3")
    assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == LATEST_SCHEMA_VERSION
    assert connection.execute("SELECT COUNT(*) FROM memory_evidence WHERE entity_id = ?", (memory["id"],)).fetchone()[0] == 1
    connection.close()


def test_topic_commitment_and_profile_are_canonical(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    message, _ = store.append_message(role="user", content="Сделаем память устойчивой", input_mode="text")
    service.create_manual({"predicate": "current_goal", "value_text": "сделать память устойчивой", "source_message_ids": [message.id], "kind": "goal"})
    topic = store.create_topic({"title": "Память", "summary_text": "Долговременная память Iris"})
    store.link_topic(topic["id"], "message", message.id)
    commitment = store.create_commitment({"kind": "milestone", "title": "Проверить миграцию", "source_message_ids": [message.id]})
    assert store.update_commitment(commitment["id"], {"status": "completed"})["completed_at"]
    profile = store.derive_profile()
    assert profile["facts"][0]["predicate"] == "current_goal"
    assert profile["topics"][0]["id"] == topic["id"]


def test_v17_normalizes_developer_aliases_and_repair_is_idempotent(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    name_source, _ = store.append_message(role="user", content="Меня зовут Фёдор", input_mode="text")
    service.create_manual({
        "kind": "identity", "predicate": "name", "value_text": "Фёдор",
        "source_message_ids": [name_source.id],
    })
    user_source, _ = store.append_message(role="user", content="я твой разработчик", input_mode="text")
    oleg_source, _ = store.append_message(
        role="user", content="второго разработчика зовут олег", input_mode="text",
    )
    result = ConsolidationResult.model_validate({
        "facts": [
            {
                "kind": "relationship", "subject": "user", "predicate": "is_developer_of",
                "value_text": "Iris", "importance": .9, "confidence": .99,
                "sensitivity": "normal", "source_message_ids": [user_source.id],
                "cardinality": "multi", "temporal_semantics": "atemporal",
            },
            {
                "kind": "identity", "subject": "oleg", "predicate": "name",
                "value_text": "Oleg", "importance": .9, "confidence": .99,
                "sensitivity": "normal", "source_message_ids": [oleg_source.id],
                "cardinality": "single", "temporal_semantics": "atemporal",
            },
        ],
        "topics": [], "commitments": [], "conflicts": [],
    })

    service.apply_consolidation(result, [user_source, oleg_source], model="fixture")
    active = store.list_memories(status="active", limit=100)
    developers = {
        (item["object_key"], item["value_text"])
        for item in active if item.get("slot_key") == "assistant.developer"
    }
    counts = [
        item for item in active if item.get("slot_key") == "assistant.developer_count"
    ]
    assert developers == {("user", "Федор"), ("person:олег", "Олег")}
    assert len(counts) == 1 and counts[0]["value_text"] == "2"
    assert {item["value_text"] for item in service.retrieve("как зовут второго?")} >= {"Олег"}
    assert {item["value_text"] for item in service.retrieve("кто я?")} >= {"Федор"}

    first = service.repair_v17_canonical_memory()
    total_after_first = len(store.list_memories(limit=500))
    second = service.repair_v17_canonical_memory()
    assert len(store.list_memories(limit=500)) == total_after_first
    assert second["idempotent_noop"] is True
    assert first["canonicalized"] >= 1


def test_v18_repairs_released_duplicate_and_provenance_pattern(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    name_source, _ = store.append_message(
        role="user", content="Зови меня Федя", input_mode="text",
    )
    service.create_manual({
        "kind": "identity", "predicate": "name", "value_text": "Федя",
        "source_message_ids": [name_source.id],
    })
    legacy_source, _ = store.append_message(
        role="user", content="Я твой разработчик", input_mode="text",
    )
    legacy = store.create_memory({
        "scope": "relationship", "kind": "relationship", "subject": "user",
        "predicate": "is_developer_of", "value_text": "Iris",
        "status": "active", "source_message_ids": [legacy_source.id],
        "source_episode_id": legacy_source.episode_id,
        "extractor_version": "consolidation-v11",
    }, actor="extractor")
    old_label = store.create_memory({
        "scope": "relationship", "kind": "relationship", "subject": "assistant",
        "predicate": "developer", "value_text": "Федор", "status": "active",
        "source_message_ids": [], "extractor_version": "consolidation-v11",
        "slot_key": "assistant.developer", "object_key": "user",
        "cardinality": "multi", "normalization_version": 17,
    }, actor="migration")
    store.supersede_memory(str(legacy["id"]), str(old_label["id"]))
    current_label = store.create_memory({
        "scope": "relationship", "kind": "relationship", "subject": "assistant",
        "predicate": "developer", "value_text": "Федя", "status": "active",
        "source_message_ids": [name_source.id],
        "source_episode_id": name_source.episode_id,
        "extractor_version": "consolidation-v11",
        "slot_key": "assistant.developer", "object_key": "user",
        "cardinality": "multi", "normalization_version": 17,
    }, actor="migration")

    before = store.memory_integrity()
    first = service.repair_v18_memory_integrity()
    second = service.repair_v18_memory_integrity()

    assert before["active_conflicts"] == 1
    assert first["duplicates_superseded"] == 1
    assert second["idempotent_noop"] is True
    assert store.memory_integrity()["state"] == "healthy"
    developers = [
        item for item in store.list_memories(status="active", limit=100)
        if item.get("slot_key") == "assistant.developer"
        and item.get("object_key") == "user"
    ]
    assert len(developers) == 1
    assert developers[0]["id"] == current_label["id"]
    assert developers[0]["value_text"] == "Федя"
    assert developers[0]["source_count"] == 2
    with pytest.raises(sqlite3.IntegrityError):
        store.create_memory({
            "scope": "relationship", "kind": "relationship",
            "subject": "assistant", "predicate": "developer",
            "value_text": "Дубликат", "status": "active",
            "source_message_ids": [], "extractor_version": "test",
            "slot_key": "assistant.developer", "object_key": "user",
            "cardinality": "multi", "normalization_version": 18,
        }, actor="test")


def test_v17_assigns_ttl_and_closes_name_loop_when_slot_is_filled(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    mood_source, _ = store.append_message(role="user", content="Сейчас я бодрый", input_mode="text")
    mood_result = ConsolidationResult.model_validate({
        "facts": [{
            "kind": "preference", "subject": "user", "predicate": "mood",
            "value_text": "бодрый", "importance": .7, "confidence": .99,
            "sensitivity": "normal", "source_message_ids": [mood_source.id],
            "cardinality": "single", "temporal_semantics": "current",
        }],
        "topics": [], "commitments": [], "conflicts": [],
    })
    service.apply_consolidation(mood_result, [mood_source], model="fixture")
    mood = next(
        item for item in store.list_memories(status="active")
        if item.get("slot_key") == "user.current_mood"
    )
    assert mood["expires_at"]
    store.update_memory(mood["id"], {"expires_at": "2000-01-01T00:00:00+00:00"})
    assert service.expire_due_memories() == 1
    assert store.get_memory(mood["id"])["status"] == "expired"

    commitment = store.create_commitment({
        "kind": "open_loop",
        "title": "Assistant asked user to provide their name",
        "details": "Как тебя зовут?",
        "target_slot": "user.name",
        "source_message_ids": [mood_source.id],
    })
    name_source, _ = store.append_message(role="user", content="Меня зовут Федор", input_mode="text")
    service.create_manual({
        "kind": "identity", "predicate": "name", "value_text": "Федор",
        "source_message_ids": [name_source.id],
    })
    assert store.get_commitment(commitment["id"])["status"] == "completed"


def test_expired_lease_is_reclaimed_atomically(tmp_path: Path) -> None:
    store, _ = _service(tmp_path)
    now = "2020-01-01T00:00:00.000+00:00"
    with store._connect() as connection:  # exercise the durable job contract directly
        connection.execute("""INSERT INTO background_jobs (id, type, status, payload_json, idempotency_key, available_at, created_at, updated_at, lease_until)
                              VALUES ('lease-test', 'memory_extract', 'running', ?, 'lease-test', ?, ?, ?, ?)""",
                           (json.dumps({"message_id": "missing"}), now, now, now, now))
    job = store.claim_memory_extraction_job()
    assert job is not None
    assert job["id"] == "lease-test"
    assert job["status"] == "running"
    assert job["lease_owner"]


def test_consolidation_validates_sections_independently(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    message, _ = store.append_message(role="user", content="Мне нравятся короткие ответы", input_mode="text")
    result = ConsolidationResult.model_validate({
        "facts": [{"kind": "preference", "subject": "user", "predicate": "prefers_response_length", "value_text": "короткие ответы", "importance": .8, "confidence": .9, "sensitivity": "normal", "source_message_ids": [message.id], "cardinality": "single", "temporal_semantics": "current"}],
        "topics": [{"title": "Стиль ответов", "summary_text": "Пользователь предпочитает краткость", "source_message_ids": [message.id]}],
        "commitments": [{"kind": "open_loop", "title": "Проверить краткость", "source_message_ids": [message.id]}],
        "conflicts": [],
    })
    counts = service.apply_consolidation(result, [message], model="test")
    assert counts == {"facts": 1, "topics": 1, "commitments": 1, "conflicts": 0}
    assert store.list_memories(status="active")[0]["cardinality"] == "single"
    assert store.list_commitments(status="open")[0]["title"] == "Проверить краткость"
