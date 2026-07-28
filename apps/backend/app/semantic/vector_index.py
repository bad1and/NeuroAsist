"""Rebuildable vector-index adapters with a safe SQLite/FTS fallback path."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Protocol

from .embedding import EmbeddingProvider


@dataclass(frozen=True)
class VectorSearchResult:
    item_id: str
    score: float


class VectorIndex(Protocol):
    async def upsert(self, item_id: str, text: str, namespace: str) -> None: ...
    async def delete(self, item_id: str, namespace: str) -> None: ...
    async def search(self, query: str, namespace: str, limit: int) -> list[VectorSearchResult]: ...
    async def rebuild(self, namespace: str) -> None: ...


class VectorDimensionMismatch(ValueError):
    pass


class NullVectorIndex:
    """Explicit no-op used while semantic retrieval is disabled or degraded."""

    available = False
    backend = "null"

    async def upsert(self, item_id: str, text: str, namespace: str) -> None:
        return None

    async def delete(self, item_id: str, namespace: str) -> None:
        return None

    async def search(self, query: str, namespace: str, limit: int) -> list[VectorSearchResult]:
        return []

    async def rebuild(self, namespace: str) -> None:
        return None

    def search_sync(self, query: str, namespace: str, limit: int) -> list[VectorSearchResult]:
        return []


class SqliteVecIndex:
    """SQLite vector adapter with optional sqlite-vec extension discovery.

    When the optional extension is unavailable, vectors remain in the rebuildable
    `semantic_vectors` table and cosine ranking is evaluated in-process. This keeps
    canonical data and FTS fully operational while preserving the same model/dimension
    isolation contract for a later native sqlite-vec acceleration path.
    """

    backend = "sqlite-vec-compatible"

    def __init__(self, database_path: Path, provider: EmbeddingProvider, source: Callable[[str], list[tuple[str, str]]]) -> None:
        self._database_path = database_path
        self._provider = provider
        self._source = source
        self.available = True
        self.extension_available = self._detect_sqlite_vec()

    async def upsert(self, item_id: str, text: str, namespace: str) -> None:
        self.upsert_sync(item_id, text, namespace)

    async def delete(self, item_id: str, namespace: str) -> None:
        self.delete_sync(item_id, namespace)

    async def search(self, query: str, namespace: str, limit: int) -> list[VectorSearchResult]:
        return self.search_sync(query, namespace, limit)

    async def rebuild(self, namespace: str) -> None:
        self.rebuild_sync(namespace)

    def upsert_sync(self, item_id: str, text: str, namespace: str) -> None:
        vector = self._provider.embed(text)
        if len(vector) != self._provider.dimension:
            raise VectorDimensionMismatch("Embedding provider returned an unexpected dimension")
        now = self._now()
        with self._connect() as connection:
            state = connection.execute("SELECT model_id, dimension FROM semantic_index_state WHERE namespace = ?", (namespace,)).fetchone()
            if state is not None and (state["model_id"] != self._provider.model_id or state["dimension"] != self._provider.dimension):
                raise VectorDimensionMismatch("Rebuild namespace before changing embedding model or dimension")
            connection.execute(
                "INSERT OR REPLACE INTO semantic_index_state (namespace, model_id, dimension, backend, updated_at) VALUES (?, ?, ?, ?, ?)",
                (namespace, self._provider.model_id, self._provider.dimension, self.backend, now),
            )
            connection.execute(
                """INSERT OR REPLACE INTO semantic_vectors (namespace, item_id, model_id, dimension, vector_json, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (namespace, item_id, self._provider.model_id, self._provider.dimension, json.dumps(vector), now),
            )

    def delete_sync(self, item_id: str, namespace: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM semantic_vectors WHERE namespace = ? AND item_id = ?", (namespace, item_id))

    def search_sync(self, query: str, namespace: str, limit: int) -> list[VectorSearchResult]:
        embed_query = getattr(self._provider, "embed_query", self._provider.embed)
        query_vector = embed_query(query)
        with self._connect() as connection:
            state = connection.execute("SELECT model_id, dimension FROM semantic_index_state WHERE namespace = ?", (namespace,)).fetchone()
            if state is None:
                return []
            if state["model_id"] != self._provider.model_id or state["dimension"] != self._provider.dimension:
                raise VectorDimensionMismatch("Vector namespace uses a different embedding model or dimension")
            rows = connection.execute(
                "SELECT item_id, vector_json FROM semantic_vectors WHERE namespace = ? AND model_id = ? AND dimension = ?",
                (namespace, self._provider.model_id, self._provider.dimension),
            ).fetchall()
        scored = [VectorSearchResult(row["item_id"], self._cosine(query_vector, json.loads(row["vector_json"]))) for row in rows]
        return sorted((item for item in scored if item.score > 0), key=lambda item: item.score, reverse=True)[:limit]

    def rebuild_sync(self, namespace: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM semantic_vectors WHERE namespace = ?", (namespace,))
            connection.execute("DELETE FROM semantic_index_state WHERE namespace = ?", (namespace,))
        for item_id, text in self._source(namespace):
            self.upsert_sync(item_id, text, namespace)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _cosine(first: list[float], second: list[float]) -> float:
        if len(first) != len(second):
            raise VectorDimensionMismatch("Stored vector dimension does not match query vector")
        denominator = math.sqrt(sum(value * value for value in first)) * math.sqrt(sum(value * value for value in second))
        return sum(left * right for left, right in zip(first, second)) / denominator if denominator else 0.0

    @staticmethod
    def _detect_sqlite_vec() -> bool:
        try:
            import sqlite_vec  # type: ignore[import-not-found]
            return callable(getattr(sqlite_vec, "load", None))
        except ImportError:
            return False

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="milliseconds")
