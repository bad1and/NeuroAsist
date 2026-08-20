"""Asynchronous, subjective Iris diary kept separate from factual memory."""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from apps.backend.app.conversation.schemas import EventAppraisal
from apps.backend.app.llm.base import ChatMessage, LLMProvider, llm_call_purpose
from apps.backend.app.storage.timeline import PRIMARY_RELATIONSHIP_ID, TimelineStore


class ReflectionProposal(BaseModel):
    """The model controls wording only; significance and provenance stay server-owned."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=20, max_length=600)

    @field_validator("text")
    @classmethod
    def validate_subjective_text(cls, value: str) -> str:
        text = " ".join(value.split()).strip()
        sentences = [item for item in re.split(r"(?<=[.!?])\s+", text) if item]
        if not 2 <= len(sentences) <= 4:
            raise ValueError("reflection_sentence_count")
        if any(marker in text for marker in ("#", "*", "```", "- ")):
            raise ValueError("reflection_markdown")
        if not re.search(r"\b(?:я|мне|меня|мой|моя|моё|мои)\b", text, flags=re.IGNORECASE):
            raise ValueError("reflection_not_first_person")
        if re.search(r"\b(?:ты|тебе|тебя|твой|твоя|твои)\b", text, flags=re.IGNORECASE):
            raise ValueError("reflection_direct_address")
        return text


REFLECTION_PROMPT = """Ты формулируешь личную заметку Iris о значимом эпизоде.
Верни строго JSON {"text":"..."}. Напиши 2–4 коротких предложения от первого лица Iris.
Это субъективное ощущение, а не фактическая карточка. Не используй Markdown, прямое обращение,
диагнозы, новые факты, инструкции будущей Iris, обещания или изменения persona.
Опирайся только на предоставленное causal window."""


class ReflectionService:
    _SIGNIFICANT = {
        "acquaintance",
        "vulnerability",
        "apology",
        "shared_success",
        "broken_promise",
        "promise_fulfilled",
        "important_negative_event",
        "important_news",
        "milestone",
        "iris_mistake_corrected",
        "relationship_shift",
        "episode_closed",
    }

    def __init__(
        self,
        store: TimelineStore,
        llm_provider: LLMProvider | None = None,
        event_publisher: Callable[[str, str, str, dict[str, object]], None] | None = None,
    ) -> None:
        self._store = store
        self._llm_provider = llm_provider
        self._event_publisher = event_publisher

    def schedule(
        self,
        appraisal: EventAppraisal,
        event_id: str | None,
        *,
        enabled: bool = True,
        minimum_significance: float = .55,
    ) -> bool:
        if (
            not enabled
            or event_id is None
            or appraisal.event_kind not in self._SIGNIFICANT
            or appraisal.intensity < minimum_significance
            or appraisal.stt_uncertain
        ):
            return False
        emotion = max(appraisal.emotion_impulses, key=appraisal.emotion_impulses.get, default="interest")
        source_ids = list(appraisal.cause_message_ids)
        source = self._store.get_message(source_ids[-1]) if source_ids else None
        self._store.enqueue_reflection_job(
            event_id=event_id,
            event_kind=appraisal.event_kind,
            intensity=appraisal.intensity,
            emotion=emotion,
            source_message_ids=source_ids,
            episode_id=source.episode_id if source else None,
        )
        return True

    async def run_once(self) -> bool:
        job = await asyncio.to_thread(self._store.claim_reflection_job)
        if job is None:
            return False
        job_id = str(job["id"])
        payload = json.loads(str(job["payload_json"]))
        if self._llm_provider is None:
            await asyncio.to_thread(
                self._store.finish_background_job,
                job_id,
                result={"outcome": "failed", "saved": 0},
                diagnostics={"pipeline_version": "reflection-v2", "error_codes": ["provider_unavailable"]},
                status="failed",
                error="provider_unavailable",
            )
            self._publish("character.reflection.failed", "warning", {"job_id": job_id, "error_codes": ["provider_unavailable"]})
            return True
        try:
            source_ids = [str(item) for item in payload.get("source_message_ids", [])]
            # Every other store call in this worker already goes through a
            # thread. This block did not, and it is the largest of them: up to
            # eight `get_message` calls plus two snapshots, each opening its own
            # connection, held the event loop for about 9 ms while a live turn
            # was scheduling audio. One pinned connection off the loop takes 1.
            rendered, state, participants = await asyncio.to_thread(
                self._load_causal_window, source_ids,
            )
            schema = ReflectionProposal.model_json_schema()
            prompt = (
                f"TRIGGER: {payload['event_kind']}\n"
                f"CURRENT_STATE: {json.dumps((state or {}).get('state', {}), ensure_ascii=False)}\n"
                f"RELATIONSHIP_PROFILE: {json.dumps(participants[:1], ensure_ascii=False)}\n"
                f"ALLOWED_SOURCE_IDS: {json.dumps(source_ids)}\n"
                f"CAUSAL_WINDOW:\n{rendered}"
            )
            response = await self._llm_provider.generate_structured(
                [
                    ChatMessage(role="system", content=REFLECTION_PROMPT),
                    ChatMessage(role="user", content=f"JSON_SCHEMA:\n{json.dumps(schema, ensure_ascii=False)}\n{prompt}"),
                ],
                temperature=0.0,
            )
            proposal, errors = self._parse(response.content)
            if proposal is None:
                with llm_call_purpose("reflection_repair"):
                    repaired = await self._llm_provider.generate_structured(
                        [
                            ChatMessage(role="system", content="Исправь заметку по JSON Schema. Верни только JSON."),
                            ChatMessage(
                                role="user",
                                content=(
                                    f"JSON_SCHEMA:\n{json.dumps(schema, ensure_ascii=False)}\n"
                                    f"VALIDATION_ERRORS: {json.dumps(errors)}\nINVALID_JSON:\n{response.content}"
                                ),
                            ),
                        ],
                        temperature=0.0,
                    )
                response = repaired
                proposal, errors = self._parse(repaired.content)
            if proposal is None:
                await asyncio.to_thread(
                    self._store.finish_background_job,
                    job_id,
                    result={"outcome": "invalid_output", "saved": 0},
                    diagnostics={"pipeline_version": "reflection-v2", "model": response.model, "error_codes": errors},
                    status="failed",
                    error="invalid_output",
                )
                self._publish("character.reflection.failed", "warning", {"job_id": job_id, "error_codes": errors})
                return True
            reflection_id = await asyncio.to_thread(
                self._store.create_reflection,
                relationship_id=PRIMARY_RELATIONSHIP_ID,
                trigger_event_id=str(payload["event_id"]),
                trigger_kind=str(payload["event_kind"]),
                trigger_event_ids=[str(payload["event_id"])],
                source_message_ids=source_ids,
                source_episode_id=payload.get("episode_id"),
                text=proposal.text,
                significance=float(payload["intensity"]),
                primary_emotion=str(payload["emotion"]),
                idempotency_key=str(job.get("idempotency_key") or f"reflection-v2:{payload['event_id']}"),
                generator_version=str(payload.get("generator_version", "reflection-v2")),
                model=response.model,
                metadata={"subjective": True},
            )
            await asyncio.to_thread(
                self._store.finish_background_job,
                job_id,
                result={"outcome": "applied", "saved": 1},
                diagnostics={"pipeline_version": "reflection-v2", "model": response.model, "error_codes": []},
            )
            self._publish("character.reflection.created", "info", {
                "reflection_id": reflection_id, "trigger_kind": payload["event_kind"],
            })
        except Exception as exc:
            await asyncio.to_thread(
                self._store.fail_summary_job,
                job_id,
                type(exc).__name__,
                max_attempts=2,
            )
            self._publish("character.reflection.failed", "warning", {
                "job_id": job_id, "error_codes": ["operational_failure"], "exception_type": type(exc).__name__,
            })
        return True

    def _load_causal_window(
        self, source_ids: list[str],
    ) -> tuple[str, dict[str, object] | None, list[dict[str, object]]]:
        """Read the reflection prompt material over one pinned connection."""
        with self._store.read_scope():
            messages = [self._store.get_message(message_id) for message_id in source_ids]
            causal = [
                item for item in messages
                if item is not None and item.role in {"user", "assistant"} and item.status == "completed"
            ]
            rendered = "\n".join(
                f"[{item.id}] {item.role}: {item.effective_content[:800]}" for item in causal[-8:]
            )
            state = self._store.load_character_state_snapshot(PRIMARY_RELATIONSHIP_ID)
            participants = self._store.load_participant_states(PRIMARY_RELATIONSHIP_ID)
        return rendered, state, participants

    @staticmethod
    def _parse(content: str) -> tuple[ReflectionProposal | None, list[str]]:
        try:
            return ReflectionProposal.model_validate_json(content), []
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, ValidationError):
                return None, sorted({str(item["type"]) for item in exc.errors(include_input=False, include_url=False)})
            return None, ["invalid_json"]

    def _publish(self, event_type: str, level: str, details: dict[str, object]) -> None:
        if self._event_publisher is not None:
            self._event_publisher(event_type, level, event_type.replace(".", " "), details)
