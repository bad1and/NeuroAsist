"""Policy-controlled writes and FTS retrieval for long-term companion memory."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.semantic.vector_index import NullVectorIndex, VectorDimensionMismatch
from apps.backend.app.storage.timeline import StoredTimelineMessage, TimelineStore


class MemoryService:
    """The only component allowed to turn a candidate into canonical memory."""

    _SENSITIVE_WORDS = ("здоров", "болез", "диагноз", "адрес", "паспорт", "карта", "парол", "полит")

    def __init__(
        self,
        store: TimelineStore,
        runtime: RuntimeSettings,
        *,
        enabled: bool = True,
        sensitive_mode: str = "ask",
        max_candidates_per_turn: int = 3,
        context_max_tokens: int = 900,
        vector_index=None,
        semantic_enabled: bool = False,
        semantic_limit: int = 8,
    ) -> None:
        self._store = store
        self._runtime = runtime
        self._enabled = enabled
        self._sensitive_mode = sensitive_mode
        self._max_candidates_per_turn = max_candidates_per_turn
        self._context_max_tokens = context_max_tokens
        self._vector_index = vector_index or NullVectorIndex()
        self._semantic_enabled = semantic_enabled and getattr(self._vector_index, "available", False)
        self._semantic_limit = semantic_limit
        self._semantic_degraded_reason: str | None = None

    @property
    def incognito(self) -> bool:
        return self._runtime.memory_incognito

    @property
    def store(self) -> TimelineStore:
        return self._store

    def should_persist_timeline(self) -> bool:
        return not self.incognito

    @property
    def semantic_enabled(self) -> bool:
        return self._semantic_enabled and self._semantic_degraded_reason is None

    def retrieve(self, query: str, limit: int = 6) -> list[dict[str, object]]:
        if not self._enabled or self.incognito:
            return []
        normalized_query = self._normalize(query)
        if "как меня зовут" in normalized_query or "my name" in normalized_query:
            memories = [item for item in self._store.list_memories(status="active", limit=limit) if item["predicate"] == "name"]
            memories = self._attach_retrieval(memories, {str(item["id"]): 1.0 for item in memories}, {}, temporal=False)
        else:
            memories = self._hybrid_retrieve(query, limit)
        selected: list[dict[str, object]] = []
        used_tokens = 0
        for memory in memories:
            estimate = max(1, len(str(memory["value_text"])) // 4)
            if selected and used_tokens + estimate > self._context_max_tokens:
                continue
            used_tokens += estimate
            selected.append(memory)
            self._record_retrieval(memory)
        return selected

    def explain_retrieval(self, query: str, limit: int = 8) -> dict[str, object]:
        return {
            "query": query,
            "semantic_enabled": self.semantic_enabled,
            "semantic_degraded_reason": self._semantic_degraded_reason,
            "items": self.retrieve(query, limit),
        }

    def extract_from_message(self, message: StoredTimelineMessage | None) -> list[dict[str, object]]:
        if not self._enabled or self.incognito or self._runtime.memory_mode == "off" or message is None:
            return []
        if message.role != "user" or message.status != "completed":
            return []
        candidates = self._extract_candidates(message.effective_content)
        saved: list[dict[str, object]] = []
        for candidate in candidates[: self._max_candidates_per_turn]:
            candidate.update({
                "source_message_ids": [message.id],
                "source_episode_id": message.episode_id,
                "extractor_version": "deterministic-v1",
            })
            saved.append(self._apply_candidate(candidate, actor="extractor"))
        return saved

    def create_manual(self, values: dict[str, object]) -> dict[str, object]:
        source_ids = list(values.get("source_message_ids", []))
        self._validate_sources(source_ids, manual=False)
        if source_ids and not values.get("source_episode_id"):
            source = self._store.get_message(source_ids[0])
            values = {**values, "source_episode_id": source.episode_id if source else None}
        values = {**values, "status": "active", "user_locked": True, "extractor_version": "manual-v1"}
        return self._apply_candidate(values, actor="user", action="activated")

    def confirm(self, memory_id: str) -> dict[str, object]:
        memory = self._store.get_memory(memory_id)
        if memory is None:
            raise KeyError(memory_id)
        if memory["status"] != "candidate":
            return memory
        self._resolve_conflict(memory_id, memory)
        confirmed = self._store.set_memory_status(memory_id, "active", actor="user", action="confirmed")
        self._sync_vector(confirmed)
        return confirmed

    def reject(self, memory_id: str) -> dict[str, object]:
        return self._store.set_memory_status(memory_id, "rejected", actor="user", action="rejected")

    def delete(self, memory_id: str) -> dict[str, object]:
        memory = self._store.set_memory_status(memory_id, "deleted", actor="user", action="deleted")
        self._delete_vector(memory_id)
        return memory

    def restore(self, memory_id: str) -> dict[str, object]:
        memory = self._store.set_memory_status(memory_id, "active", actor="user", action="restored")
        self._sync_vector(memory)
        return memory

    def edit(self, memory_id: str, changes: dict[str, object]) -> dict[str, object]:
        memory = self._store.update_memory(memory_id, changes)
        if memory["status"] == "active":
            self._sync_vector(memory)
        return memory

    def reindex(self) -> dict[str, object]:
        fts_indexed = self._store.reindex_memories()
        if not self.semantic_enabled:
            return {"indexed": fts_indexed, "fts_indexed": fts_indexed, "semantic_indexed": 0, "semantic_enabled": False}
        try:
            self._vector_index.rebuild_sync("memory")
            self._vector_index.rebuild_sync("episode_summary")
            return {
                "fts_indexed": fts_indexed,
                "indexed": fts_indexed,
                "semantic_indexed": len(self._store.semantic_index_items("memory")),
                "semantic_enabled": True,
            }
        except Exception as exc:
            self._degrade_semantic(exc)
            return {"indexed": fts_indexed, "fts_indexed": fts_indexed, "semantic_indexed": 0, "semantic_enabled": False}

    def clear(self, status: str | None = None) -> int:
        deleted = self._store.clear_memories(status)
        if self.semantic_enabled:
            try:
                self._vector_index.rebuild_sync("memory")
            except Exception as exc:
                self._degrade_semantic(exc)
        return deleted

    def index_episode_summary(self, summary: dict[str, object] | None) -> None:
        if not summary or not self.semantic_enabled:
            return
        try:
            self._vector_index.upsert_sync(str(summary["id"]), str(summary["summary_text"]), "episode_summary")
        except Exception as exc:
            self._degrade_semantic(exc)

    def _apply_candidate(self, values: dict[str, object], *, actor: str, action: str = "candidate_created") -> dict[str, object]:
        self._validate_sources(list(values.get("source_message_ids", [])), manual=actor == "user")
        values = {**values, "subject": self._normalize(str(values["subject"])), "predicate": self._normalize(str(values["predicate"]))}
        exact, conflict = self._match_existing(values)
        if exact is not None:
            self._store.update_memory(exact["id"], {}, actor="policy", action="retrieved")
            return exact
        status = str(values.get("status", "candidate"))
        if actor == "extractor":
            sensitive = values.get("sensitivity") == "sensitive"
            status = "active" if self._runtime.memory_mode == "automatic" and not (sensitive and self._sensitive_mode == "ask") else "candidate"
            if conflict is not None and conflict["user_locked"]:
                status = "candidate"
        values["status"] = status
        memory = self._store.create_memory(values, actor=actor, action=action if status == "active" else "candidate_created")
        if status == "active" and conflict is not None:
            self._store.supersede_memory(str(conflict["id"]), str(memory["id"]))
            memory = self._store.get_memory(str(memory["id"])) or memory
        if memory["status"] == "active":
            self._sync_vector(memory)
        return memory

    def _hybrid_retrieve(self, query: str, limit: int) -> list[dict[str, object]]:
        fts = self._store.list_memories(status="active", query=query, limit=max(limit, self._semantic_limit))
        fts_scores = {str(item["id"]): 1.0 / (position + 1) for position, item in enumerate(fts)}
        semantic_scores: dict[str, float] = {}
        candidates = {str(item["id"]): item for item in fts}
        if self.semantic_enabled:
            try:
                for result in self._vector_index.search_sync(query, "memory", self._semantic_limit):
                    semantic_scores[result.item_id] = result.score
                    memory = self._store.get_memory(result.item_id)
                    if memory is not None and memory["status"] == "active":
                        candidates[result.item_id] = memory
            except Exception as exc:
                self._degrade_semantic(exc)
        temporal = self._is_temporal_query(query)
        return self._attach_retrieval(list(candidates.values()), fts_scores, semantic_scores, temporal)[:limit]

    def _attach_retrieval(
        self, memories: list[dict[str, object]], fts_scores: dict[str, float],
        semantic_scores: dict[str, float], temporal: bool,
    ) -> list[dict[str, object]]:
        ranked: list[dict[str, object]] = []
        for memory in memories:
            memory_id = str(memory["id"])
            fts_score = fts_scores.get(memory_id, 0.0)
            semantic_score = max(0.0, semantic_scores.get(memory_id, 0.0))
            temporal_score = self._temporal_score(str(memory["created_at"])) if temporal else 0.0
            score = 0.55 * semantic_score + 0.25 * fts_score + 0.10 * float(memory["importance"]) + 0.10 * float(memory["confidence"]) + temporal_score
            reasons = (["semantic"] if semantic_score else []) + (["fts"] if fts_score else []) + (["temporal"] if temporal else [])
            ranked.append({**memory, "retrieval": {"score": round(score, 4), "semantic_score": round(semantic_score, 4), "fts_score": round(fts_score, 4), "reasons": reasons}})
        return sorted(ranked, key=lambda item: item["retrieval"]["score"], reverse=True)

    def _sync_vector(self, memory: dict[str, object]) -> None:
        if not self.semantic_enabled:
            return
        try:
            self._vector_index.upsert_sync(str(memory["id"]), str(memory["canonical_text"]), "memory")
        except Exception as exc:
            self._degrade_semantic(exc)

    def _delete_vector(self, memory_id: str) -> None:
        if not self.semantic_enabled:
            return
        try:
            self._vector_index.delete_sync(memory_id, "memory")
        except Exception as exc:
            self._degrade_semantic(exc)

    def _degrade_semantic(self, error: Exception) -> None:
        self._semantic_degraded_reason = f"{type(error).__name__}: {error}"[:300]

    @staticmethod
    def _is_temporal_query(query: str) -> bool:
        normalized = query.lower()
        return any(marker in normalized for marker in ("раньше", "вчера", "сегодня", "в прошлый раз", "когда мы", "до этого", "потом", "previously", "yesterday", "last time"))

    @staticmethod
    def _temporal_score(created_at: str) -> float:
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            age_days = max(0.0, (datetime.now(UTC) - created).total_seconds() / 86400)
            return 0.10 * max(0.0, 1.0 - age_days / 365)
        except ValueError:
            return 0.0

    def _resolve_conflict(self, memory_id: str, memory: dict[str, object]) -> None:
        _, conflict = self._match_existing(memory, exclude_id=memory_id)
        if conflict is not None:
            self._store.supersede_memory(str(conflict["id"]), memory_id)

    def _match_existing(self, values: dict[str, object], exclude_id: str | None = None) -> tuple[dict[str, object] | None, dict[str, object] | None]:
        active = self._store.list_memories(status="active", limit=250)
        subject, predicate = str(values["subject"]), str(values["predicate"])
        candidate_value = self._normalize(str(values["value_text"]))
        exact = conflict = None
        for item in active:
            if item["id"] == exclude_id or item["subject"] != subject or item["predicate"] != predicate:
                continue
            if self._normalize(str(item["value_text"])) == candidate_value:
                exact = item
            else:
                conflict = item
        return exact, conflict

    def _validate_sources(self, source_ids: list[str], *, manual: bool) -> None:
        if manual and not source_ids:
            return
        if not source_ids:
            raise ValueError("Memory requires at least one source user message")
        for message_id in source_ids:
            message = self._store.get_message(message_id)
            if message is None or message.role != "user":
                raise ValueError("Memory sources must be existing user messages")

    def _record_retrieval(self, memory: dict[str, object]) -> None:
        self._store.record_memory_retrieval(str(memory["id"]))

    def _extract_candidates(self, text: str) -> list[dict[str, object]]:
        cleaned = text.strip()
        lower = cleaned.lower()
        value: str | None = None
        kind, predicate, importance = "preference", "user_statement", 0.55
        explicit = re.search(r"(?:запомни|remember)\s*[:,]?\s*(.+)", cleaned, flags=re.IGNORECASE)
        name = re.search(r"(?:меня зовут|my name is)\s+(.+)", cleaned, flags=re.IGNORECASE)
        preference = re.search(r"(?:я предпочитаю|i prefer)\s+(.+)", cleaned, flags=re.IGNORECASE)
        interest = re.search(r"(?:я люблю|мне нравится|i like)\s+(.+)", cleaned, flags=re.IGNORECASE)
        correction = re.search(r"(?:теперь я|я больше не)\s+(.+)", cleaned, flags=re.IGNORECASE)
        if explicit:
            value, predicate, importance = explicit.group(1).strip(), "explicit_memory", 0.8
        elif name:
            value, kind, predicate, importance = name.group(1).strip(), "identity", "name", 0.9
        elif preference:
            value, predicate, importance = preference.group(1).strip(), "preferred", 0.7
        elif interest:
            value, kind, predicate = interest.group(1).strip(), "interest", "likes"
        elif correction:
            value, kind, predicate, importance = correction.group(1).strip(), "correction", "current_statement", 0.75
        if not value or len(value) < 2:
            return []
        sensitivity = "sensitive" if any(word in lower for word in self._SENSITIVE_WORDS) else "normal"
        return [{
            "scope": "user_profile", "kind": kind, "subject": "user", "predicate": predicate,
            "value_text": value[:2000], "importance": importance, "confidence": 0.9 if explicit else 0.75,
            "sensitivity": sensitivity,
        }]

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.strip().lower().split())
