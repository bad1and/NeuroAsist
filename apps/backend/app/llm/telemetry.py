from __future__ import annotations

import math
import sqlite3
import time
from collections import Counter, deque
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
        db_path: Path | str | None = None,
    ) -> None:
        if isinstance(max_records, bool) or not isinstance(max_records, int) or max_records <= 0:
            raise ValueError("max_records must be a positive integer")
        self._records: deque[LLMTelemetryRecord] = deque(maxlen=max_records)
        self._clock = clock
        self._lock = RLock()
        self._db_path: Path | None = Path(db_path) if db_path is not None else None
        if self._db_path is not None:
            self._init_db()
            self._load_recent_records()

    def bind_database(self, db_path: Path | str) -> None:
        """Bind persistent SQLite storage to this collector."""
        with self._lock:
            self._db_path = Path(db_path)
            self._init_db()
            self._load_recent_records()

    def _init_db(self) -> None:
        if self._db_path is None:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_telemetry_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    request_id TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    model TEXT NOT NULL,
                    streaming INTEGER NOT NULL,
                    thinking INTEGER NOT NULL,
                    max_tokens INTEGER,
                    message_count INTEGER NOT NULL,
                    input_chars INTEGER NOT NULL,
                    usage_available INTEGER NOT NULL,
                    prompt INTEGER NOT NULL,
                    completion INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    reasoning INTEGER NOT NULL,
                    cache_hit INTEGER NOT NULL,
                    cache_miss INTEGER NOT NULL,
                    latency REAL NOT NULL,
                    finish_reason TEXT,
                    status TEXT NOT NULL,
                    error_type TEXT,
                    logical_attempt INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_llm_telemetry_timestamp ON llm_telemetry_records (timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_llm_telemetry_purpose ON llm_telemetry_records (purpose)"
            )

    def _load_recent_records(self) -> None:
        if self._db_path is None:
            return
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT timestamp, request_id, purpose, model, streaming, thinking, max_tokens,
                           message_count, input_chars, usage_available, prompt, completion, total,
                           reasoning, cache_hit, cache_miss, latency, finish_reason, status, error_type, logical_attempt
                    FROM llm_telemetry_records
                    ORDER BY timestamp DESC, id DESC
                    LIMIT ?
                    """,
                    (self.max_records,),
                ).fetchall()
            loaded: list[LLMTelemetryRecord] = []
            for row in reversed(rows):
                loaded.append(self._row_to_record(row))
            self._records.clear()
            self._records.extend(loaded)
        except Exception:
            pass

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
            if self._db_path is not None:
                try:
                    with sqlite3.connect(self._db_path) as conn:
                        conn.execute(
                            """
                            INSERT INTO llm_telemetry_records (
                                timestamp, request_id, purpose, model, streaming, thinking, max_tokens,
                                message_count, input_chars, usage_available, prompt, completion, total,
                                reasoning, cache_hit, cache_miss, latency, finish_reason, status, error_type, logical_attempt
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                item.timestamp, item.request_id, item.purpose, item.model,
                                1 if item.streaming else 0, 1 if item.thinking else 0, item.max_tokens,
                                item.message_count, item.input_chars, 1 if item.usage_available else 0,
                                item.prompt, item.completion, item.total, item.reasoning,
                                item.cache_hit, item.cache_miss, item.latency,
                                item.finish_reason, item.status, item.error_type, item.logical_attempt,
                            ),
                        )
                except Exception:
                    pass
        return item

    def reset(self) -> None:
        with self._lock:
            self._records.clear()
            if self._db_path is not None:
                try:
                    with sqlite3.connect(self._db_path) as conn:
                        conn.execute("DELETE FROM llm_telemetry_records")
                except Exception:
                    pass

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

    def get_stats(
        self,
        timeframe: str = "all",
        now: float | None = None,
    ) -> dict[str, object]:
        """Return rich token analytics, cost estimation and timeseries for dashboards."""
        effective_now = float(self._clock() if now is None else now)
        seconds = {
            "24h": 24 * 3600.0,
            "7d": 7 * 24 * 3600.0,
            "30d": 30 * 24 * 3600.0,
        }.get(timeframe)
        boundary = (effective_now - seconds) if seconds is not None else 0.0

        with self._lock:
            if self._db_path is not None:
                try:
                    with sqlite3.connect(self._db_path) as conn:
                        conn.row_factory = sqlite3.Row
                        if boundary > 0.0:
                            rows = conn.execute(
                                "SELECT * FROM llm_telemetry_records WHERE timestamp >= ? ORDER BY timestamp ASC",
                                (boundary,),
                            ).fetchall()
                        else:
                            rows = conn.execute(
                                "SELECT * FROM llm_telemetry_records ORDER BY timestamp ASC"
                            ).fetchall()
                        records = tuple(self._row_to_record(row) for row in rows)
                except Exception:
                    records = tuple(r for r in self._records if r.timestamp >= boundary)
            else:
                records = tuple(r for r in self._records if r.timestamp >= boundary)

        return self._compute_detailed_stats(records, timeframe, effective_now)

    def get_records(
        self,
        limit: int = 50,
        offset: int = 0,
        purpose: str | None = None,
    ) -> dict[str, object]:
        """Return paginated raw request records for detailed inspection."""
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        with self._lock:
            purposes = [p.strip() for p in purpose.split(",") if p.strip()] if purpose else []
            if self._db_path is not None:
                try:
                    with sqlite3.connect(self._db_path) as conn:
                        conn.row_factory = sqlite3.Row
                        if len(purposes) == 1:
                            where = "WHERE purpose = ?"
                            params = [purposes[0]]
                        elif len(purposes) > 1:
                            placeholders = ",".join("?" for _ in purposes)
                            where = f"WHERE purpose IN ({placeholders})"
                            params = purposes
                        else:
                            where = ""
                            params = []
                        total_count = conn.execute(
                            f"SELECT COUNT(*) FROM llm_telemetry_records {where}",
                            params,
                        ).fetchone()[0]
                        rows = conn.execute(
                            f"""
                            SELECT * FROM llm_telemetry_records {where}
                            ORDER BY timestamp DESC, id DESC
                            LIMIT ? OFFSET ?
                            """,
                            [*params, limit, offset],
                        ).fetchall()
                        items = [self._row_to_dict(row) for row in rows]
                        return {
                            "items": items,
                            "total": total_count,
                            "limit": limit,
                            "offset": offset,
                        }
                except Exception:
                    pass

            # Fallback to in-memory records
            purpose_set = set(purposes) if purposes else None
            filtered = [r for r in reversed(self._records) if (purpose_set is None or r.purpose in purpose_set)]
            page = filtered[offset : offset + limit]
            return {
                "items": [
                    {
                        "timestamp": r.timestamp,
                        "request_id": r.request_id,
                        "purpose": r.purpose,
                        "model": r.model,
                        "streaming": r.streaming,
                        "thinking": r.thinking,
                        "max_tokens": r.max_tokens,
                        "message_count": r.message_count,
                        "input_chars": r.input_chars,
                        "usage_available": r.usage_available,
                        "prompt": r.prompt,
                        "completion": r.completion,
                        "total": r.total,
                        "reasoning": r.reasoning,
                        "cache_hit": r.cache_hit,
                        "cache_miss": r.cache_miss,
                        "latency_ms": round(r.latency * 1000.0, 1),
                        "finish_reason": r.finish_reason,
                        "status": r.status,
                        "error_type": r.error_type,
                        "logical_attempt": r.logical_attempt,
                    }
                    for r in page
                ],
                "total": len(filtered),
                "limit": limit,
                "offset": offset,
            }

    @classmethod
    def _compute_detailed_stats(
        cls,
        records: tuple[LLMTelemetryRecord, ...],
        timeframe: str,
        now: float,
    ) -> dict[str, object]:
        total_prompt = sum(r.prompt for r in records)
        total_completion = sum(r.completion for r in records)
        total_tokens = sum(r.total for r in records)
        total_reasoning = sum(r.reasoning for r in records)
        total_cache_hit = sum(r.cache_hit for r in records)
        total_cache_miss = sum(r.cache_miss for r in records)
        cache_total = total_cache_hit + total_cache_miss
        cache_hit_rate = round((total_cache_hit / cache_total) * 100.0, 1) if cache_total > 0 else 0.0

        request_count = len(records)
        success_count = sum(1 for r in records if r.status == "success")
        error_count = request_count - success_count
        latencies = sorted(r.latency for r in records)
        latency_avg_ms = round((sum(latencies) / len(latencies)) * 1000.0, 1) if latencies else 0.0
        p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1) if latencies else 0
        latency_p95_ms = round(latencies[p95_index] * 1000.0, 1) if latencies else 0.0

        # DeepSeek pricing: $0.07/M cached in, $0.27/M uncached in, $1.10/M out
        estimated_cost_usd = round(
            (total_cache_hit * 0.00000007)
            + (total_cache_miss * 0.00000027)
            + (total_completion * 0.0000011),
            5,
        )

        by_purpose: dict[str, dict[str, int]] = {}
        for r in records:
            p = by_purpose.setdefault(
                r.purpose,
                {"request_count": 0, "prompt": 0, "completion": 0, "total": 0, "cache_hit": 0},
            )
            p["request_count"] += 1
            p["prompt"] += r.prompt
            p["completion"] += r.completion
            p["total"] += r.total
            p["cache_hit"] += r.cache_hit

        by_model: dict[str, dict[str, int]] = {}
        for r in records:
            m = by_model.setdefault(
                r.model,
                {"request_count": 0, "prompt": 0, "completion": 0, "total": 0},
            )
            m["request_count"] += 1
            m["prompt"] += r.prompt
            m["completion"] += r.completion
            m["total"] += r.total

        timeseries = cls._build_timeseries(records, timeframe, now)

        return {
            "timeframe": timeframe,
            "total_tokens": total_tokens,
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "reasoning_tokens": total_reasoning,
            "cache_hit_tokens": total_cache_hit,
            "cache_miss_tokens": total_cache_miss,
            "cache_hit_rate": cache_hit_rate,
            "request_count": request_count,
            "success_count": success_count,
            "error_count": error_count,
            "latency_avg_ms": latency_avg_ms,
            "latency_p95_ms": latency_p95_ms,
            "estimated_cost_usd": estimated_cost_usd,
            "by_purpose": by_purpose,
            "by_model": by_model,
            "timeseries": timeseries,
        }

    @staticmethod
    def _build_timeseries(
        records: tuple[LLMTelemetryRecord, ...],
        timeframe: str,
        now: float,
    ) -> list[dict[str, object]]:
        if timeframe == "24h":
            # 24 hourly buckets
            buckets: list[dict[str, object]] = []
            bucket_map: dict[int, dict[str, object]] = {}
            base_hour = int(now // 3600) * 3600
            for i in range(23, -1, -1):
                ts = base_hour - (i * 3600)
                dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=ts)
                label = dt.strftime("%H:00")
                item = {
                    "timestamp": ts,
                    "label": label,
                    "prompt": 0,
                    "completion": 0,
                    "total": 0,
                    "count": 0,
                }
                buckets.append(item)
                bucket_map[ts] = item

            for r in records:
                b_ts = int(r.timestamp // 3600) * 3600
                if b_ts in bucket_map:
                    bucket_map[b_ts]["prompt"] = int(bucket_map[b_ts]["prompt"]) + r.prompt
                    bucket_map[b_ts]["completion"] = int(bucket_map[b_ts]["completion"]) + r.completion
                    bucket_map[b_ts]["total"] = int(bucket_map[b_ts]["total"]) + r.total
                    bucket_map[b_ts]["count"] = int(bucket_map[b_ts]["count"]) + 1

            return buckets

        # Daily buckets (7d, 30d, all)
        num_days = 7 if timeframe == "7d" else 30
        buckets = []
        bucket_map = {}
        base_day = int(now // 86400) * 86400
        for i in range(num_days - 1, -1, -1):
            ts = base_day - (i * 86400)
            dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=ts)
            label = dt.strftime("%d.%m")
            item = {
                "timestamp": ts,
                "label": label,
                "prompt": 0,
                "completion": 0,
                "total": 0,
                "count": 0,
            }
            buckets.append(item)
            bucket_map[ts] = item

        for r in records:
            b_ts = int(r.timestamp // 86400) * 86400
            if b_ts in bucket_map:
                bucket_map[b_ts]["prompt"] = int(bucket_map[b_ts]["prompt"]) + r.prompt
                bucket_map[b_ts]["completion"] = int(bucket_map[b_ts]["completion"]) + r.completion
                bucket_map[b_ts]["total"] = int(bucket_map[b_ts]["total"]) + r.total
                bucket_map[b_ts]["count"] = int(bucket_map[b_ts]["count"]) + 1

        return buckets

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> LLMTelemetryRecord:
        return LLMTelemetryRecord(
            timestamp=float(row["timestamp"]),
            request_id=str(row["request_id"]),
            purpose=str(row["purpose"]),
            model=str(row["model"]),
            streaming=bool(row["streaming"]),
            thinking=bool(row["thinking"]),
            max_tokens=row["max_tokens"],
            message_count=int(row["message_count"]),
            input_chars=int(row["input_chars"]),
            usage_available=bool(row["usage_available"]),
            prompt=int(row["prompt"]),
            completion=int(row["completion"]),
            total=int(row["total"]),
            reasoning=int(row["reasoning"]),
            cache_hit=int(row["cache_hit"]),
            cache_miss=int(row["cache_miss"]),
            latency=float(row["latency"]),
            finish_reason=row["finish_reason"],
            status=str(row["status"]),
            error_type=row["error_type"],
            logical_attempt=int(row["logical_attempt"]),
        )

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, object]:
        return {
            "timestamp": float(row["timestamp"]),
            "request_id": str(row["request_id"]),
            "purpose": str(row["purpose"]),
            "model": str(row["model"]),
            "streaming": bool(row["streaming"]),
            "thinking": bool(row["thinking"]),
            "max_tokens": row["max_tokens"],
            "message_count": int(row["message_count"]),
            "input_chars": int(row["input_chars"]),
            "usage_available": bool(row["usage_available"]),
            "prompt": int(row["prompt"]),
            "completion": int(row["completion"]),
            "total": int(row["total"]),
            "reasoning": int(row["reasoning"]),
            "cache_hit": int(row["cache_hit"]),
            "cache_miss": int(row["cache_miss"]),
            "latency_ms": round(float(row["latency"]) * 1000.0, 1),
            "finish_reason": row["finish_reason"],
            "status": str(row["status"]),
            "error_type": row["error_type"],
            "logical_attempt": int(row["logical_attempt"]),
        }

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
