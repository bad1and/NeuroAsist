from pathlib import Path

import pytest

from apps.backend.app.memory.service import MemoryService
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.semantic.benchmark import semantic_improves_eval
from apps.backend.app.semantic.vector_index import SqliteVecIndex, VectorDimensionMismatch
from apps.backend.app.storage.timeline import TimelineStore


class StaticEmbeddingProvider:
    model_id = "test-multilingual-v1"
    dimension = 2

    def embed(self, text: str) -> list[float]:
        if any(word in text.lower() for word in ("петербург", "saint", "travel")):
            return [1.0, 0.0]
        return [0.0, 1.0]


def _semantic_service(tmp_path: Path) -> tuple[TimelineStore, MemoryService]:
    store = TimelineStore(tmp_path / "semantic.sqlite3")
    store.init_db()
    index = SqliteVecIndex(store._db_path, StaticEmbeddingProvider(), store.semantic_index_items)
    service = MemoryService(
        store, RuntimeSettings(memory_mode="automatic"), vector_index=index,
        semantic_enabled=True, semantic_limit=8,
    )
    return store, service


def test_hybrid_retrieval_finds_multilingual_semantic_match_and_explains_it(tmp_path: Path) -> None:
    store, service = _semantic_service(tmp_path)
    source, _ = store.append_message(role="user", content="Мы обсуждали поездку", input_mode="text")
    memory = service.create_manual({
        "scope": "episode", "kind": "decision", "subject": "user", "predicate": "trip",
        "value_text": "Поездка в Санкт-Петербург", "source_message_ids": [source.id],
    })

    result = service.explain_retrieval("travel to Saint Petersburg")

    assert result["semantic_enabled"] is True
    assert result["items"][0]["id"] == memory["id"]
    assert "semantic" in result["items"][0]["retrieval"]["reasons"]


def test_vector_namespace_rebuilds_and_rejects_mixed_dimensions(tmp_path: Path) -> None:
    store, service = _semantic_service(tmp_path)
    source, _ = store.append_message(role="user", content="Источник", input_mode="text")
    service.create_manual({
        "scope": "user_profile", "kind": "preference", "subject": "user", "predicate": "style",
        "value_text": "Короткие ответы", "source_message_ids": [source.id],
    })
    report = service.reindex()
    assert report["semantic_enabled"] is True
    assert report["semantic_indexed"] == 1

    class DifferentDimensionProvider(StaticEmbeddingProvider):
        model_id = "test-multilingual-v2"
        dimension = 3

        def embed(self, text: str) -> list[float]:
            return [1.0, 0.0, 0.0]

    index = SqliteVecIndex(store._db_path, DifferentDimensionProvider(), store.semantic_index_items)
    with pytest.raises(VectorDimensionMismatch):
        index.upsert_sync("another", "another", "memory")
    index.rebuild_sync("memory")
    assert index.search_sync("короткие", "memory", 1)


def test_vector_failure_falls_back_to_fts_and_eval_gate_is_strict(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "fallback.sqlite3")
    store.init_db()

    class BrokenIndex:
        available = True

        def search_sync(self, *_args):
            raise RuntimeError("extension unavailable")

    service = MemoryService(store, RuntimeSettings(memory_mode="automatic"), vector_index=BrokenIndex(), semantic_enabled=True)
    source, _ = store.append_message(role="user", content="Источник", input_mode="text")
    memory = service.create_manual({
        "scope": "user_profile", "kind": "preference", "subject": "user", "predicate": "style",
        "value_text": "Короткие ответы", "source_message_ids": [source.id],
    })

    result = service.explain_retrieval("короткие")
    assert result["items"][0]["id"] == memory["id"]
    assert result["semantic_enabled"] is False
    assert semantic_improves_eval({"I prefer concise answers": ["wrong"]}, {"I prefer concise answers": ["concise"]}) is True
    assert semantic_improves_eval({"I prefer concise answers": ["concise"]}, {"I prefer concise answers": ["concise"]}) is False
