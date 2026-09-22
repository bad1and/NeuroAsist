from datetime import datetime, timezone

import pytest

from apps.backend.app.llm.models import canonical_deepseek_model
from apps.backend.app.llm.pricing import (
    deepseek_token_rates,
    estimate_deepseek_cost_usd,
    is_deepseek_peak_time,
)


def _timestamp(year: int, month: int, day: int, hour: int) -> float:
    return datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp()


def test_deepseek_model_aliases_use_current_api_identifiers() -> None:
    assert canonical_deepseek_model("deepseek-v4.1-flash") == "deepseek-flash"
    assert canonical_deepseek_model("deepseek-v4-flash") == "deepseek-flash"
    assert canonical_deepseek_model("deepseek-v4.1-pro") == "deepseek-v4-pro"
    assert canonical_deepseek_model("custom-model") == "custom-model"


def test_peak_windows_use_utc_weekdays() -> None:
    monday = (2026, 9, 21)
    assert is_deepseek_peak_time(_timestamp(*monday, 2)) is True
    assert is_deepseek_peak_time(_timestamp(*monday, 5)) is False
    assert is_deepseek_peak_time(_timestamp(*monday, 8)) is True
    assert is_deepseek_peak_time(_timestamp(2026, 9, 20, 2)) is False


@pytest.mark.parametrize(
    ("model", "day", "expected"),
    [
        ("deepseek-flash", 21, 1.506),
        ("deepseek-flash", 20, 0.753),
        ("deepseek-v4-pro", 21, 5.324),
        ("deepseek-v4-pro", 20, 2.662),
    ],
)
def test_cost_uses_model_and_peak_tier(model: str, day: int, expected: float) -> None:
    cost = estimate_deepseek_cost_usd(
        model=model,
        timestamp=_timestamp(2026, 9, day, 2),
        cache_hit=1_000_000,
        cache_miss=1_000_000,
        completion=1_000_000,
    )

    assert cost == pytest.approx(expected)


def test_published_flash_rates_are_selected_for_legacy_alias() -> None:
    rates = deepseek_token_rates("deepseek-v4.1-flash", _timestamp(2026, 9, 21, 2))

    assert rates.cache_hit == 0.006
    assert rates.cache_miss == 0.30
    assert rates.output == 1.20
