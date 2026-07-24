"""Asynchronous, policy-controlled long-term memory extraction."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable

from apps.backend.app.llm.base import ChatMessage, LLMProvider
from apps.backend.app.storage.timeline import TimelineStore


logger = logging.getLogger(__name__)


MEMORY_EXTRACTION_PROMPT = """Ты — внутренний модуль долговременной памяти AI-компаньона.
Верни только один JSON-объект вида {"memories": [...]}.

Извлекай исключительно явно сказанные пользователем, самодостаточные и полезные в будущем
факты. Подходят: имя и способ обращения, устойчивые предпочтения, цели и проекты,
ограничения, навыки, интересы, отношения, решения и исправления. Не сохраняй приветствия,
одноразовое настроение, случайные детали, предположения, оценки личности или информацию из
реплики ассистента. Если сохранять нечего, верни {"memories": []}.

Каждый элемент должен иметь: kind, subject, predicate, value_text, importance (0..1),
confidence (0..1), sensitivity (normal|sensitive). Используй subject="user", если факт о
пользователе. Медицинские, финансовые, адресные, политические данные и пароли всегда помечай
sensitivity="sensitive". Не используй местоимения без референта, «пользователь сказал» и
«запомни» в value_text. Максимум 3 разных факта.

Примеры:
«Я предпочитаю короткие ответы» → {"kind":"preference","subject":"user","predicate":"prefers_response_length","value_text":"короткие ответы","importance":0.7,"confidence":0.95,"sensitivity":"normal"}
«В этом месяце хочу закончить память NeuroAsist» → {"kind":"goal","subject":"user","predicate":"current_goal","value_text":"закончить память NeuroAsist в этом месяце","importance":0.8,"confidence":0.9,"sensitivity":"normal"}
"""


class MemoryExtractionWorker:
    """Processes durable jobs after the visible chat or voice reply was sent."""

    def __init__(
        self,
        store: TimelineStore,
        memory_service,
        llm_provider: LLMProvider,
        event_publisher: Callable[[str, str, str, dict[str, object]], None] | None = None,
    ) -> None:
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
            message_id = str(json.loads(str(job["payload_json"]))["message_id"])
            message = await asyncio.to_thread(self._store.get_message, message_id)
            if message is None or message.role != "user" or message.status != "completed":
                await asyncio.to_thread(self._store.complete_summary_job, job_id)
                return True
            response = await self._llm_provider.generate([
                ChatMessage(role="system", content=MEMORY_EXTRACTION_PROMPT),
                ChatMessage(role="user", content=f"Текст пользователя:\n{message.effective_content}"),
            ])
            candidates = self._parse_candidates(response.content)
            saved = await asyncio.to_thread(self._memory_service.apply_llm_candidates, candidates, message)
            await asyncio.to_thread(self._store.complete_summary_job, job_id)
            self._publish(
                "memory.extraction_completed",
                "info",
                "Background memory extraction completed",
                {"message_id": message_id, "proposed": len(candidates), "saved": len(saved), "model": response.model},
            )
        except Exception as exc:
            logger.warning("Background memory extraction failed: exception_type=%s", type(exc).__name__)
            await asyncio.to_thread(self._store.fail_summary_job, job_id, str(exc))
            self._publish(
                "memory.extraction_failed",
                "warning",
                "Background memory extraction failed",
                {"job_id": job_id, "exception_type": type(exc).__name__},
            )
        return True

    @staticmethod
    def _parse_candidates(content: str) -> list[object]:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("Memory extractor returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("Memory extractor returned a non-object JSON value")
        candidates = payload.get("memories", payload.get("memory_candidates", []))
        if not isinstance(candidates, list):
            raise ValueError("Memory extractor memories must be an array")
        return candidates[:3]

    def _publish(self, event_type: str, level: str, message: str, details: dict[str, object]) -> None:
        if self._event_publisher is not None:
            self._event_publisher(event_type, level, message, details)
