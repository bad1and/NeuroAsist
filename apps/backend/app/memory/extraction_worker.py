"""Asynchronous, policy-controlled long-term memory consolidation."""

from __future__ import annotations

import asyncio
import json
import logging
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


MEMORY_EXTRACTION_PROMPT = """Ты — Archivist, внутренний модуль консолидации памяти AI-компаньона.
Верни только JSON вида {"facts":[],"topics":[],"commitments":[],"conflicts":[],"decisions":[]}.
Используй только явные сведения из завершённого прямого диалога. В окне есть user и Iris;
обе роли допустимы как provenance для общих решений, обещаний и milestones. Не используй
ambient/incomplete/echo, секреты, догадки или субъективные оценки. Каждый факт содержит kind,
subject, predicate, value_text, importance, confidence, sensitivity, source_message_ids,
cardinality (single|multi) и temporal_semantics (atemporal|current|period). Topics имеют
title, summary_text, optional topic_id, source_message_ids. Commitments имеют kind
(milestone|promise|decision|open_loop), title, details, status, importance, confidence,
source_message_ids. Conflicts имеют existing_id, proposed_kind, reason и resolution.
Не добавляй неизвестные ключи. source_message_ids выбирай только из списка ALLOWED_SOURCE_IDS.
Факты и темы о пользователе обязаны иметь хотя бы один user source. Реплика Iris сама по себе
не доказывает ни факт о пользователе, ни её выдуманное текущее занятие/состояние; обещания,
решения и общие milestones из assistant source оформляй только как commitments.
Decisions содержат внутренние accept|reject|clarify, reason, optional predicate и
clarification_id; они не создают память и нужны только для диагностики решения.
Если сохранять нечего, верни пустые массивы.
Если Iris задала вопрос, чтобы уточнить факт или получить согласие на чувствительную
память, не предлагай этот факт до следующего прямого ответа пользователя. Явное «да»,
«верно» или исправленное значение подтверждает факт; явное отрицание его отклоняет.
Не создавай факты для ручной проверки: сомнительные малозначимые и временные сведения
просто пропускай.
Предпочитай канонические predicates из каталога:
user.name, assistant.developer, assistant.developer_count, user.likes_category,
user.likes_game, user.game_detail, user.preference, user.note, user.relationship.friend,
user.current_mood, user.current_activity, user.current_goal,
user.prefers_response_length. Не создавай новый topic для одноразовой проверки памяти,
имени или статуса разработчика; используй существующую игровую тему при наличии.

Короткий корректный пример:
{"facts":[{"kind":"identity","subject":"user","predicate":"name","value_text":"Федор",
"importance":0.9,"confidence":0.99,"sensitivity":"normal","source_message_ids":["msg-1"],
"cardinality":"single","temporal_semantics":"atemporal"}],
"topics":[{"title":"Игровые предпочтения","summary_text":"Любит шутеры.","source_message_ids":["msg-2"]}],
"commitments":[],"conflicts":[],"decisions":[]}"""


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
            context = await asyncio.to_thread(self._store.memory_consolidation_context, message_id, 40)
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
            schema = ConsolidationResult.model_json_schema()
            extraction_messages = [
                ChatMessage(role="system", content=MEMORY_EXTRACTION_PROMPT),
                ChatMessage(
                    role="user",
                    content=(
                        f"JSON_SCHEMA:\n{json.dumps(schema, ensure_ascii=False)}\n"
                        f"ALLOWED_SOURCE_IDS: {json.dumps([item.id for item in context])}\n{prompt}"
                    ),
                ),
            ]
            response = await self._llm_provider.generate_structured(extraction_messages, temperature=0.0)
            result, errors = self._parse_partial_result(response.content)
            if errors:
                with llm_call_purpose("memory_repair"):
                    repair = await self._llm_provider.generate_structured(
                        [
                            ChatMessage(
                                role="system",
                                content="Исправь ответ по исходной JSON Schema. Верни только исправленный JSON без пояснений.",
                            ),
                            ChatMessage(
                                role="user",
                                content=(
                                    f"JSON_SCHEMA:\n{json.dumps(schema, ensure_ascii=False)}\n"
                                    f"VALIDATION_ERRORS:\n{json.dumps(errors, ensure_ascii=False)}\n"
                                    f"INVALID_JSON:\n{response.content}"
                                ),
                            ),
                        ],
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
        limits = {"facts": 30, "topics": 12, "commitments": 20, "conflicts": 20, "decisions": 30}
        for section, model in models.items():
            raw_items = payload.get(section, [])
            if not isinstance(raw_items, list):
                errors.append({"section": section, "index": -1, "code": "not_array", "path": f"$.{section}"})
                continue
            if len(raw_items) > limits[section]:
                errors.append({"section": section, "index": limits[section], "code": "too_long", "path": f"$.{section}"})
            for index, item in enumerate(raw_items[:limits[section]]):
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
        rendered: list[str] = []
        user_burst: list[tuple[str, str]] = []

        def flush_user_burst() -> None:
            if not user_burst:
                return
            ids = ",".join(message_id for message_id, _ in user_burst)
            text = "\n".join(text for _, text in user_burst)
            rendered.append(f"[{ids}] user-burst: {text}")
            user_burst.clear()

        for item in context[-20:]:
            safe, was_redacted = self._memory_service.sanitize_for_llm_extraction(item.effective_content)
            redacted = redacted or was_redacted
            if item.role == "user":
                user_burst.append((item.id, safe))
            else:
                flush_user_burst()
                rendered.append(f"[{item.id}] {item.role}: {safe}")
        flush_user_burst()
        if not rendered:
            safe, was_redacted = self._memory_service.sanitize_for_llm_extraction(current_text)
            redacted = redacted or was_redacted
            rendered.append(f"[unknown] user: {safe}")
        topics = self._store.list_topics(status="active", limit=50)
        topic_catalog = [
            {"id": item["id"], "title": item["title"]}
            for item in topics
        ]
        return (
            "Существующие темы (переиспользуй topic_id вместо дубля):\n"
            + json.dumps(topic_catalog, ensure_ascii=False)
            + "\nОкно завершённого диалога:\n"
            + "\n".join(rendered)
        ), redacted

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
