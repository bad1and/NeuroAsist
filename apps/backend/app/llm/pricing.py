from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from apps.backend.app.llm.models import (
    DEEPSEEK_PRO_MODEL,
    canonical_deepseek_model,
)


@dataclass(frozen=True, slots=True)
class DeepSeekTokenRates:
    """USD prices per one million tokens."""

    cache_hit: float
    cache_miss: float
    output: float


# DeepSeek pricing published for V4.1 Flash and V4 Pro on 2026-09-10.
_FLASH_PEAK = DeepSeekTokenRates(cache_hit=0.006, cache_miss=0.30, output=1.20)
_FLASH_OFF_PEAK = DeepSeekTokenRates(cache_hit=0.003, cache_miss=0.15, output=0.60)
_PRO_PEAK = DeepSeekTokenRates(cache_hit=0.044, cache_miss=1.32, output=3.96)
_PRO_OFF_PEAK = DeepSeekTokenRates(cache_hit=0.022, cache_miss=0.66, output=1.98)


def is_deepseek_peak_time(timestamp: float) -> bool:
    """Return whether a Unix timestamp falls in DeepSeek peak hours (UTC)."""
    moment = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
    if moment.weekday() >= 5:
        return False
    return 1 <= moment.hour < 4 or 6 <= moment.hour < 10


def deepseek_token_rates(model: str, timestamp: float) -> DeepSeekTokenRates:
    canonical = canonical_deepseek_model(model)
    peak = is_deepseek_peak_time(timestamp)
    if canonical == DEEPSEEK_PRO_MODEL:
        return _PRO_PEAK if peak else _PRO_OFF_PEAK
    return _FLASH_PEAK if peak else _FLASH_OFF_PEAK


def estimate_deepseek_cost_usd(
    *,
    model: str,
    timestamp: float,
    cache_hit: int,
    cache_miss: int,
    completion: int,
) -> float:
    rates = deepseek_token_rates(model, timestamp)
    return (
        (max(0, cache_hit) * rates.cache_hit)
        + (max(0, cache_miss) * rates.cache_miss)
        + (max(0, completion) * rates.output)
    ) / 1_000_000
