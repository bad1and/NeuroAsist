from __future__ import annotations

import time
from typing import Any


def token_metadata(provider: object, *, timestamp: float | None = None) -> dict[str, object] | None:
    """Return the latest provider usage in the durable timeline shape.

    Streaming and batch calls expose the same information through slightly
    different objects.  Keeping the conversion here prevents the live voice
    path from losing usage while it waits for playback acknowledgement.
    """

    response = getattr(provider, "last_response", None)
    metrics = getattr(provider, "last_call_metrics", None)
    usage = (
        getattr(response, "usage", None)
        or getattr(metrics, "usage", None)
    )
    if usage is None:
        return None

    raw_usage: dict[str, Any]
    model_dump = getattr(usage, "model_dump", None)
    if callable(model_dump):
        raw_usage = dict(model_dump())
    else:
        raw_usage = {
            name: getattr(usage, name, 0)
            for name in (
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "reasoning_tokens",
                "prompt_cache_hit_tokens",
                "prompt_cache_miss_tokens",
            )
        }

    latency_ms = getattr(response, "latency_ms", None)
    if latency_ms is None:
        latency_ms = getattr(metrics, "latency_ms", 0.0)

    finish_reason = (
        getattr(response, "finish_reason", None)
        or getattr(metrics, "finish_reason", None)
    )
    purpose = getattr(response, "purpose", None) or getattr(metrics, "purpose", None)
    attempts = getattr(response, "attempts", None) or getattr(metrics, "attempts", None)

    result: dict[str, object] = {
        **raw_usage,
        "model": (
            getattr(response, "model", None)
            or getattr(metrics, "model", None)
            or getattr(provider, "_model", "")
        ),
        "timestamp": time.time() if timestamp is None else timestamp,
        "latency_ms": round(float(latency_ms or 0.0), 1),
        "raw_usage": raw_usage,
    }
    if finish_reason:
        result["finish_reason"] = str(finish_reason)
    if purpose:
        result["purpose"] = str(purpose)
    if attempts is not None:
        result["attempts"] = int(attempts)
    return result
