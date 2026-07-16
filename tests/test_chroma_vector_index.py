from pathlib import Path

from apps.backend.app.semantic.chroma_index import ChromaVectorIndex
from apps.backend.app.semantic.embedding import HashEmbeddingProvider
from apps.backend.app.memory.service import MemoryService
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineStore


def test_chroma_index_upserts_searches_deletes_and_rebuilds(tmp_path: Path) -> None:
    source = {"memory": [("second", "пользователь любит чай")]}
    index = ChromaVectorIndex(
        tmp_path / "chroma", HashEmbeddingProvider(dimension=64), lambda namespace: source.get(namespace, []),
    )

    index.upsert_sync("first", "пользователь любит кофе", "memory")
    assert index.search_sync("кофе", "memory", 2)[0].item_id == "first"

    index.delete_sync("first", "memory")
    assert all(result.item_id != "first" for result in index.search_sync("кофе", "memory", 2))

    index.rebuild_sync("memory")
    assert index.search_sync("чай", "memory", 1)[0].item_id == "second"


def test_llm_candidate_is_indexed_in_chroma_outside_an_event_loop(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "memory.sqlite3")
    store.init_db()
    index = ChromaVectorIndex(
        tmp_path / "chroma", HashEmbeddingProvider(dimension=64), store.semantic_index_items,
    )
    service = MemoryService(
        store, RuntimeSettings(memory_mode="automatic"), vector_index=index, semantic_enabled=True,
        llm_extraction_enabled=True,
    )
    message, _ = store.append_message(role="user", content="Я люблю кофе", input_mode="text")

    created = service.apply_llm_candidates([
        {"kind": "preference", "subject": "user", "predicate": "likes", "value_text": "кофе", "confidence": 0.9},
    ], message)

    assert service.sync_next_index_job() is True
    assert index.search_sync("кофе", "memory", 1)[0].item_id == created[0]["id"]
