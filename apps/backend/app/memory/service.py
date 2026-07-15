"""Policy-controlled writes and FTS retrieval for long-term companion memory."""

from __future__ import annotations

import json
import re
import logging
import time
from datetime import UTC, datetime
from typing import Any

from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.semantic.vector_index import NullVectorIndex, VectorDimensionMismatch
from apps.backend.app.storage.timeline import StoredTimelineMessage, TimelineStore


logger = logging.getLogger(__name__)


class MemoryService:
    """The only component allowed to turn a candidate into canonical memory."""

    _SENSITIVE_WORDS = ("здоров", "болез", "диагноз", "адрес", "паспорт", "карта", "парол", "полит")
    _NAME_PREFIX = re.compile(
        r"(?:\bменя\s+зовут\b|\bмо[её]\s+имя(?:\s+(?:это|[-—:]))?\b|\bmy\s+name\s+is\b|\bcall\s+me\b)",
        flags=re.IGNORECASE,
    )
    _NAME_TOKEN = re.compile(r"^[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё'’-]{1,39}$")
    _NAME_STOP_WORDS = {
        "и", "а", "но", "я", "мне", "это", "теперь", "запомни", "remember",
        "and", "but", "i", "this", "please",
    }
    _IDENTITY_QUERY_MARKERS = (
        "как меня зовут", "помнишь мое имя", "помнишь моё имя", "как меня называть",
        "кто я", "ты помнишь имя", "my name", "remember my name", "what is my name",
        "call me", "who am i",
    )

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
        llm_extraction_enabled: bool = False,
        llm_min_confidence: float = 0.70,
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
        self._llm_extraction_enabled = llm_extraction_enabled
        self._llm_min_confidence = llm_min_confidence

    @property
    def llm_extraction_enabled(self) -> bool:
        return self._llm_extraction_enabled

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
        if self._is_identity_query(normalized_query):
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
        started = time.perf_counter()
        items = self.retrieve(query, limit)
        return {
            "query": query,
            "semantic_enabled": self.semantic_enabled,
            "semantic_degraded_reason": self._semantic_degraded_reason,
            "backend": getattr(self._vector_index, "backend", "null"),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "items": items,
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
                "extractor_version": "deterministic-v2",
            })
            saved.append(self._apply_candidate(candidate, actor="extractor"))
        return saved

    def apply_llm_candidates(
        self, candidates: list[object], source_message: StoredTimelineMessage | None,
    ) -> list[dict[str, object]]:
        """Validate model proposals through the same policy path as all other writes."""
        if not self._enabled or self.incognito or self._runtime.memory_mode == "off" or source_message is None:
            return []
        if source_message.role != "user" or source_message.status != "completed":
            return []
        allowed_kinds = {
            "identity", "preference", "relationship", "goal", "constraint", "skill", "interest",
            "episode", "decision", "correction", "open_loop", "shared_milestone",
        }
        saved: list[dict[str, object]] = []
        for raw_candidate in candidates[: self._max_candidates_per_turn]:
            candidate = raw_candidate.model_dump() if hasattr(raw_candidate, "model_dump") else raw_candidate
            if not isinstance(candidate, dict):
                continue
            try:
                kind = str(candidate["kind"]).strip().lower()
                confidence = float(candidate.get("confidence", 0))
                value_text = str(candidate["value_text"]).strip()
                predicate = str(candidate["predicate"]).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if kind not in allowed_kinds or confidence < self._llm_min_confidence or not value_text or not predicate:
                continue
            sensitivity = str(candidate.get("sensitivity", "normal"))
            values = {
                "scope": "user_profile",
                "kind": kind,
                "subject": str(candidate.get("subject", "user"))[:200],
                "predicate": predicate[:200],
                "value_text": value_text[:1000],
                "importance": min(1.0, max(0.0, float(candidate.get("importance", 0.6)))),
                "confidence": min(1.0, max(0.0, confidence)),
                "sensitivity": "sensitive" if sensitivity == "sensitive" else "normal",
                "source_message_ids": [source_message.id],
                "source_episode_id": source_message.episode_id,
                "extractor_version": "deepseek-character-v1",
            }
            try:
                memory = self._apply_candidate(values, actor="extractor", sync_vector=False)
            except (KeyError, TypeError, ValueError):
                logger.warning("Discarded invalid LLM memory candidate")
                continue
            saved.append(memory)
            if memory["status"] == "active":
                self._schedule_vector_sync(memory)
        return saved

    def repair_legacy_identity_candidates(self) -> list[dict[str, object]]:
        """Repair only malformed V0.5 name candidates from their source messages.

        The original candidate text is never trusted: a fresh valid name is
        extracted from its provenance, then the old candidate is superseded.
        Re-running this method is safe because repaired items are no longer
        candidates.
        """
        repaired: list[dict[str, object]] = []
        candidates = sorted(
            self._store.list_memories(status="candidate", limit=250),
            key=lambda item: str(item["created_at"]),
        )
        for candidate in candidates:
            if candidate["predicate"] != "name" or candidate["extractor_version"] != "deterministic-v1":
                continue
            source_ids = list(candidate["source_message_ids"])
            if len(source_ids) != 1:
                continue
            source = self._store.get_message(source_ids[0])
            value = self._extract_name(source.effective_content) if source is not None else None
            if value is None:
                continue
            values = {
                "scope": "user_profile", "kind": "identity", "subject": "user", "predicate": "name",
                "value_text": value, "importance": 0.9, "confidence": 0.9, "sensitivity": "normal",
                "status": "active", "source_message_ids": source_ids,
                "source_episode_id": source.episode_id, "extractor_version": "deterministic-v2-repair",
            }
            repaired_memory = self._apply_candidate(values, actor="migration", action="legacy_identity_repaired")
            self._store.supersede_memory(str(candidate["id"]), str(repaired_memory["id"]))
            repaired.append(repaired_memory)
        return repaired

    @staticmethod
    def memory_update(memory: dict[str, object]) -> dict[str, str]:
        status = str(memory["status"])
        return {
            "id": str(memory["id"]),
            "status": status,
            "action": "saved" if status == "active" else "review" if status == "candidate" else "updated",
            "predicate": str(memory["predicate"]),
        }

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

    def reset_all(self) -> dict[str, int]:
        result = self._store.reset_companion_data()
        if self.semantic_enabled:
            try:
                self._vector_index.rebuild_sync("memory")
                self._vector_index.rebuild_sync("episode_summary")
            except Exception as exc:
                self._degrade_semantic(exc)
        return result

    def index_episode_summary(self, summary: dict[str, object] | None) -> None:
        if not summary or not self.semantic_enabled:
            return
        try:
            self._vector_index.upsert_sync(str(summary["id"]), str(summary["summary_text"]), "episode_summary")
        except Exception as exc:
            self._degrade_semantic(exc)

    def _apply_candidate(
        self, values: dict[str, object], *, actor: str, action: str = "candidate_created", sync_vector: bool = True,
    ) -> dict[str, object]:
        self._validate_sources(list(values.get("source_message_ids", [])), manual=actor == "user")
        values = {**values, "subject": self._normalize(str(values["subject"])), "predicate": self._normalize(str(values["predicate"]))}
        exact, conflict = self._match_existing(values)
        if exact is not None:
            self._store.update_memory(exact["id"], {}, actor="policy", action="retrieved")
            return exact
        status = str(values.get("status", "candidate"))
        if actor == "extractor":
            sensitive = values.get("sensitivity") == "sensitive"
            status = "active" if self._should_auto_activate(values, sensitive) else "candidate"
            if conflict is not None and conflict["user_locked"]:
                status = "candidate"
        values["status"] = status
        memory = self._store.create_memory(values, actor=actor, action=action if status == "active" else "candidate_created")
        if status == "active" and conflict is not None:
            self._store.supersede_memory(str(conflict["id"]), str(memory["id"]))
            self._schedule_vector_sync(conflict)
            memory = self._store.get_memory(str(memory["id"])) or memory
        if sync_vector and memory["status"] == "active":
            self._sync_vector(memory)
        return memory

    def _schedule_vector_sync(self, memory: dict[str, object]) -> None:
        """Queue index work durably so a crash cannot lose a Chroma update."""
        if not self.semantic_enabled:
            return
        self._store.enqueue_memory_index_job(str(memory["id"]))

    def sync_next_index_job(self) -> bool:
        job = self._store.claim_memory_index_job()
        if job is None:
            return False
        try:
            memory_id = str(json.loads(str(job["payload_json"]))["memory_id"])
            memory = self._store.get_memory(memory_id)
            if memory is not None and memory["status"] == "active":
                self._vector_index.upsert_sync(str(memory["id"]), str(memory["canonical_text"]), "memory")
            else:
                self._vector_index.delete_sync(memory_id, "memory")
            self._store.complete_summary_job(str(job["id"]))
        except Exception as exc:
            self._degrade_semantic(exc)
            self._store.fail_summary_job(str(job["id"]), str(exc))
        return True

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

    def _should_auto_activate(self, values: dict[str, object], sensitive: bool) -> bool:
        if sensitive and self._sensitive_mode == "ask":
            return False
        mode = "balanced" if self._runtime.memory_mode == "ask" else self._runtime.memory_mode
        if mode == "automatic":
            return True
        return mode == "balanced" and str(values.get("predicate")) in {"name", "explicit_memory", "current_statement"}

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
            # A profile name and an explicit correction are single-valued;
            # independent preferences and explicit notes must coexist.
            elif predicate in {"name", "current_statement"}:
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
        preference = re.search(r"(?:я предпочитаю|i prefer)\s+(.+)", cleaned, flags=re.IGNORECASE)
        interest = re.search(r"(?:я люблю|мне нравится|i like)\s+(.+)", cleaned, flags=re.IGNORECASE)
        correction = re.search(r"(?:теперь я|я больше не)\s+(.+)", cleaned, flags=re.IGNORECASE)
        name = self._extract_name(cleaned)
        # Identity takes priority over a generic explicit-memory command.
        if name:
            value, kind, predicate, importance = name, "identity", "name", 0.9
        elif explicit:
            value, predicate, importance = explicit.group(1).strip(), "explicit_memory", 0.8
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

    @classmethod
    def _extract_name(cls, text: str) -> str | None:
        match = cls._NAME_PREFIX.search(text)
        if match is None:
            return None
        suffix = text[match.end():].lstrip(" \t:,-—–")
        segment = re.split(r"[,.!?;:\n—–-]", suffix, maxsplit=1)[0]
        tokens: list[str] = []
        for raw in segment.split():
            token = raw.strip("\"'“”()[]{}")
            if not token:
                continue
            if token.lower() in cls._NAME_STOP_WORDS:
                break
            if not cls._NAME_TOKEN.fullmatch(token):
                break
            tokens.append(token)
            if len(tokens) == 3:
                break
        if not tokens:
            return None
        return " ".join(tokens)

    @classmethod
    def _is_identity_query(cls, normalized_query: str) -> bool:
        return any(marker in normalized_query for marker in cls._IDENTITY_QUERY_MARKERS)

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.strip().lower().split())
