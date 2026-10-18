from __future__ import annotations

import asyncio
import json

from apps.backend.app.llm.base import LLMProvider, LLMResponse
from apps.backend.app.memory.consolidation import ConsolidationResult
from apps.backend.app.memory.extraction_worker import (
    MEMORY_EXTRACTION_INPUT_CHAR_BUDGET,
    MEMORY_EXTRACTION_MAX_INPUT_CHARS,
    MEMORY_EXTRACTION_PROMPT,
    MEMORY_REPAIR_INPUT_CHAR_BUDGET,
    MemoryExtractionWorker,
)
from apps.backend.app.memory.service import MemoryService
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineStore


class CaptureProvider(LLMProvider):
    def __init__(self, content: str | list[str]) -> None:
        self._content = [content] if isinstance(content, str) else list(content)
        self.calls: list[list] = []

    async def generate(self, messages):
        self.calls.append(messages)
        content = self._content[min(len(self.calls) - 1, len(self._content) - 1)]
        return LLMResponse(content=content, model="memory-budget-test")


def _service(tmp_path):
    store = TimelineStore(tmp_path / "memory-budget.sqlite3")
    store.init_db()
    service = MemoryService(
        store,
        RuntimeSettings(memory_mode="automatic"),
        llm_extraction_enabled=True,
        async_extraction_enabled=True,
    )
    return store, service


def test_large_unprocessed_window_is_bounded_per_call_without_source_loss(
    tmp_path,
) -> None:
    store, service = _service(tmp_path)
    for index in range(20):
        store.create_topic({
            "title": "Игровые предпочтения" if index == 7 else f"Архивная тема {index}",
            "summary_text": (
                "Шутеры и кооперативные игры"
                if index == 7
                else f"Несвязанный старый материал раздела {index}"
            ),
        })

    latest_user = None
    for index in range(16):
        user, _ = store.append_message(
            role="user",
            content=(
                ("very-old-marker " if index == 0 else "")
                + f"Старый разговор номер {index}. "
                + "Подробность без долговременного значения. " * 7
            ),
            input_mode="text",
        )
        latest_user = user
        store.append_message(
            role="assistant",
            content=f"Ответ Iris номер {index}. " + "Контекст ответа. " * 6,
            input_mode="text",
            reply_to_message_id=user.id,
        )
    current, _ = store.append_message(
        role="user",
        content=(
            "запомни latest-head: мне важны шутеры и кооперативные игры. "
            + "Содержательная деталь текущего сообщения. " * 80
            + " latest-tail"
        ),
        input_mode="text",
    )
    assert latest_user is not None
    provider = CaptureProvider(
        '{"facts":[],"topics":[],"commitments":[],"conflicts":[],"decisions":[]}'
    )
    service.schedule_extraction(current)

    assert asyncio.run(MemoryExtractionWorker(store, service, provider).run_once()) is True

    assert len(provider.calls) > 1
    assert all(sum(len(item.content) for item in request) <= MEMORY_EXTRACTION_MAX_INPUT_CHARS for request in provider.calls)
    submitted = "\n".join(request[-1].content for request in provider.calls)
    assert "JSON_SCHEMA" not in submitted
    assert "latest-head" in submitted and "latest-tail" in submitted
    assert "very-old-marker" in submitted
    assert submitted.count("Содержательная деталь текущего сообщения.") == 80
    assert "Игровые предпочтения" in submitted
    assert "Архивная тема" not in next(request[-1].content for request in provider.calls if "latest-head" in request[-1].content)
    assert all(request[-1].content.count('"id":') <= 9 for request in provider.calls)


def test_short_everyday_turn_keeps_one_compact_call(tmp_path) -> None:
    store, service = _service(tmp_path)
    source, _ = store.append_message(role="user", content="Моя сестра Аня живёт в Туле", input_mode="text")
    service.schedule_extraction(source)
    provider = CaptureProvider('{"facts":[]}')
    assert asyncio.run(MemoryExtractionWorker(store, service, provider).run_once())
    assert len(provider.calls) == 1
    assert sum(len(item.content) for item in provider.calls[0]) <= MEMORY_EXTRACTION_INPUT_CHAR_BUDGET


def test_context_contains_only_new_delta_and_one_prior_turn(tmp_path) -> None:
    store, service = _service(tmp_path)
    old_user, _ = store.append_message(
        role="user", content="old-marker should not return", input_mode="text",
    )
    old_reply, _ = store.append_message(
        role="assistant", content="old reply", input_mode="text",
        reply_to_message_id=old_user.id,
    )
    prior_user, _ = store.append_message(
        role="user", content="prior-turn-marker", input_mode="text",
    )
    prior_reply, _ = store.append_message(
        role="assistant", content="prior reply marker", input_mode="text",
        reply_to_message_id=prior_user.id,
    )
    store.record_consolidation_run(
        idempotency_key="covered-prior",
        end_message_id=prior_user.id,
        pipeline_version="test",
        messages=[old_user, old_reply, prior_user, prior_reply],
        status="no_candidates",
        result={"outcome": "no_candidates"},
        section_errors=[],
    )
    delta_user, _ = store.append_message(
        role="user", content="delta-one-marker", input_mode="text",
    )
    store.append_message(
        role="assistant", content="delta reply marker", input_mode="text",
        reply_to_message_id=delta_user.id,
    )
    current, _ = store.append_message(
        role="user", content="запомни delta-two-marker", input_mode="text",
    )
    provider = CaptureProvider(
        '{"facts":[],"topics":[],"commitments":[],"conflicts":[],"decisions":[]}'
    )
    service.schedule_extraction(current)

    assert asyncio.run(MemoryExtractionWorker(store, service, provider).run_once()) is True

    submitted = provider.calls[0][-1].content
    assert "old-marker" not in submitted
    assert "prior-turn-marker" in submitted
    assert "prior reply marker" in submitted
    assert "delta-one-marker" in submitted
    assert "delta reply marker" in submitted
    assert "delta-two-marker" in submitted


def test_compact_repair_has_its_own_hard_budget() -> None:
    errors = [
        {"path": f"$.facts[{index}].value_text", "code": "string_too_short"}
        for index in range(30)
    ]

    messages = MemoryExtractionWorker._repair_messages("{" + "x" * 10_000, errors)
    request_chars = sum(len(item.content) for item in messages)

    assert request_chars == MEMORY_REPAIR_INPUT_CHAR_BUDGET
    assert "JSON_SCHEMA" not in messages[-1].content
    assert "BAD_JSON" in messages[-1].content
    assert messages[-1].content.count("string_too_short") == 16


def test_extraction_array_limits_keep_valid_prefix_and_report_overflow() -> None:
    payload = {
        "facts": [
            {
                "kind": "note",
                "predicate": "note",
                "value_text": f"value-{index}",
                "source_message_ids": ["source"],
            }
            for index in range(12)
        ],
        "topics": [],
        "commitments": [],
        "conflicts": [],
        "decisions": [],
    }

    result, errors = MemoryExtractionWorker._parse_partial_result(json.dumps(payload))

    assert len(result.facts) == 8
    assert any(item["code"] == "too_long" and item["section"] == "facts" for item in errors)
