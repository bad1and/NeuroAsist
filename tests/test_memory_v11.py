from __future__ import annotations

import json
import sqlite3
from pathlib import Path

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
