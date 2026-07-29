"""ChromaDB-backed vector index with the same contract as the SQLite adapter.

Canonical memories deliberately remain in SQLite. This class only indexes their
text, so the index can always be rebuilt after an upgrade, corruption, or restore.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
import math
from shutil import rmtree
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
        self._directory = directory
        self._client = chromadb.PersistentClient(path=str(directory))
        self._provider = provider
        self._source = source
        self._last_successful_sync: str | None = None

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
        self._collection(namespace).upsert(
            ids=[item_id], documents=[text], embeddings=[embedding],
            metadatas=[{"namespace": namespace, "model_id": self._provider.model_id, "dimension": self._provider.dimension}],
        )

    def delete_sync(self, item_id: str, namespace: str) -> None:
        self._collection(namespace).delete(ids=[item_id])

    def search_sync(self, query: str, namespace: str, limit: int) -> list[VectorSearchResult]:
        query_embedding = getattr(self._provider, "embed_query", self._provider.embed)(query)
        result = self._collection(namespace).query(
            query_embeddings=[query_embedding], n_results=max(1, limit), include=["distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        if len(ids) != len(distances):
            raise VectorDimensionMismatch("Chroma returned inconsistent search result lengths")
        return [VectorSearchResult(str(item_id), max(0.0, 1.0 - float(distance))) for item_id, distance in zip(ids, distances)]

    def search_source_sync(self, query: str, namespace: str, limit: int) -> list[VectorSearchResult]:
        embed_query = getattr(self._provider, "embed_query", self._provider.embed)
        query_vector = embed_query(query)
        scored: list[VectorSearchResult] = []
        for item_id, text in self._source(namespace):
            vector = self._provider.embed(text)
            denominator = math.sqrt(sum(value * value for value in query_vector)) * math.sqrt(sum(value * value for value in vector))
            score = sum(left * right for left, right in zip(query_vector, vector)) / denominator if denominator else 0.0
            if score > 0:
                scored.append(VectorSearchResult(item_id, score))
        return sorted(scored, key=lambda item: item.score, reverse=True)[:limit]

    def rebuild_sync(self, namespace: str) -> None:
        source = dict(self._source(namespace))
        collection = self._collection(namespace)
        existing = collection.get(include=["documents"])
        ids = [str(item_id) for item_id in (existing.get("ids") or [])]
        documents = [str(document or "") for document in (existing.get("documents") or [])]
        indexed = dict(zip(ids, documents))
        stale = sorted(set(indexed) - set(source))
        if stale:
            collection.delete(ids=stale)
        for item_id, text in source.items():
            if indexed.get(item_id) != text:
                self.upsert_sync(item_id, text, namespace)
        self._last_successful_sync = self._now()

    def snapshot_sync(self, namespace: str) -> dict[str, object]:
        collection = self._collection(namespace)
        result = collection.get(include=["documents"])
        ids = [str(item_id) for item_id in (result.get("ids") or [])]
        documents = [str(document or "") for document in (result.get("documents") or [])]
        fingerprint = hashlib.sha256(
            "\n".join(f"{item_id}\0{text}" for item_id, text in sorted(zip(ids, documents))).encode("utf-8")
        ).hexdigest()
        return {
            "namespace": namespace,
            "ids": ids,
            "count": len(ids),
            "fingerprint": fingerprint,
            "model_id": self._provider.model_id,
            "dimension": self._provider.dimension,
            "backend": self.backend,
            "directory": str(self._directory),
            "last_successful_sync": self._last_successful_sync,
        }

    def reset_storage_sync(self) -> None:
        """Mark the persistent index for hard deletion at the next backend start.

        Windows keeps Chroma's HNSW files open while this process is running.
        The marker is outside the index directory, so startup can safely remove
        the whole directory before opening a new PersistentClient.
        """
        self.reset_marker_path(self._directory).touch()
        for namespace in ("memory", "topic_memory", "commitment_memory", "episode_summary"):
            try:
                self._client.delete_collection(self._collection_name(namespace))
            except Exception:
                pass

    @classmethod
    def clear_pending_reset(cls, directory: Path) -> bool:
        """Hard-delete a stale Chroma directory before any client opens it."""
        marker = cls.reset_marker_path(directory)
        if not marker.exists():
            return False
        if directory.exists():
            rmtree(directory, ignore_errors=False)
        marker.unlink()
        return True

    @staticmethod
    def remove_legacy_storage_if_safe(directory: Path, replacement: Path) -> bool:
        """Remove only an obsolete Chroma root containing NeuroAsist collections."""
        legacy = directory.resolve()
        if legacy == replacement.resolve() or not legacy.is_dir():
            return False
        database = legacy / "chroma.sqlite3"
        if not database.is_file():
            return False
        connection = None
        try:
            connection = sqlite3.connect(database)
            names = [
                str(row[0])
                for row in connection.execute("SELECT name FROM collections")
            ]
        except (sqlite3.Error, OSError):
            return False
        finally:
            if connection is not None:
                connection.close()
        if not names or any(not name.startswith("neuroasist_") for name in names):
            return False
        try:
            rmtree(legacy, ignore_errors=False)
        except OSError:
            return False
        return True

    @staticmethod
    def reset_marker_path(directory: Path) -> Path:
        return directory.parent / f".{directory.name}.reset-pending"

    def _collection(self, namespace: str):
        name = self._collection_name(namespace)
        expected = {"model_id": self._provider.model_id, "dimension": self._provider.dimension}
        try:
            existing = self._client.get_collection(name)
            metadata = existing.metadata or {}
            if (
                metadata.get("model_id") != expected["model_id"]
                or int(metadata.get("dimension", -1)) != expected["dimension"]
            ):
                self._client.delete_collection(name)
            else:
                return existing
        except Exception:
            pass
        return self._client.get_or_create_collection(
            name=name, embedding_function=None,
            metadata={"model_id": self._provider.model_id, "dimension": self._provider.dimension, "hnsw:space": "cosine"},
        )

    @staticmethod
    def _now() -> str:
        from datetime import UTC, datetime
        return datetime.now(UTC).isoformat(timespec="seconds")

    @staticmethod
    def _collection_name(namespace: str) -> str:
        safe_namespace = "".join(char if char.isalnum() else "_" for char in namespace.lower())
        return f"neuroasist_{safe_namespace}"
