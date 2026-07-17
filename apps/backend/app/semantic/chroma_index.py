"""ChromaDB-backed vector index with the same contract as the SQLite adapter.

Canonical memories deliberately remain in SQLite. This class only indexes their
text, so the index can always be rebuilt after an upgrade, corruption, or restore.
"""

from __future__ import annotations

from pathlib import Path
from shutil import rmtree
from threading import RLock
from typing import Callable

from .embedding import EmbeddingProvider
from .vector_index import VectorDimensionMismatch, VectorSearchResult


class ChromaVectorIndex:
    backend = "chroma"
    available = True

    def __init__(self, directory: Path, provider: EmbeddingProvider, source: Callable[[str], list[tuple[str, str]]]) -> None:
        try:
            import chromadb
        except ImportError as exc:  # pragma: no cover - exercised in packaged environments
            raise RuntimeError("ChromaDB is enabled but the chromadb package is not installed") from exc
        self._chromadb = chromadb
        self._directory = directory
        self._client = chromadb.PersistentClient(path=str(directory))
        self._provider = provider
        self._source = source
        self._lock = RLock()

    async def upsert(self, item_id: str, text: str, namespace: str) -> None:
        self.upsert_sync(item_id, text, namespace)

    async def delete(self, item_id: str, namespace: str) -> None:
        self.delete_sync(item_id, namespace)

    async def search(self, query: str, namespace: str, limit: int) -> list[VectorSearchResult]:
        return self.search_sync(query, namespace, limit)

    async def rebuild(self, namespace: str) -> None:
        self.rebuild_sync(namespace)

    def upsert_sync(self, item_id: str, text: str, namespace: str) -> None:
        embedding = self._provider.embed(text)
        with self._lock:
            self._collection(namespace).upsert(
                ids=[item_id], documents=[text], embeddings=[embedding],
                metadatas=[{"namespace": namespace, "model_id": self._provider.model_id, "dimension": self._provider.dimension}],
            )

    def delete_sync(self, item_id: str, namespace: str) -> None:
        with self._lock:
            self._collection(namespace).delete(ids=[item_id])

    def search_sync(self, query: str, namespace: str, limit: int) -> list[VectorSearchResult]:
        query_embedding = self._provider.embed(query)
        with self._lock:
            result = self._collection(namespace).query(
                query_embeddings=[query_embedding], n_results=max(1, limit), include=["distances"],
            )
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        if len(ids) != len(distances):
            raise VectorDimensionMismatch("Chroma returned inconsistent search result lengths")
        return [VectorSearchResult(str(item_id), max(0.0, 1.0 - float(distance))) for item_id, distance in zip(ids, distances)]

    def rebuild_sync(self, namespace: str) -> None:
        with self._lock:
            name = self._collection_name(namespace)
            try:
                self._client.delete_collection(name)
            except Exception:
                pass  # A missing collection is the normal first-run case.
            for item_id, text in self._source(namespace):
                self.upsert_sync(item_id, text, namespace)

    def reset_storage_sync(self) -> None:
        """Discard all Chroma files after a full companion-data reset.

        ChromaDB may retain empty segment folders after collections are deleted.
        SQLite remains canonical, so a full reset can safely recreate this index from
        an empty directory instead of accumulating orphaned implementation files.
        """
        with self._lock:
            self._client.close()
            rmtree(self._directory, ignore_errors=False)
            self._directory.mkdir(parents=True, exist_ok=True)
            self._client = self._chromadb.PersistentClient(path=str(self._directory))

    def _collection(self, namespace: str):
        return self._client.get_or_create_collection(
            name=self._collection_name(namespace), embedding_function=None,
            metadata={"model_id": self._provider.model_id, "dimension": self._provider.dimension, "hnsw:space": "cosine"},
        )

    @staticmethod
    def _collection_name(namespace: str) -> str:
        safe_namespace = "".join(char if char.isalnum() else "_" for char in namespace.lower())
        return f"neuroasist_{safe_namespace}"
