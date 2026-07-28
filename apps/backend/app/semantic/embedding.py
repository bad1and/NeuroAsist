"""Small dependency-free embedding provider used only when semantic retrieval is enabled."""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Protocol


class EmbeddingProvider(Protocol):
    model_id: str
    dimension: int

    def embed(self, text: str) -> list[float]: ...


class HashEmbeddingProvider:
    """Multilingual character/word n-gram projection with deterministic dimensionality.

    It is intentionally a lightweight fallback, not a claim of a trained semantic model.
    Production semantic mode is gated behind benchmark approval, so deployments can replace
    this provider with a model-backed implementation without changing the vector contract.
    """

    def __init__(self, model_id: str = "hash-multilingual-v1", dimension: int = 256) -> None:
        if dimension < 32:
            raise ValueError("Embedding dimension must be at least 32")
        self.model_id = model_id
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        normalized = " ".join(re.findall(r"[\w]+", text.lower(), flags=re.UNICODE))
        tokens = normalized.split()
        features = tokens + [token[index:index + 3] for token in tokens for index in range(max(1, len(token) - 2))]
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            slot = int.from_bytes(digest[:4], "big") % self.dimension
            vector[slot] += 1.0 if digest[4] & 1 else -1.0
        magnitude = math.sqrt(sum(value * value for value in vector))
        return [value / magnitude for value in vector] if magnitude else vector


class LocalE5EmbeddingProvider:
    """Offline-only ``multilingual-e5-small`` provider with no remote code.

    Importing sentence-transformers is deferred so a normal FTS-only desktop
    install has no heavyweight model dependency.  Model files must already be
    present in the configured local path; this provider never downloads them.
    """

    def __init__(self, model_path: Path, revision: str | None = None) -> None:
        if not model_path.is_dir():
            raise FileNotFoundError(f"Local E5 model is not installed: {model_path}")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - optional runtime dependency
            raise RuntimeError("sentence-transformers is required for local E5 retrieval") from exc
        self.model_id = f"intfloat/multilingual-e5-small@{revision or 'local'}"
        self._model = SentenceTransformer(str(model_path), trust_remote_code=False, local_files_only=True, revision=revision)
        self.dimension = int(self._model.get_sentence_embedding_dimension())

    def embed(self, text: str) -> list[float]:
        vector = self._model.encode("passage: " + text, normalize_embeddings=True, show_progress_bar=False)
        return [float(value) for value in vector]

    def embed_query(self, text: str) -> list[float]:
        vector = self._model.encode("query: " + text, normalize_embeddings=True, show_progress_bar=False)
        return [float(value) for value in vector]
