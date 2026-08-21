from __future__ import annotations

import math
import time
from collections import Counter, deque
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from threading import RLock


TELEMETRY_WINDOWS: Mapping[str, float] = {
    "5m": 5 * 60,
    "30m": 30 * 60,
    "24h": 24 * 60 * 60,
}


@dataclass(frozen=True, slots=True)
class LLMTelemetryRecord:
    """Content-free measurements for one physical provider request.

    ``timestamp`` is UTC Unix time in seconds. Token fields intentionally use
    the short provider-facing names requested by the telemetry contract. They
    contain counts only; prompt, response, message, and error text are never
    accepted by this schema.
    """

    timestamp: float
    request_id: str
    purpose: str
    model: str
    streaming: bool
    thinking: bool
    max_tokens: int | None
    message_count: int
    input_chars: int
    usage_available: bool
    prompt: int
    completion: int
    total: int
    reasoning: int
    cache_hit: int
    cache_miss: int
    latency: float
    finish_reason: str | None
    status: str
    error_type: str | None
    logical_attempt: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LLMTelemetryAggregate:
    window: str
    purpose: str | None
    request_count: int
    success_count: int
    error_count: int
    streaming_count: int
    thinking_count: int
    logical_attempts: int
    input_chars: int
    usage_available_count: int
    usage_unavailable_count: int
    prompt: int
    completion: int
    total: int
    reasoning: int
    cache_hit: int
    cache_miss: int
    latency_total: float
    latency_average: float
    latency_max: float
    latency_p95: float
    status_counts: Mapping[str, int]
    model_counts: Mapping[str, int]
    finish_reason_counts: Mapping[str, int]
    error_type_counts: Mapping[str, int]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LLMTelemetryWindowReport:
    overall: LLMTelemetryAggregate
    per_purpose: Mapping[str, LLMTelemetryAggregate]


class LLMTelemetryCollector:
    """Thread-safe bounded telemetry store with fixed rolling windows."""

    def __init__(
        self,
        max_records: int = 10_000,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if isinstance(max_records, bool) or not isinstance(max_records, int) or max_records <= 0:
            raise ValueError("max_records must be a positive integer")
        self._records: deque[LLMTelemetryRecord] = deque(maxlen=max_records)
        self._clock = clock
        self._lock = RLock()

    @property
    def max_records(self) -> int:
        return self._records.maxlen or 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def record(
        self,
        *,
        request_id: str,
        purpose: str,
        model: str,
        streaming: bool,
        thinking: bool,
        max_tokens: int | None,
        message_count: int,
        input_chars: int,
        usage_available: bool = False,
        prompt: int = 0,
        completion: int = 0,
        total: int = 0,
        reasoning: int = 0,
        cache_hit: int = 0,
        cache_miss: int = 0,
        latency: float = 0.0,
        finish_reason: str | None = None,
        status: str = "success",
        error_type: str | None = None,
        logical_attempt: int = 1,
        timestamp: float | None = None,
    ) -> LLMTelemetryRecord:
        item = LLMTelemetryRecord(
            timestamp=float(self._clock() if timestamp is None else timestamp),
            request_id=request_id,
            purpose=purpose,
            model=model,
            streaming=streaming,
            thinking=thinking,
            max_tokens=max_tokens,
            message_count=message_count,
            input_chars=input_chars,
            usage_available=usage_available,
            prompt=prompt,
            completion=completion,
            total=total,
            reasoning=reasoning,
            cache_hit=cache_hit,
            cache_miss=cache_miss,
            latency=float(latency),
            finish_reason=finish_reason,
            status=status,
            error_type=error_type,
            logical_attempt=logical_attempt,
        )
        return self.append(item)

    def append(self, item: LLMTelemetryRecord) -> LLMTelemetryRecord:
        self._validate(item)
        with self._lock:
            self._records.append(item)
        return item

    def reset(self) -> None:
        with self._lock:
            self._records.clear()

    def snapshot(
        self,
        window: str,
        *,
        purpose: str | None = None,
        now: float | None = None,
    ) -> tuple[LLMTelemetryRecord, ...]:
        seconds = self._window_seconds(window)
        boundary = float(self._clock() if now is None else now) - seconds
        with self._lock:
            records = tuple(self._records)
        return tuple(
            item
            for item in records
            if item.timestamp >= boundary and (purpose is None or item.purpose == purpose)
        )

    def snapshots(
        self,
        *,
        purpose: str | None = None,
        now: float | None = None,
    ) -> dict[str, tuple[LLMTelemetryRecord, ...]]:
        effective_now = float(self._clock() if now is None else now)
        return {
            window: self.snapshot(window, purpose=purpose, now=effective_now)
            for window in TELEMETRY_WINDOWS
        }

    def aggregate(
        self,
        window: str,
        *,
        purpose: str | None = None,
        now: float | None = None,
    ) -> LLMTelemetryAggregate:
        records = self.snapshot(window, purpose=purpose, now=now)
        return self._aggregate_records(window, purpose, records)

    def aggregates(
        self,
        *,
        purpose: str | None = None,
        now: float | None = None,
    ) -> dict[str, LLMTelemetryAggregate]:
        effective_now = float(self._clock() if now is None else now)
        return {
            window: self.aggregate(window, purpose=purpose, now=effective_now)
            for window in TELEMETRY_WINDOWS
        }

    def report(
        self,
        *,
        now: float | None = None,
    ) -> dict[str, LLMTelemetryWindowReport]:
        """Return overall and per-purpose aggregates for every fixed window."""

        effective_now = float(self._clock() if now is None else now)
        result: dict[str, LLMTelemetryWindowReport] = {}
        for window in TELEMETRY_WINDOWS:
            records = self.snapshot(window, now=effective_now)
            purposes = sorted({item.purpose for item in records})
            result[window] = LLMTelemetryWindowReport(
                overall=self._aggregate_records(window, None, records),
                per_purpose={
                    purpose: self._aggregate_records(
                        window,
                        purpose,
                        tuple(item for item in records if item.purpose == purpose),
                    )
                    for purpose in purposes
                },
            )
        return result

    @staticmethod
    def _aggregate_records(
        window: str,
        purpose: str | None,
        records: tuple[LLMTelemetryRecord, ...],
    ) -> LLMTelemetryAggregate:
        latencies = sorted(item.latency for item in records)
        latency_total = sum(latencies)
        p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1) if latencies else 0
        success_count = sum(item.status == "success" for item in records)
        return LLMTelemetryAggregate(
            window=window,
            purpose=purpose,
            request_count=len(records),
            success_count=success_count,
            error_count=len(records) - success_count,
            streaming_count=sum(item.streaming for item in records),
            thinking_count=sum(item.thinking for item in records),
            logical_attempts=sum(item.logical_attempt for item in records),
            input_chars=sum(item.input_chars for item in records),
            usage_available_count=sum(item.usage_available for item in records),
            usage_unavailable_count=sum(not item.usage_available for item in records),
            prompt=sum(item.prompt for item in records),
            completion=sum(item.completion for item in records),
            total=sum(item.total for item in records),
            reasoning=sum(item.reasoning for item in records),
            cache_hit=sum(item.cache_hit for item in records),
            cache_miss=sum(item.cache_miss for item in records),
            latency_total=latency_total,
            latency_average=latency_total / len(records) if records else 0.0,
            latency_max=max(latencies, default=0.0),
            latency_p95=latencies[p95_index] if latencies else 0.0,
            status_counts=dict(Counter(item.status for item in records)),
            model_counts=dict(Counter(item.model for item in records)),
            finish_reason_counts=dict(
                Counter(item.finish_reason for item in records if item.finish_reason)
            ),
            error_type_counts=dict(
                Counter(item.error_type for item in records if item.error_type)
            ),
        )

    @staticmethod
    def _window_seconds(window: str) -> float:
        try:
            return TELEMETRY_WINDOWS[window]
        except KeyError as exc:
            choices = ", ".join(TELEMETRY_WINDOWS)
            raise ValueError(f"unknown telemetry window {window!r}; expected one of {choices}") from exc

    @staticmethod
    def _validate(item: LLMTelemetryRecord) -> None:
        if not isinstance(item, LLMTelemetryRecord):
            raise TypeError("item must be an LLMTelemetryRecord")
        if not math.isfinite(item.timestamp):
            raise ValueError("timestamp must be finite")
        if not item.request_id or not item.purpose or not item.model or not item.status:
            raise ValueError("request_id, purpose, model, and status must be non-empty")
        for name in (
            "message_count",
            "input_chars",
            "prompt",
            "completion",
            "total",
            "reasoning",
            "cache_hit",
            "cache_miss",
        ):
            value = getattr(item, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if item.max_tokens is not None and (
            isinstance(item.max_tokens, bool)
            or not isinstance(item.max_tokens, int)
            or item.max_tokens < 0
        ):
            raise ValueError("max_tokens must be a non-negative integer or None")
        if (
            isinstance(item.logical_attempt, bool)
            or not isinstance(item.logical_attempt, int)
            or item.logical_attempt < 1
        ):
            raise ValueError("logical_attempt must be a positive integer")
        if not math.isfinite(item.latency) or item.latency < 0:
            raise ValueError("latency must be a finite non-negative number")


# A process-local default is available for future integration. It performs no
# I/O and remains unused until a provider explicitly records measurements.
llm_telemetry = LLMTelemetryCollector()
