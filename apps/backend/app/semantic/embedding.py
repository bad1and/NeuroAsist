"""Small dependency-free embedding provider used only when semantic retrieval is enabled."""

from __future__ import annotations

import hashlib
import math
import re
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
