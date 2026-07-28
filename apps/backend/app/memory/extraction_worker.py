"""Asynchronous, policy-controlled long-term memory consolidation."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable

from apps.backend.app.llm.base import ChatMessage, LLMProvider
from apps.backend.app.memory.consolidation import ConsolidationResult
from apps.backend.app.storage.timeline import TimelineStore


logger = logging.getLogger(__name__)


MEMORY_EXTRACTION_PROMPT = """Ты — внутренний модуль консолидации памяти AI-компаньона.
Верни только JSON вида {"facts":[],"topics":[],"commitments":[],"conflicts":[]}.
Используй только явные сведения из завершённого прямого диалога. В окне есть user и Iris;
обе роли допустимы как provenance для общих решений, обещаний и milestones. Не используй
ambient/incomplete/echo, секреты, догадки или субъективные оценки. Каждый факт содержит kind,
subject, predicate, value_text, importance, confidence, sensitivity, source_message_ids,
cardinality (single|multi) и temporal_semantics (atemporal|current|period). Topics имеют
title, summary_text, optional topic_id, source_message_ids. Commitments имеют kind
(milestone|promise|decision|open_loop), title, details, status, importance, confidence,
source_message_ids. Conflicts имеют existing_id, proposed_kind, reason и resolution.
Не добавляй неизвестные ключи. Если сохранять нечего, верни пустые массивы."""


class MemoryExtractionWorker:
    """Processes durable jobs after the visible chat or voice reply was sent."""

    def __init__(self, store: TimelineStore, memory_service, llm_provider: LLMProvider,
                 event_publisher: Callable[[str, str, str, dict[str, object]], None] | None = None) -> None:
        self._store = store
        self._memory_service = memory_service
        self._llm_provider = llm_provider
        self._event_publisher = event_publisher

    async def run_once(self) -> bool:
        job = await asyncio.to_thread(self._store.claim_memory_extraction_job)
        if job is None:
            return False
        job_id = str(job["id"])
        try:
            payload = json.loads(str(job["payload_json"]))
            message_id = str(payload.get("end_message_id") or payload.get("message_id"))
            message = await asyncio.to_thread(self._store.get_message, message_id)
            if message is None or message.status != "completed" or not self._memory_service.is_eligible_automatic_source(message):
                await asyncio.to_thread(self._store.complete_summary_job, job_id)
                return True
            context = await asyncio.to_thread(self._store.memory_extraction_context, message_id, 20)
            prompt, redacted_secrets = self._format_input(message.effective_content, context)
            response = await self._llm_provider.generate([
                ChatMessage(role="system", content=MEMORY_EXTRACTION_PROMPT),
                ChatMessage(role="user", content=prompt),
            ])
            try:
                result = self._parse_result(response.content)
            except ValueError:
                # One, and only one, repair retry for malformed structured output.
                response = await self._llm_provider.generate([
                    ChatMessage(role="system", content="Исправь JSON по указанной строгой схеме. Верни только JSON."),
                    ChatMessage(role="user", content=prompt),
                ])
                try:
                    result = self._parse_result(response.content)
                except ValueError:
                    # The repair budget is exhausted.  Invalid structured
                    # output is not an operational failure: no canonical data
                    # was changed, so complete the idempotent job instead of
                    # creating noisy retry loops every few seconds.
                    await asyncio.to_thread(self._store.complete_summary_job, job_id)
                    self._publish("memory.invalid_structured_output", "warning", "Memory consolidation output was discarded", {
                        "job_id": job_id, "model": response.model, "repair_exhausted": True,
                    })
                    return True
            result = self._replace_legacy_source(result, message.id)
            proposed = len(result.facts) + len(result.topics) + len(result.commitments) + len(result.conflicts)
            if str(job.get("type")) == "memory_consolidation":
                counts = await asyncio.to_thread(self._memory_service.apply_consolidation, result, context, model=response.model)
                # Deterministic high-precision extraction is intentionally
                # local and fills only a few explicit facts the model may have
                # skipped. It remains safe to run with consolidation because
                # policy deduplicates the canonical claim.
                source_user = next((item for item in reversed(context) if item.role == "user"), None)
                resilient = await asyncio.to_thread(self._memory_service.extract_resilient_facts_from_message, source_user)
                saved = sum(counts.values()) + len(resilient)
            else:
                # v10 compatibility: legacy jobs still write only facts, but
                # their outputs are parsed through v11's strict schema.
                facts = [fact.model_dump(exclude={"source_message_ids", "cardinality", "temporal_semantics"}) for fact in result.facts]
                applied = await asyncio.to_thread(self._memory_service.apply_llm_candidates, facts, message)
                resilient = await asyncio.to_thread(self._memory_service.extract_resilient_facts_from_message, message)
                saved = len(applied) + len(resilient)
            await asyncio.to_thread(self._store.complete_summary_job, job_id)
            self._publish("memory.consolidation_completed", "info", "Background memory consolidation completed", {
                "job_id": job_id, "proposed": proposed, "saved": saved, "model": response.model,
                "redacted_secrets": redacted_secrets,
            })
        except Exception as exc:
            logger.warning("Background memory consolidation failed: exception_type=%s", type(exc).__name__)
            await asyncio.to_thread(self._store.fail_summary_job, job_id, str(exc))
            self._publish("memory.consolidation_failed", "warning", "Background memory consolidation failed", {"job_id": job_id, "exception_type": type(exc).__name__})
        return True

    @staticmethod
    def _parse_candidates(content: str) -> list[object]:
        """Compatibility helper retained for integrations using the old worker API."""
        return [fact.model_dump() for fact in MemoryExtractionWorker._parse_result(content).facts]

    @staticmethod
    def _parse_result(content: str) -> ConsolidationResult:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("Memory extractor returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("Memory extractor returned a non-object JSON value")
        if "memories" in payload or "memory_candidates" in payload:
            raw = payload.get("memories", payload.get("memory_candidates", []))
            if not isinstance(raw, list):
                raise ValueError("Memory extractor memories must be an array")
            payload = {
                "facts": [{**item, "source_message_ids": item.get("source_message_ids", ["legacy-source"]),
                            "cardinality": item.get("cardinality", "multi"),
                            "temporal_semantics": item.get("temporal_semantics", "atemporal")}
                          for item in raw if isinstance(item, dict)],
                "topics": [], "commitments": [], "conflicts": [],
            }
        try:
            return ConsolidationResult.model_validate(payload)
        except Exception as exc:
            raise ValueError("Memory extractor returned invalid structured output") from exc

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
        for item in context[-20:]:
            safe, was_redacted = self._memory_service.sanitize_for_llm_extraction(item.effective_content)
            redacted = redacted or was_redacted
            rendered.append(f"[{item.id}] {item.role}: {safe}")
        if not rendered:
            safe, was_redacted = self._memory_service.sanitize_for_llm_extraction(current_text)
            redacted = redacted or was_redacted
            rendered.append(f"[unknown] user: {safe}")
        return "Окно завершённого диалога:\n" + "\n".join(rendered), redacted

    def _publish(self, event_type: str, level: str, message: str, details: dict[str, object]) -> None:
        if self._event_publisher is not None:
            self._event_publisher(event_type, level, message, details)
