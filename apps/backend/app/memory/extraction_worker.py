"""Asynchronous, policy-controlled long-term memory consolidation."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError
from apps.backend.app.llm.base import ChatMessage, LLMProvider, llm_call_purpose
from apps.backend.app.memory.consolidation import (
    CommitmentProposal,
    ConflictProposal,
    ConsolidationResult,
    FactProposal,
    MemoryDecisionProposal,
    TopicProposal,
)
from apps.backend.app.storage.timeline import TimelineStore


logger = logging.getLogger(__name__)


MEMORY_EXTRACTION_PROMPT = """Ты — Archivist памяти AI-компаньона. Верни только JSON-объект;
корневые ключи: facts, topics, commitments, conflicts, decisions. Отсутствующие секции — [].

Извлекай только новые явные сведения завершённого прямого диалога. Не сохраняй секреты,
догадки, оценки, ambient/incomplete/echo и малозначимые временные детали. Факт или topic о
пользователе требует source_message_ids хотя бы одной строки U. Строка I сама не доказывает
факт о пользователе/текущем состоянии Iris; обещания, решения и milestones Iris — commitment.
ID источников бери только из квадратных скобок DIALOGUE. Если сохранять нечего — все [].
Вопрос Iris не подтверждает факт или sensitive-память: жди прямое «да», исправление либо
значение пользователя; отрицание отклоняет предложение.

Компактный контракт (неизвестные ключи запрещены; поля с default можно опускать):
facts<=8: {kind,subject="user",predicate,value_text,importance=.6,confidence=.7,
sensitivity="normal|sensitive",source_message_ids,cardinality="single|multi",
temporal_semantics="atemporal|current|period"}
topics<=3: {title,summary_text="",topic_id?,source_message_ids}; переиспользуй релевантный
topic_id из TOPICS и не создавай topic для проверки имени/памяти/статуса разработчика.
commitments<=4: {kind="milestone|promise|decision|open_loop",title,details="",
status="open|completed|cancelled",importance=.6,confidence=.7,source_message_ids}
conflicts<=4: {existing_id?,proposed_kind,reason,resolution="supersede|review|coexist"}
decisions<=6: {action="accept|reject|clarify",reason,predicate?,clarification_id?}; диагностика,
не память. Предпочитай predicates: name, assistant.developer, assistant.developer_count,
likes_category, likes_game, game_detail, preference, note, relationship.friend, current_mood,
current_activity, current_goal, prefers_response_length."""

MEMORY_REPAIR_PROMPT = """Исправь JSON без пояснений. Разрешены только корневые массивы
facts,topics,commitments,conflicts,decisions с лимитами 8/3/4/4/6. Сохрани валидные элементы.
Используй пути ошибок; удали неизвестные поля и элементы, которые нельзя исправить надёжно."""

# DeepSeek tokenization varies by language. Two Unicode characters per token
# deliberately overestimates the mixed Russian/JSON payloads observed in local
# traces. The hard character ceiling covers both system and user content.
MEMORY_EXTRACTION_INPUT_CHAR_BUDGET = 4_200
MEMORY_EXTRACTION_ESTIMATED_TOKEN_BUDGET = 2_100
MEMORY_REPAIR_INPUT_CHAR_BUDGET = 3_000
_CONTEXT_MESSAGE_LIMIT = 12
_TOPIC_CANDIDATE_LIMIT = 50
_TOPIC_SHORTLIST_LIMIT = 5
_SECTION_LIMITS = {
    "facts": 8,
    "topics": 3,
    "commitments": 4,
    "conflicts": 4,
    "decisions": 6,
}
_TOPIC_STOP_WORDS = {
    "это", "как", "что", "для", "или", "мне", "меня", "тебя", "тебе", "очень",
    "сейчас", "только", "когда", "который", "которая", "есть", "была", "будет",
    "the", "and", "that", "this", "with", "from", "have", "about",
}


class MemoryExtractionWorker:
    """Processes durable jobs after the visible chat or voice reply was sent."""

    def __init__(self, store: TimelineStore, memory_service, llm_provider: LLMProvider,
                 event_publisher: Callable[[str, str, str, dict[str, object]], None] | None = None,
                 reflection_policy: Callable[[], tuple[bool, float]] | None = None,
                 respect_coalescing: bool = False) -> None:
        self._store = store
        self._memory_service = memory_service
        self._llm_provider = llm_provider
        self._event_publisher = event_publisher
        self._reflection_policy = reflection_policy or (lambda: (True, .55))
        self._respect_coalescing = respect_coalescing

    async def run_once(self) -> bool:
        job = await asyncio.to_thread(
            self._store.claim_memory_extraction_job, self._respect_coalescing,
        )
        if job is None:
            return False
        job_id = str(job["id"])
        try:
            payload = json.loads(str(job["payload_json"]))
            message_id = str(payload.get("end_message_id") or payload.get("message_id"))
            message = await asyncio.to_thread(self._store.get_message, message_id)
            if message is None or message.status != "completed" or not self._memory_service.is_eligible_automatic_source(message):
                await asyncio.to_thread(
                    self._store.finish_background_job,
                    job_id,
                    result={"outcome": "no_candidates", "proposed": 0, "saved": 0, "discarded": 0},
                    diagnostics={"pipeline_version": "v12", "error_codes": ["ineligible_source"]},
                )
                return True
            # The store returns the unprocessed delta plus one prior turn. A
            # modest row cap protects a first-ever run from replaying a long
            # episode; the prompt builder applies the stricter character cap.
            context = await asyncio.to_thread(
                self._store.memory_consolidation_context,
                message_id,
                _CONTEXT_MESSAGE_LIMIT,
            )
            run_key = str(job.get("idempotency_key") or job_id)
            existing_run = await asyncio.to_thread(self._store.consolidation_run, run_key)
            if existing_run is not None:
                previous = dict(existing_run.get("result", {}))
                await asyncio.to_thread(
                    self._store.finish_background_job,
                    job_id,
                    result={**previous, "idempotent_noop": True},
                    diagnostics={
                        "pipeline_version": payload.get("pipeline_version", "v12"),
                        "error_codes": [],
                    },
                )
                return True
            prompt, redacted_secrets = self._format_input(message.effective_content, context)
            extraction_messages = [
                ChatMessage(role="system", content=MEMORY_EXTRACTION_PROMPT),
                ChatMessage(role="user", content=prompt),
            ]
            self._assert_request_budget(
                extraction_messages,
                MEMORY_EXTRACTION_INPUT_CHAR_BUDGET,
            )
            response = await self._llm_provider.generate_structured(extraction_messages, temperature=0.0)
            result, errors = self._parse_partial_result(response.content)
            if errors:
                with llm_call_purpose("memory_repair"):
                    repair = await self._llm_provider.generate_structured(
                        self._repair_messages(response.content, errors),
                        temperature=0.0,
                    )
                repaired, repair_errors = self._parse_partial_result(repair.content)
                if self._proposal_count(repaired) >= self._proposal_count(result):
                    result, errors, response = repaired, repair_errors, repair
            latest_user = next((item for item in reversed(context) if item.role == "user"), None)
            result = self._replace_legacy_source(
                result,
                latest_user.id if latest_user is not None else message.id,
            )
            result, provenance_errors = self._filter_provenance(result, context)
            errors.extend(provenance_errors)
            proposed = len(result.facts) + len(result.topics) + len(result.commitments) + len(result.conflicts)
            pipeline_version = str(payload.get("pipeline_version") or "v12")
            diagnostics = {
                "pipeline_version": pipeline_version,
                "model": response.model,
                "error_codes": sorted({str(item["code"]) for item in errors}),
                "section_errors": errors,
                "redacted_secret_count": int(redacted_secrets),
                "request_chars": sum(len(item.content) for item in extraction_messages),
                "request_token_estimate": (
                    sum(len(item.content) for item in extraction_messages) + 1
                ) // 2,
            }
            if proposed == 0 and errors:
                outcome = "invalid_output"
                result_payload = {"outcome": outcome, "proposed": 0, "saved": 0, "discarded": len(errors)}
                await asyncio.to_thread(
                    self._store.record_consolidation_run,
                    idempotency_key=str(job.get("idempotency_key") or job_id),
                    end_message_id=message_id,
                    pipeline_version=pipeline_version,
                    messages=context,
                    status=outcome,
                    result=result_payload,
                    section_errors=errors,
                )
                await asyncio.to_thread(
                    self._store.finish_background_job,
                    job_id,
                    result=result_payload,
                    diagnostics=diagnostics,
                    status="failed",
                    error="invalid_output",
                )
                self._publish("memory.invalid_output", "warning", "Memory consolidation output was invalid", {
                    "job_id": job_id, "model": response.model, "error_codes": diagnostics["error_codes"],
                })
                return True
            if str(job.get("type")) == "memory_consolidation":
                run_outcome = "partial" if errors else ("applied" if proposed else "no_candidates")
                counts = await asyncio.to_thread(
                    self._memory_service.apply_consolidation,
                    result,
                    context,
                    model=response.model,
                    run_record={
                        "idempotency_key": run_key,
                        "end_message_id": message_id,
                        "pipeline_version": pipeline_version,
                        "status": run_outcome,
                        "result": {
                            "outcome": run_outcome,
                            "proposed": proposed,
                            "discarded": len(errors),
                        },
                        "section_errors": errors,
                    },
                )
                # Deterministic high-precision extraction is intentionally
                # local and fills only a few explicit facts the model may have
                # skipped. It remains safe to run with consolidation because
                # policy deduplicates the canonical claim.
                source_user = next((item for item in reversed(context) if item.role == "user"), None)
                resilient = await asyncio.to_thread(self._memory_service.extract_resilient_facts_from_message, source_user)
                saved = sum(counts.values()) + len(resilient)
                await asyncio.to_thread(self._schedule_acquaintance, context)
            else:
                # v10 compatibility: legacy jobs still write only facts, but
                # their outputs are parsed through v11's strict schema.
                facts = [fact.model_dump(exclude={"source_message_ids", "cardinality", "temporal_semantics"}) for fact in result.facts]
                applied = await asyncio.to_thread(self._memory_service.apply_llm_candidates, facts, message)
                resilient = await asyncio.to_thread(self._memory_service.extract_resilient_facts_from_message, message)
                saved = len(applied) + len(resilient)
            outcome = "partial" if errors else ("applied" if proposed or saved else "no_candidates")
            result_payload = {
                "outcome": outcome,
                "proposed": proposed,
                "saved": saved,
                "discarded": len(errors),
                "counts": counts if str(job.get("type")) == "memory_consolidation" else {"facts": saved},
            }
            await asyncio.to_thread(
                self._store.record_consolidation_run,
                idempotency_key=str(job.get("idempotency_key") or job_id),
                end_message_id=message_id,
                pipeline_version=pipeline_version,
                messages=context,
                status=outcome,
                result=result_payload,
                section_errors=errors,
            )
            await asyncio.to_thread(
                self._store.finish_background_job,
                job_id,
                result=result_payload,
                diagnostics=diagnostics,
            )
            event_type = {
                "partial": "memory.consolidation_partial",
                "no_candidates": "memory.no_candidates",
            }.get(outcome, "memory.consolidation_completed")
            self._publish(event_type, "warning" if outcome == "partial" else "info", "Background memory consolidation finished", {
                "job_id": job_id, "outcome": outcome, "proposed": proposed, "saved": saved,
                "model": response.model, "error_codes": diagnostics["error_codes"],
            })
        except Exception as exc:
            logger.warning("Background memory consolidation failed: exception_type=%s", type(exc).__name__)
            await asyncio.to_thread(
                self._store.fail_summary_job,
                job_id,
                str(exc),
                max_attempts=2,
            )
            self._publish("memory.consolidation_failed", "warning", "Background memory consolidation failed", {"job_id": job_id, "exception_type": type(exc).__name__})
        return True

    @staticmethod
    def _parse_candidates(content: str) -> list[object]:
        """Compatibility helper retained for integrations using the old worker API."""
        return [fact.model_dump() for fact in MemoryExtractionWorker._parse_result(content).facts]

    @staticmethod
    def _parse_result(content: str) -> ConsolidationResult:
        result, errors = MemoryExtractionWorker._parse_partial_result(content)
        if errors:
            raise ValueError("Memory extractor returned invalid structured output")
        return result

    @staticmethod
    def _parse_partial_result(content: str) -> tuple[ConsolidationResult, list[dict[str, object]]]:
        """Validate sections item-by-item so one bad proposal cannot discard siblings."""
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return ConsolidationResult(), [{"section": "root", "index": -1, "code": "invalid_json", "path": "$"}]
        if not isinstance(payload, dict):
            return ConsolidationResult(), [{"section": "root", "index": -1, "code": "non_object", "path": "$"}]
        if "memories" in payload or "memory_candidates" in payload:
            raw = payload.get("memories", payload.get("memory_candidates", []))
            if not isinstance(raw, list):
                return ConsolidationResult(), [{"section": "facts", "index": -1, "code": "not_array", "path": "$.memories"}]
            payload = {
                "facts": [{**item, "source_message_ids": item.get("source_message_ids", ["legacy-source"]),
                            "cardinality": item.get("cardinality", "multi"),
                            "temporal_semantics": item.get("temporal_semantics", "atemporal")}
                          for item in raw if isinstance(item, dict)],
                "topics": [], "commitments": [], "conflicts": [],
                "decisions": [],
            }
        unknown = sorted(set(payload) - {"facts", "topics", "commitments", "conflicts", "decisions"})
        models: dict[str, type[Any]] = {
            "facts": FactProposal,
            "topics": TopicProposal,
            "commitments": CommitmentProposal,
            "conflicts": ConflictProposal,
            "decisions": MemoryDecisionProposal,
        }
        accepted: dict[str, list[object]] = {key: [] for key in models}
        errors: list[dict[str, object]] = [
            {"section": "root", "index": -1, "code": "extra_forbidden", "path": f"$.{key}"}
            for key in unknown
        ]
        for section, model in models.items():
            raw_items = payload.get(section, [])
            if not isinstance(raw_items, list):
                errors.append({"section": section, "index": -1, "code": "not_array", "path": f"$.{section}"})
                continue
            limit = _SECTION_LIMITS[section]
            if len(raw_items) > limit:
                errors.append({"section": section, "index": limit, "code": "too_long", "path": f"$.{section}"})
            for index, item in enumerate(raw_items[:limit]):
                try:
                    accepted[section].append(model.model_validate(item))
                except ValidationError as exc:
                    for detail in exc.errors(include_input=False, include_url=False):
                        location = ".".join(str(part) for part in detail.get("loc", ()))
                        errors.append({
                            "section": section,
                            "index": index,
                            "code": str(detail.get("type", "validation_error")),
                            "path": f"$.{section}[{index}]" + (f".{location}" if location else ""),
                        })
        return ConsolidationResult(**accepted), errors

    @staticmethod
    def _proposal_count(result: ConsolidationResult) -> int:
        return (
            len(result.facts) + len(result.topics) + len(result.commitments)
            + len(result.conflicts) + len(result.decisions)
        )

    def _filter_provenance(
        self,
        result: ConsolidationResult,
        context: list,
    ) -> tuple[ConsolidationResult, list[dict[str, object]]]:
        allowed = {
            item.id for item in context
            if item.role in {"user", "assistant"} and self._memory_service.is_eligible_automatic_source(item)
        }
        roles = {item.id: item.role for item in context}
        payload = result.model_dump()
        errors: list[dict[str, object]] = []
        for section in ("facts", "topics", "commitments"):
            kept: list[dict[str, object]] = []
            for index, item in enumerate(payload[section]):
                source_ids = item.get("source_message_ids", [])
                requires_user_evidence = section in {"facts", "topics"}
                has_user_evidence = any(roles.get(source_id) == "user" for source_id in source_ids)
                if (
                    source_ids
                    and all(source_id in allowed for source_id in source_ids)
                    and (not requires_user_evidence or has_user_evidence)
                ):
                    kept.append(item)
                else:
                    errors.append({
                        "section": section,
                        "index": index,
                        "code": "invalid_provenance",
                        "path": f"$.{section}[{index}].source_message_ids",
                    })
            payload[section] = kept
        return ConsolidationResult.model_validate(payload), errors

    @staticmethod
    def _replace_legacy_source(result: ConsolidationResult, message_id: str) -> ConsolidationResult:
        """Make a legacy ``memories`` response usable in the v11 window."""
        payload = result.model_dump()
        for fact in payload["facts"]:
            if fact.get("source_message_ids") == ["legacy-source"]:
                fact["source_message_ids"] = [message_id]
        return ConsolidationResult.model_validate(payload)

    def _format_input(self, current_text: str, context) -> tuple[str, bool]:
        redacted = False
        safe_messages: list[tuple[str, str, str]] = []
        for item in context[-_CONTEXT_MESSAGE_LIMIT:]:
            safe, was_redacted = self._memory_service.sanitize_for_llm_extraction(item.effective_content)
            redacted = redacted or was_redacted
            if item.role in {"user", "assistant"}:
                safe_messages.append((item.id, "U" if item.role == "user" else "I", safe))
        if not safe_messages:
            safe, was_redacted = self._memory_service.sanitize_for_llm_extraction(current_text)
            redacted = redacted or was_redacted
            safe_messages.append(("unknown", "U", safe))

        # Topic reuse should follow the new user delta, not lexical noise from
        # the overlap turn. The newest eligible user line is the job's source.
        topic_query = next(
            (text for _, role, text in reversed(safe_messages) if role == "U"),
            "",
        )
        topics = self._shortlist_topics(topic_query)
        topic_catalog = [
            {
                "id": str(item["id"]),
                "title": self._clip_text(str(item["title"]), 120),
            }
            for item in topics
        ]
        header = (
            "TOPICS:"
            + json.dumps(topic_catalog, ensure_ascii=False, separators=(",", ":"))
            + "\nDIALOGUE oldest->newest (U=user,I=Iris):\n"
        )
        dialogue_budget = (
            MEMORY_EXTRACTION_INPUT_CHAR_BUDGET
            - len(MEMORY_EXTRACTION_PROMPT)
            - len(header)
        )
        if dialogue_budget < 80:
            # Topic titles are hints, never more important than source text.
            topic_catalog = []
            header = "TOPICS:[]\nDIALOGUE oldest->newest (U=user,I=Iris):\n"
            dialogue_budget = (
                MEMORY_EXTRACTION_INPUT_CHAR_BUDGET
                - len(MEMORY_EXTRACTION_PROMPT)
                - len(header)
            )
        dialogue = self._render_dialogue(safe_messages, dialogue_budget)
        return header + dialogue, redacted

    def _shortlist_topics(self, query: str) -> list[dict[str, object]]:
        query_tokens = self._meaningful_tokens(query)
        if not query_tokens:
            return []
        candidates = self._store.list_topics(
            status="active",
            limit=_TOPIC_CANDIDATE_LIMIT,
            include_details=False,
        )
        query_stems = {token[:4] for token in query_tokens if len(token) >= 4}
        ranked: list[tuple[int, int, dict[str, object]]] = []
        for index, item in enumerate(candidates):
            topic_text = f"{item.get('title', '')} {item.get('summary_text', '')}"
            topic_tokens = self._meaningful_tokens(topic_text)
            exact = len(query_tokens & topic_tokens)
            topic_stems = {token[:4] for token in topic_tokens if len(token) >= 4}
            stems = len(query_stems & topic_stems)
            score = exact * 3 + stems
            if score:
                ranked.append((score, -index, item))
        ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        return [item for _, _, item in ranked[:_TOPIC_SHORTLIST_LIMIT]]

    @staticmethod
    def _meaningful_tokens(text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)
            if len(token) >= 3 and token not in _TOPIC_STOP_WORDS
        }

    @classmethod
    def _render_dialogue(
        cls,
        messages: list[tuple[str, str, str]],
        budget: int,
    ) -> str:
        selected = list(messages)
        while selected:
            minimum = sum(len(f"[{message_id}] {role}: \n") + 24 for message_id, role, _ in selected)
            if minimum <= budget or len(selected) == 1:
                break
            selected.pop(0)
        if not selected or budget <= 0:
            return ""

        prefixes = [f"[{message_id}] {role}: " for message_id, role, _ in selected]
        content_budget = max(budget - sum(len(prefix) + 1 for prefix in prefixes), 0)
        rendered: list[str] = []
        for index, ((_, _, text), prefix) in enumerate(zip(selected, prefixes, strict=True)):
            remaining_items = len(selected) - index
            allowance = content_budget // remaining_items if remaining_items else 0
            clipped = cls._clip_text(text, allowance)
            content_budget -= len(clipped)
            rendered.append(prefix + clipped)
        return "\n".join(rendered)

    @staticmethod
    def _clip_text(text: str, limit: int) -> str:
        if limit <= 0:
            return ""
        if len(text) <= limit:
            return text
        if limit <= 3:
            return text[:limit]
        if limit < 24:
            return text[: limit - 1] + "…"
        tail = max(8, limit // 3)
        head = limit - tail - 1
        return text[:head] + "…" + text[-tail:]

    @classmethod
    def _repair_messages(
        cls,
        invalid_json: str,
        errors: list[dict[str, object]],
    ) -> list[ChatMessage]:
        compact_errors = [
            {"path": item.get("path"), "code": item.get("code")}
            for item in errors[:16]
        ]
        prefix = (
            "ERRORS:"
            + json.dumps(compact_errors, ensure_ascii=False, separators=(",", ":"))
            + "\nBAD_JSON:\n"
        )
        invalid_budget = (
            MEMORY_REPAIR_INPUT_CHAR_BUDGET
            - len(MEMORY_REPAIR_PROMPT)
            - len(prefix)
        )
        messages = [
            ChatMessage(role="system", content=MEMORY_REPAIR_PROMPT),
            ChatMessage(
                role="user",
                content=prefix + cls._clip_text(invalid_json, max(invalid_budget, 0)),
            ),
        ]
        cls._assert_request_budget(messages, MEMORY_REPAIR_INPUT_CHAR_BUDGET)
        return messages

    @staticmethod
    def _assert_request_budget(messages: list[ChatMessage], budget: int) -> None:
        request_chars = sum(len(item.content) for item in messages)
        if request_chars > budget:
            raise ValueError(
                f"Memory LLM input exceeds hard budget: {request_chars}>{budget}"
            )

    def _publish(self, event_type: str, level: str, message: str, details: dict[str, object]) -> None:
        if self._event_publisher is not None:
            self._event_publisher(event_type, level, message, details)

    def _schedule_acquaintance(self, context: list) -> bool:
        """Queue one diary note once an episode has identity plus personal interest."""
        enabled, minimum = self._reflection_policy()
        if not enabled or not context:
            return False
        episode_id = context[-1].episode_id
        if not episode_id:
            return False
        memories = [
            item for item in self._store.list_memories(status="active", limit=500)
            if item.get("source_episode_id") == episode_id
        ]
        has_identity = any(item.get("predicate") == "name" for item in memories)
        has_interest = any(
            item.get("kind") in {"interest", "preference"}
            or item.get("predicate") in {"likes", "likes_category", "prefers"}
            for item in memories
        )
        if not (has_identity and has_interest):
            return False
        source_ids = [
            item.id for item in context
            if item.role in {"user", "assistant"} and self._memory_service.is_eligible_automatic_source(item)
        ]
        self._store.enqueue_reflection_job(
            event_id=f"acquaintance:{episode_id}",
            event_kind="acquaintance",
            intensity=max(.65, minimum),
            emotion="interest",
            source_message_ids=source_ids,
            episode_id=episode_id,
        )
        return True
