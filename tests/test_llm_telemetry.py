from concurrent.futures import ThreadPoolExecutor

import pytest

from apps.backend.app.llm.telemetry import (
    LLMTelemetryCollector,
    LLMTelemetryRecord,
    TELEMETRY_WINDOWS,
)


def _record(
    collector: LLMTelemetryCollector,
    request_id: str,
    *,
    timestamp: float,
    purpose: str = "chat",
    status: str = "success",
    latency: float = 10.0,
) -> LLMTelemetryRecord:
    return collector.record(
        timestamp=timestamp,
        request_id=request_id,
        purpose=purpose,
        model="deepseek-v4-flash",
        streaming=purpose == "chat",
        thinking=False,
        max_tokens=512,
        message_count=3,
        input_chars=120,
        usage_available=True,
        prompt=30,
        completion=10,
        total=40,
        reasoning=2,
        cache_hit=7,
        cache_miss=23,
        latency=latency,
        finish_reason="stop" if status == "success" else None,
        status=status,
        error_type=None if status == "success" else "TimeoutError",
        logical_attempt=1,
    )


def test_schema_is_content_free_and_deque_is_bounded() -> None:
    collector = LLMTelemetryCollector(max_records=3, clock=lambda: 1_000.0)
    for index in range(4):
        _record(collector, f"req-{index}", timestamp=1_000.0 + index)

    records = collector.snapshot("24h", now=1_004.0)

    assert len(collector) == 3
    assert [item.request_id for item in records] == ["req-1", "req-2", "req-3"]
    assert set(records[0].to_dict()) == {
        "timestamp", "request_id", "purpose", "model", "streaming", "thinking",
        "max_tokens", "message_count", "input_chars", "prompt", "completion",
        "usage_available",
        "total", "reasoning", "cache_hit", "cache_miss", "latency",
        "finish_reason", "status", "error_type", "logical_attempt",
    }
    assert not {"messages", "content", "prompt_content", "response_content"} & set(
        records[0].to_dict()
    )


def test_snapshots_apply_fixed_windows_and_purpose_filter() -> None:
    now = 100_000.0
    collector = LLMTelemetryCollector(clock=lambda: now)
    _record(collector, "recent-chat", timestamp=now - 60, purpose="chat")
    _record(collector, "recent-memory", timestamp=now - 240, purpose="memory")
    _record(collector, "half-hour", timestamp=now - 1_200, purpose="chat")
    _record(collector, "day", timestamp=now - 20_000, purpose="summary")
    _record(collector, "expired", timestamp=now - 90_000, purpose="chat")

    snapshots = collector.snapshots(now=now)

    assert list(snapshots) == list(TELEMETRY_WINDOWS)
    assert {item.request_id for item in snapshots["5m"]} == {
        "recent-chat", "recent-memory",
    }
    assert {item.request_id for item in snapshots["30m"]} == {
        "recent-chat", "recent-memory", "half-hour",
    }
    assert {item.request_id for item in snapshots["24h"]} == {
        "recent-chat", "recent-memory", "half-hour", "day",
    }
    assert [
        item.request_id for item in collector.snapshot("30m", purpose="chat", now=now)
    ] == ["recent-chat", "half-hour"]


def test_aggregates_include_usage_latency_status_and_per_purpose() -> None:
    now = 50_000.0
    collector = LLMTelemetryCollector(clock=lambda: now)
    _record(collector, "chat-ok", timestamp=now - 10, purpose="chat", latency=10.0)
    _record(
        collector,
        "chat-error",
        timestamp=now - 20,
        purpose="chat",
        status="error",
        latency=30.0,
    )
    _record(collector, "memory-ok", timestamp=now - 30, purpose="memory", latency=20.0)

    aggregate = collector.aggregate("5m", purpose="chat", now=now)
    report = collector.report(now=now)["5m"]

    assert aggregate.request_count == 2
    assert aggregate.success_count == 1
    assert aggregate.error_count == 1
    assert aggregate.prompt == 60
    assert aggregate.completion == 20
    assert aggregate.total == 80
    assert aggregate.reasoning == 4
    assert aggregate.cache_hit == 14
    assert aggregate.cache_miss == 46
    assert aggregate.input_chars == 240
    assert aggregate.usage_available_count == 2
    assert aggregate.usage_unavailable_count == 0
    assert aggregate.latency_total == 40.0
    assert aggregate.latency_average == 20.0
    assert aggregate.latency_max == 30.0
    assert aggregate.latency_p95 == 30.0
    assert aggregate.status_counts == {"success": 1, "error": 1}
    assert aggregate.error_type_counts == {"TimeoutError": 1}
    assert report.overall.request_count == 3
    assert set(report.per_purpose) == {"chat", "memory"}
    assert report.per_purpose["memory"].request_count == 1


def test_recording_is_thread_safe_and_resettable() -> None:
    collector = LLMTelemetryCollector(max_records=500, clock=lambda: 10_000.0)

    def add(index: int) -> None:
        _record(collector, f"thread-{index}", timestamp=10_000.0)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(add, range(800)))

    records = collector.snapshot("5m", now=10_000.0)
    assert len(records) == 500
    assert len({item.request_id for item in records}) == 500

    collector.reset()
    assert len(collector) == 0
    assert collector.snapshots(now=10_000.0) == {"5m": (), "30m": (), "24h": ()}


def test_validation_rejects_invalid_counts_and_windows() -> None:
    collector = LLMTelemetryCollector()

    with pytest.raises(ValueError, match="input_chars"):
        collector.record(
            request_id="bad",
            purpose="chat",
            model="model",
            streaming=False,
            thinking=False,
            max_tokens=None,
            message_count=1,
            input_chars=-1,
        )
    with pytest.raises(ValueError, match="unknown telemetry window"):
        collector.snapshot("1h")
