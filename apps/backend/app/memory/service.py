"""Policy-controlled writes and FTS retrieval for long-term companion memory."""

from __future__ import annotations

import json
import re
import logging
import time
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.memory.consolidation import CommitmentProposal, ConsolidationResult, FactProposal, TopicProposal
from apps.backend.app.semantic.vector_index import NullVectorIndex, VectorDimensionMismatch
from apps.backend.app.storage.timeline import StoredTimelineMessage, TimelineStore


logger = logging.getLogger(__name__)


class MemoryService:
    """The only component allowed to turn a candidate into canonical memory."""

    _SENSITIVE_WORDS = (
        "здоров", "болез", "диагноз", "аллерг", "лекар", "симптом", "врач",
        "адрес", "паспорт", "карта", "банков", "полит",
    )
    _SECRET_WORDS = ("парол", "password", "код подтверждения", "код из смс", "cvv", "токен", "token", "api key")
    _SINGLE_VALUE_PREDICATES = {"name", "current_statement", "current_goal", "prefers_response_length"}
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
    _EXPLICIT_PREFIX = re.compile(
        r"^.*?\b(?:запомни|remember)(?:\s+(?:пожалуйста|please))?\s*[:,—-]?\s*",
        flags=re.IGNORECASE,
    )
    _DEVELOPER_FACT = re.compile(
        r"^(?:такой\s+факт,?\s*)?(?:что\s+)?тво(?:их|его|й)\s+разработчик(?:ов|и)?\s*(?:(?:зовут|это)\s*)?(.+)$",
        flags=re.IGNORECASE,
    )
    _LEADING_FACT_FILLER = re.compile(r"^(?:такой\s+факт,?\s*)?(?:что\s+)?", flags=re.IGNORECASE)
    _SECRET_SPAN = re.compile(
        r"(?ix)(?:\b(?:и|а)\s+)?(?:(?:мой|твой|наш|my|your)\s+)?"
        r"(?:парол[ья]?|password|код\s+подтверждения|код\s+из\s+смс|cvv|токен|token|api\s+key)\b[^.!?\n]*"
    )
    _RESPONSE_LENGTH_FACT = re.compile(
        r"(?:я\s+)?(?:предпочитаю|люблю)\s+"
        r"((?:(?:коротк|длинн|подробн|лаконич)[^.!?\n]*?)ответ(?:ы|ов)?)",
        flags=re.IGNORECASE,
    )
    _CURRENT_GOAL_FACT = re.compile(
        r"моя\s+(?:текущая\s+)?цель(?:\s+в\s+разработке)?\s*(?:(?:это|—|-)\s*)?"
        r"(.+?)(?=\s+(?:а|и)\s+ещ[её]\b|[.!?\n]|$)",
        flags=re.IGNORECASE,
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
        async_extraction_enabled: bool = True,
        auto_min_confidence: float = 0.85,
        auto_min_importance: float = 0.60,
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
        self._async_extraction_enabled = async_extraction_enabled
        self._auto_min_confidence = auto_min_confidence
        self._auto_min_importance = auto_min_importance
        # A request handler and the background worker share this service.  Keep
        # their read/check/write sequence serialized so the same fact cannot be
        # created twice during a narrow scheduling race.
        self._write_lock = RLock()

    @property
    def llm_extraction_enabled(self) -> bool:
        return self._llm_extraction_enabled

    @property
    def uses_background_extraction(self) -> bool:
        """Whether this service should use the one asynchronous LLM write path."""
        return self._llm_extraction_enabled and self._async_extraction_enabled

    @property
    def incognito(self) -> bool:
        return self._runtime.memory_incognito

    @property
    def store(self) -> TimelineStore:
        return self._store

    def should_persist_timeline(self) -> bool:
        return not self.incognito

    def schedule_extraction(self, message: StoredTimelineMessage | None) -> bool:
        """Queue background extraction without delaying the user-facing turn."""
        if (
            not self.uses_background_extraction
            or not self._enabled
            or self.incognito
            or self._runtime.memory_mode == "off"
            or message is None
            or message.status != "completed"
            or not self.is_eligible_automatic_source(message)
        ):
            return False
        # Consolidation is the sole LLM write path.  The old per-message job
        # was left alongside it during the first v11 draft, which doubled API
        # calls and retried the same malformed model output independently.
        self._store.enqueue_consolidation_job(message.id)
        return True

    @staticmethod
    def is_eligible_automatic_source(
        message: StoredTimelineMessage | None,
    ) -> bool:
        """Exclude overheard and incomplete live speech from factual memory."""
        if message is None:
            return False
        scope = str(message.metadata.get("dialogue_scope", ""))
        if scope in {"ambient", "incomplete"}:
            return False
        decision = message.metadata.get("conversation_decision")
        if isinstance(decision, dict) and decision.get("reason") in {
            "ambient_speech",
            "self_talk",
            "other_person",
            "incomplete_turn",
        }:
            return False
        return True

    def _memory_has_eligible_source(self, memory: dict[str, object]) -> bool:
        source_ids = [str(item) for item in memory.get("source_message_ids", [])]
        if not source_ids:
            return True
        sources = [self._store.get_message(message_id) for message_id in source_ids]
        existing = [source for source in sources if source is not None]
        return not existing or any(
            self.is_eligible_automatic_source(source) for source in existing
        )

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
        # Separate namespaces prevent a free-form topic reflection from being
        # treated as a factual assertion.  Topic and commitment rows use a
        # small common display contract for ContextManager and diagnostics.
        topic_rows = self._store.list_topics(status="active", query=query, limit=limit)
        commitment_rows = self._store.list_commitments(status="open", limit=limit)
        query_terms = set(re.findall(r"[^\W_]+", self._normalize(query), flags=re.UNICODE))
        for topic in topic_rows:
            text = f"{topic['title']} {topic['summary_text']}"
            overlap = len(query_terms & set(re.findall(r"[^\W_]+", self._normalize(text), flags=re.UNICODE)))
            if overlap:
                memories.append({"id": f"topic:{topic['id']}", "namespace": "topic_memory", "predicate": str(topic["title"]), "value_text": str(topic["summary_text"]), "importance": .7, "confidence": 1.0, "status": "active", "source_message_ids": [], "retrieval": {"score": round(.35 + .1 * overlap, 4), "components": {"exact": 0, "fts": overlap, "semantic": 0, "importance": .7}, "reasons": ["topic_fts"]}})
        for commitment in commitment_rows:
            text = f"{commitment['title']} {commitment['details']}"
            overlap = len(query_terms & set(re.findall(r"[^\W_]+", self._normalize(text), flags=re.UNICODE)))
            if overlap or any(marker in self._normalize(query) for marker in ("план", "обещ", "задач", "loop", "обяз")):
                memories.append({"id": f"commitment:{commitment['id']}", "namespace": "commitment_memory", "predicate": str(commitment["title"]), "value_text": str(commitment["details"] or commitment["title"]), "importance": float(commitment["importance"]), "confidence": float(commitment["confidence"]), "status": "active", "source_message_ids": [], "retrieval": {"score": round(.5 + .1 * overlap + .1 * float(commitment["importance"]), 4), "components": {"open_loop": 1, "fts": overlap, "importance": commitment["importance"]}, "reasons": ["open_commitment"]}})
        memories = [
            memory for memory in memories
            if self._memory_has_eligible_source(memory)
        ]
        selected: list[dict[str, object]] = []
        used_tokens = 0
        seen: set[str] = set()
        for memory in sorted(memories, key=lambda item: float(dict(item.get("retrieval", {})).get("score", 0)), reverse=True):
            fingerprint = self._fingerprint(str(memory.get("namespace", "factual_memory")), str(memory["predicate"]), str(memory["value_text"]))
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            estimate = max(1, len(str(memory["value_text"])) // 4)
            if selected and used_tokens + estimate > self._context_max_tokens:
                continue
            used_tokens += estimate
            selected.append(memory)
            if not str(memory["id"]).startswith(("topic:", "commitment:")):
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
            "provider": getattr(getattr(self._vector_index, "embedding_provider", None), "model_id", "none"),
            "fallback_state": "fts_only" if not self.semantic_enabled else "hybrid",
            "considered_ids": [item["id"] for item in items],
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "items": items,
        }

    def extract_from_message(self, message: StoredTimelineMessage | None) -> list[dict[str, object]]:
        if not self._enabled or self.incognito or self._runtime.memory_mode == "off" or message is None:
            return []
        if (
            message.role != "user"
            or message.status != "completed"
            or not self.is_eligible_automatic_source(message)
        ):
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

    def extract_high_precision_from_message(self, message: StoredTimelineMessage | None) -> list[dict[str, object]]:
        """Persist only facts safe enough to acknowledge in the visible turn.

        Background extraction remains the sole automatic LLM write path.  This
        tiny deterministic exception keeps identity and the well-structured
        assistant-developer fact immediate, including the existing Memory
        Center feedback contract.
        """
        if not self._enabled or self.incognito or self._runtime.memory_mode == "off" or message is None:
            return []
        if (
            message.role != "user"
            or message.status != "completed"
            or not self.is_eligible_automatic_source(message)
        ):
            return []
        saved: list[dict[str, object]] = []
        for candidate in self._extract_candidates(message.effective_content):
            if str(candidate.get("predicate")) not in {"name", "developers"}:
                continue
            candidate.update({
                "source_message_ids": [message.id],
                "source_episode_id": message.episode_id,
                "extractor_version": "deterministic-v3-high-precision",
            })
            saved.append(self._apply_candidate(candidate, actor="extractor"))
        return saved

    def apply_llm_candidates(
        self, candidates: list[object], source_message: StoredTimelineMessage | None,
    ) -> list[dict[str, object]]:
        """Validate model proposals through the same policy path as all other writes."""
        if not self._enabled or self.incognito or self._runtime.memory_mode == "off" or source_message is None:
            return []
        if (
            source_message.role != "user"
            or source_message.status != "completed"
            or not self.is_eligible_automatic_source(source_message)
        ):
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
                value_text = self._clean_memory_value(str(candidate["value_text"]))
                predicate = str(candidate["predicate"]).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if kind not in allowed_kinds or confidence < self._llm_min_confidence or not value_text or not predicate:
                continue
            if (
                self._contains_secret(value_text.lower())
                or self._looks_like_secret_value(value_text)
                or self._is_secret_predicate(predicate)
            ):
                # Secrets should never become review items or durable records.
                continue
            sensitivity = str(candidate.get("sensitivity", "normal"))
            is_sensitive = (
                sensitivity == "sensitive"
                or self._contains_sensitive(value_text.lower())
            )
            values = {
                "scope": "user_profile",
                "kind": kind,
                "subject": str(candidate.get("subject", "user"))[:200],
                "predicate": predicate[:200],
                "value_text": value_text[:1000],
                "importance": min(1.0, max(0.0, float(candidate.get("importance", 0.6)))),
                "confidence": min(1.0, max(0.0, confidence)),
                "sensitivity": "sensitive" if is_sensitive else "normal",
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

    def apply_consolidation(self, result: ConsolidationResult, messages: list[StoredTimelineMessage], *, model: str | None = None) -> dict[str, int]:
        """Apply independently valid structured sections without trusting model IDs.

        A bad proposal is recorded as a conflict/review item where possible;
        it must never roll back unrelated, valid proposals from the same pass.
        """
        by_id = {message.id: message for message in messages}
        saved_facts = saved_topics = saved_commitments = conflicts = 0
        for proposal in result.facts:
            source_ids = [item for item in proposal.source_message_ids if item in by_id]
            if not source_ids:
                continue
            source = by_id[source_ids[-1]]
            values = proposal.model_dump()
            values.update({
                "scope": "user_profile", "source_message_ids": source_ids, "source_episode_id": source.episode_id,
                "extractor_version": "consolidation-v11", "extraction_model": model,
                "claim_fingerprint": self._fingerprint(proposal.subject, proposal.predicate, proposal.value_text),
                "source_quality": self._source_quality(source),
            })
            try:
                self._apply_candidate(values, actor="extractor", sync_vector=False)
                saved_facts += 1
            except (KeyError, TypeError, ValueError):
                self._store.create_conflict({"reason": "invalid fact proposal", "proposed_entity_type": "fact", "status": "resolved", "resolution": "discarded"})
                conflicts += 1
        for proposal in result.topics:
            source_ids = [item for item in proposal.source_message_ids if item in by_id]
            try:
                topic = self._apply_topic_proposal(proposal, source_ids)
                if topic:
                    saved_topics += 1
            except (KeyError, TypeError, ValueError):
                self._store.create_conflict({"reason": "invalid topic proposal", "proposed_entity_type": "topic", "status": "resolved", "resolution": "discarded"})
                conflicts += 1
        for proposal in result.commitments:
            source_ids = [item for item in proposal.source_message_ids if item in by_id]
            if not source_ids:
                continue
            try:
                self._store.create_commitment({**proposal.model_dump(), "source_message_ids": source_ids, "source_episode_id": by_id[source_ids[-1]].episode_id, "extractor_version": "consolidation-v11"})
                saved_commitments += 1
            except (KeyError, TypeError, ValueError):
                self._store.create_conflict({"reason": "invalid commitment proposal", "proposed_entity_type": "commitment", "status": "resolved", "resolution": "discarded"})
                conflicts += 1
        for proposal in result.conflicts:
            existing = self._store.get_memory(proposal.existing_id) if proposal.existing_id else None
            if existing is not None and existing.get("user_locked"):
                resolution = "review"
            else:
                resolution = proposal.resolution
            self._store.create_conflict({"existing_entity_type": "fact" if existing else None, "existing_entity_id": proposal.existing_id, "proposed_entity_type": proposal.proposed_kind, "reason": proposal.reason, "status": "open" if resolution == "review" else "resolved", "resolution": resolution})
            conflicts += 1
        return {"facts": saved_facts, "topics": saved_topics, "commitments": saved_commitments, "conflicts": conflicts}

    def extract_resilient_facts_from_message(
        self, message: StoredTimelineMessage | None,
    ) -> list[dict[str, object]]:
        """Store a few obvious facts even if the extractor omitted a clause.

        This is intentionally narrow.  It covers structured preferences, a
        clearly stated current goal and the assistant-developer relation; all
        other memory decisions remain with the extraction model and policy.
        """
        if not self._enabled or self.incognito or self._runtime.memory_mode == "off" or message is None:
            return []
        if (
            message.role != "user"
            or message.status != "completed"
            or not self.is_eligible_automatic_source(message)
        ):
            return []
        text, _ = self.sanitize_for_llm_extraction(message.effective_content)
        # The marker is useful instruction for the LLM, but must never leak
        # into a deterministic value that becomes canonical memory.
        text = text.replace("[секрет удалён]", "")
        saved: list[dict[str, object]] = []
        for candidate in self._extract_resilient_candidates(text)[: self._max_candidates_per_turn]:
            candidate.update({
                "source_message_ids": [message.id],
                "source_episode_id": message.episode_id,
                "extractor_version": "deterministic-v4-resilient",
            })
            saved.append(self._apply_candidate(candidate, actor="extractor"))
        return saved

    def sanitize_for_llm_extraction(self, text: str) -> tuple[str, bool]:
        """Remove secret-bearing spans before they can reach an LLM prompt."""
        sanitized, count = self._SECRET_SPAN.subn("[секрет удалён]", text)
        return sanitized, count > 0

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

    def repair_legacy_response_length_preferences(self) -> list[dict[str, object]]:
        """Merge the old ``preferred`` alias and stale answer-length choices.

        Before background extraction, a deterministic fallback used the generic
        predicate ``preferred``.  It also allowed both old and new response
        length choices to remain active.  Response length is a setting, so the
        newest explicit choice must be the only active one.
        """
        active = [
            item for item in self._store.list_memories(status="active", limit=250)
            if item["subject"] == "user"
            and item["predicate"] in {"preferred", "prefers_response_length"}
            and self._is_response_length_preference(str(item["value_text"]))
        ]
        if not active:
            return []
        active.sort(key=lambda item: (str(item["created_at"]), str(item["id"])))
        latest = active[-1]
        if len(active) == 1 and latest["predicate"] == "prefers_response_length":
            return []
        values = {
            "scope": str(latest["scope"]),
            "kind": "preference",
            "subject": "user",
            "predicate": "prefers_response_length",
            "value_text": str(latest["value_text"]),
            "importance": float(latest["importance"]),
            "confidence": float(latest["confidence"]),
            "sensitivity": str(latest["sensitivity"]),
            "status": "active",
            "source_message_ids": list(latest["source_message_ids"]),
            "source_episode_id": latest["source_episode_id"],
            "extractor_version": "memory-v2-preference-repair",
        }
        target = self._apply_candidate(values, actor="migration", action="legacy_preference_repaired")
        repaired: list[dict[str, object]] = []
        for item in active:
            if item["id"] == target["id"]:
                continue
            current = self._store.get_memory(str(item["id"]))
            if current is not None and current["status"] == "active":
                self._store.supersede_memory(str(item["id"]), str(target["id"]))
                self._schedule_vector_sync(current)
                repaired.append(current)
        return repaired

    def repair_ambiguous_relationship_memories(self) -> list[dict[str, object]]:
        """Move old, inferred social ties out of active prompt context.

        Earlier extractors could turn a loosely mentioned name into a permanent
        relationship.  Preserve the record for review, but do not keep it in
        automatic retrieval.  Explicit user-created memories are never touched.
        """
        repaired: list[dict[str, object]] = []
        for memory in self._store.list_memories(status="active", limit=250):
            if (
                memory["kind"] != "relationship"
                or bool(memory.get("user_locked"))
                or str(memory.get("extractor_version", "")).startswith("manual")
                or self._relationship_is_unambiguous(memory)
            ):
                continue
            demoted = self._store.set_memory_status(
                str(memory["id"]),
                "candidate",
                actor="migration",
                action="ambiguous_relationship_review",
            )
            self._delete_vector(str(memory["id"]))
            repaired.append(demoted)
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
        values = {"scope": "user_profile", "subject": "user", "importance": 0.6, "confidence": 1.0,
                  "sensitivity": "normal", **values, "status": "active", "user_locked": True,
                  "extractor_version": "manual-v1"}
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
        reset_storage = getattr(self._vector_index, "reset_storage_sync", None)
        if callable(reset_storage):
            reset_storage()
            result["chroma_cleanup_pending"] = 1
        elif self.semantic_enabled:
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
        with self._write_lock:
            self._validate_sources(list(values.get("source_message_ids", [])), manual=actor == "user")
            values = {
                **values,
                "subject": self._normalize(str(values["subject"])),
                "predicate": self._normalize(str(values["predicate"])),
            }
            exact, conflict = self._match_existing(values)
            if exact is not None:
                self._store.update_memory(exact["id"], {}, actor="policy", action="retrieved")
                return exact
            status = str(values.get("status", "candidate"))
            if actor == "extractor":
                sensitive = values.get("sensitivity") == "sensitive"
                status = "active" if self._should_auto_activate(values, sensitive) else "candidate"
                if float(values.get("source_quality", 1.0)) < 0.80:
                    # Speech recognition uncertainty is useful evidence, but
                    # never strong enough to silently alter the profile.
                    status = "candidate"
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
        if str(values.get("kind")) == "relationship" and not self._relationship_is_unambiguous(values):
            # Names and social roles are easy to misread in informal dialogue.
            # Keep uncertain ties in Memory Center for review instead of making
            # them permanent context that can distort later answers.
            return False
        mode = "balanced" if self._runtime.memory_mode == "ask" else self._runtime.memory_mode
        if mode == "automatic":
            return True
        if mode != "balanced":
            return False
        if str(values.get("predicate")) in {"name", "explicit_memory", "current_statement"}:
            return True
        return (
            float(values.get("confidence", 0.0)) >= self._auto_min_confidence
            and float(values.get("importance", 0.0)) >= self._auto_min_importance
        )

    def _relationship_is_unambiguous(self, values: dict[str, object]) -> bool:
        subject = str(values.get("subject", ""))
        predicate = str(values.get("predicate", ""))
        if subject == "assistant" and predicate == "developers":
            return True
        if "develop" in predicate:
            return True
        source_ids = list(values.get("source_message_ids", []))
        if len(source_ids) != 1:
            return False
        source = self._store.get_message(str(source_ids[0]))
        if source is None:
            return False
        name = re.escape(str(values.get("value_text", "")).strip())
        if not name:
            return False
        text = self._normalize(source.effective_content)
        direct_patterns = (
            rf"(?:^|[.!?]\s*)(?:это\s+)?мой\s+друг\s+{name}(?:[.!?]|$)",
            rf"(?:^|[.!?]\s*){name}\s*(?:-|—)\s*мой\s+друг(?:[.!?]|$)",
            rf"(?:^|[.!?]\s*)моего\s+друга\s+зовут\s+{name}(?:[.!?]|$)",
        )
        return any(re.search(pattern, text, flags=re.IGNORECASE) is not None for pattern in direct_patterns)

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
            recency = self._temporal_score(str(memory["updated_at"])) * 10
            source_quality = float(memory.get("source_quality", 1.0))
            recent_use_penalty = min(.08, float(memory.get("access_count", 0)) * .002)
            score = 0.45 * semantic_score + 0.22 * fts_score + 0.10 * float(memory["importance"]) + 0.08 * float(memory["confidence"]) + .08 * source_quality + recency + temporal_score - recent_use_penalty
            reasons = (["semantic"] if semantic_score else []) + (["fts"] if fts_score else []) + (["temporal"] if temporal else [])
            ranked.append({**memory, "namespace": "factual_memory", "retrieval": {"score": round(score, 4), "semantic_score": round(semantic_score, 4), "fts_score": round(fts_score, 4), "components": {"exact": 0.0, "fts": round(fts_score, 4), "semantic": round(semantic_score, 4), "importance": float(memory["importance"]), "confidence": float(memory["confidence"]), "recency": round(recency, 4), "source_quality": source_quality, "recent_use_penalty": round(recent_use_penalty, 4)}, "reasons": reasons}})
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
        review = self._store.list_memories(status="candidate", limit=250)
        subject, predicate = str(values["subject"]), str(values["predicate"])
        candidate_value = self._normalize(str(values["value_text"]))
        exact = conflict = None
        for item in [*active, *review]:
            if item["id"] == exclude_id or item["subject"] != subject or item["predicate"] != predicate:
                continue
            if self._normalize(str(item["value_text"])) == candidate_value:
                exact = item
            # A profile name and an explicit correction are single-valued;
            # independent interests and notes must coexist.
            elif item["status"] == "active" and (predicate in self._SINGLE_VALUE_PREDICATES or values.get("cardinality") == "single" or values.get("temporal_semantics") in {"current", "period"}):
                conflict = item
        return exact, conflict

    def _validate_sources(self, source_ids: list[str], *, manual: bool) -> None:
        if manual and not source_ids:
            return
        if not source_ids:
            raise ValueError("Memory requires at least one source user message")
        for message_id in source_ids:
            message = self._store.get_message(message_id)
            if message is None or message.role not in {"user", "assistant"} or message.status != "completed":
                raise ValueError("Memory sources must be completed dialogue messages")

    def _apply_topic_proposal(self, proposal: TopicProposal, source_ids: list[str]) -> dict[str, object] | None:
        if not source_ids:
            return None
        candidates = self._store.list_topics(status="active", query=proposal.title, limit=5)
        target = next((item for item in candidates if self._normalize(str(item["title"])) == self._normalize(proposal.title)), None)
        if proposal.topic_id:
            target = self._store.get_topic(proposal.topic_id)
        if target is not None:
            if target.get("user_locked"):
                return target
            topic = self._store.update_topic(str(target["id"]), {"title": proposal.title, "summary_text": proposal.summary_text}, actor="consolidation")
        else:
            topic = self._store.create_topic({"title": proposal.title, "summary_text": proposal.summary_text, "extractor_version": "consolidation-v11"}, actor="consolidation")
        for source_id in source_ids:
            self._store.link_topic(str(topic["id"]), "message", source_id)
        return topic

    @classmethod
    def _fingerprint(cls, subject: str, predicate: str, value: str) -> str:
        return "|".join(cls._normalize(part) for part in (subject, predicate, value))

    @staticmethod
    def _source_quality(message: StoredTimelineMessage) -> float:
        if message.input_mode != "voice":
            return 1.0
        raw = message.metadata.get("stt_confidence")
        try:
            return max(0.0, min(1.0, float(raw)))
        except (TypeError, ValueError):
            # A missing score is not evidence of uncertainty. Explicit
            # ``stt_uncertain`` is filtered before scheduling; only a supplied
            # low confidence score should force review.
            return 1.0

    def _record_retrieval(self, memory: dict[str, object]) -> None:
        self._store.record_memory_retrieval(str(memory["id"]))

    def _extract_candidates(self, text: str) -> list[dict[str, object]]:
        cleaned = text.strip()
        lower = cleaned.lower()
        value: str | None = None
        kind, predicate, importance = "preference", "user_statement", 0.55
        explicit = self._explicit_fact(cleaned)
        preference = re.search(r"(?:я предпочитаю|i prefer)\s+(.+)", cleaned, flags=re.IGNORECASE)
        interest = re.search(r"(?:я люблю|мне нравится|i like)\s+(.+)", cleaned, flags=re.IGNORECASE)
        correction = re.search(r"(?:теперь я|я больше не)\s+(.+)", cleaned, flags=re.IGNORECASE)
        name = self._extract_name(cleaned)
        developer = self._developer_candidate(cleaned)
        # Identity takes priority over a generic explicit-memory command.
        if name:
            value, kind, predicate, importance = name, "identity", "name", 0.9
        elif developer:
            return [developer]
        elif explicit:
            return [explicit]
        elif preference:
            value = preference.group(1).strip()
            predicate = "prefers_response_length" if self._is_response_length_preference(value) else "prefers"
            importance = 0.7
        elif interest:
            value, kind, predicate = interest.group(1).strip(), "interest", "likes"
        elif correction:
            value, kind, predicate, importance = correction.group(1).strip(), "correction", "current_statement", 0.75
        if not value or len(value) < 2:
            return []
        if self._contains_secret(lower):
            return []
        sensitivity = "sensitive" if self._contains_sensitive(lower) else "normal"
        return [{
            "scope": "user_profile", "kind": kind, "subject": "user", "predicate": predicate,
            "value_text": value[:2000], "importance": importance, "confidence": 0.9 if explicit else 0.75,
            "sensitivity": sensitivity,
        }]

    def _explicit_fact(self, text: str) -> dict[str, object] | None:
        if self._EXPLICIT_PREFIX.match(text) is None:
            return None
        value = self._EXPLICIT_PREFIX.sub("", text).strip()
        value = self._clean_memory_value(value)
        if not value or self._contains_secret(value.lower()):
            return None
        developer = self._developer_candidate(value)
        if developer is not None:
            return developer
        return {
            "scope": "user_profile", "kind": "decision", "subject": "user",
            "predicate": "explicit_memory", "value_text": value[:1000], "importance": 0.8,
            "confidence": 0.9, "sensitivity": "sensitive" if self._contains_sensitive(value.lower()) else "normal",
        }

    def _extract_resilient_candidates(self, text: str) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        developer = self._developer_candidate(text.strip())
        if developer is not None:
            candidates.append(developer)
        length_match = self._RESPONSE_LENGTH_FACT.search(text)
        if length_match is not None:
            value = self._clean_memory_value(length_match.group(1))
            if value:
                candidates.append({
                    "scope": "user_profile", "kind": "preference", "subject": "user",
                    "predicate": "prefers_response_length", "value_text": value[:200],
                    "importance": 0.75, "confidence": 0.97, "sensitivity": "normal",
                })
        goal_match = self._CURRENT_GOAL_FACT.search(text)
        if goal_match is not None:
            value = self._clean_memory_value(goal_match.group(1))
            if value and not self._contains_secret(value.lower()):
                candidates.append({
                    "scope": "user_profile", "kind": "goal", "subject": "user",
                    "predicate": "current_goal", "value_text": value[:500],
                    "importance": 0.8, "confidence": 0.97, "sensitivity": "normal",
                })
        return candidates

    def _developer_candidate(self, text: str) -> dict[str, object] | None:
        developer_match = self._DEVELOPER_FACT.match(text.strip())
        if developer_match is None:
            return None
        names = developer_match.group(1).strip(" \t,;:.—-")
        if not names or self._contains_secret(names.lower()):
            return None
        return {
            "scope": "relationship", "kind": "relationship", "subject": "assistant",
            "predicate": "developers", "value_text": names[:200], "importance": 0.8,
            "confidence": 0.95, "sensitivity": "normal",
        }

    @classmethod
    def _contains_sensitive(cls, text: str) -> bool:
        return any(word in text for word in cls._SENSITIVE_WORDS)

    @classmethod
    def _contains_secret(cls, text: str) -> bool:
        return any(word in text for word in cls._SECRET_WORDS)

    @classmethod
    def _is_secret_predicate(cls, predicate: str) -> bool:
        normalized = predicate.lower().replace("_", " ")
        return cls._contains_secret(normalized) or any(
            marker in normalized for marker in ("credential", "credentials", "auth", "access key")
        )

    @staticmethod
    def _looks_like_secret_value(value: str) -> bool:
        normalized = " ".join(value.lower().split())
        if re.fullmatch(r"[0-9\s-]{4,}", normalized):
            return True
        number_words = {
            "ноль", "один", "одна", "два", "две", "три", "четыре", "пять",
            "шесть", "семь", "восемь", "девять", "zero", "one", "two", "three",
            "four", "five", "six", "seven", "eight", "nine",
        }
        tokens = re.findall(r"[a-zа-яё]+", normalized, flags=re.IGNORECASE)
        return len(tokens) >= 4 and all(token in number_words for token in tokens)

    @staticmethod
    def _is_response_length_preference(value: str) -> bool:
        normalized = value.lower()
        return "ответ" in normalized or any(marker in normalized for marker in ("коротк", "длинн", "лаконич"))

    def _clean_memory_value(self, value: str) -> str:
        cleaned = self._LEADING_FACT_FILLER.sub("", value.strip()).strip(" \t,;:.—-")
        if len(cleaned) < 3 or re.match(r"^(?:это[, ]+)?он\b", cleaned, flags=re.IGNORECASE):
            return ""
        return cleaned

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
