"""Host local time service.

Operates purely in memory using the local Windows host clock.
Adds zero latency (0 ms) and requires no external network calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Literal


DayPeriod = Literal["night", "early_morning", "morning", "afternoon", "evening", "late_night"]

_WEEKDAYS_RU = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)

_MONTHS_RU = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


@dataclass(frozen=True, slots=True)
class TimeSnapshot:
    iso_timestamp: str
    date_formatted: str
    time_formatted: str
    weekday_ru: str
    day_period: DayPeriod
    day_period_ru: str
    timezone_name: str
    utc_offset: str

    def ambient_string(self) -> str:
        """Compact string representation for micro-context (~15 tokens)."""
        return f"{self.weekday_ru.capitalize()}, {self.date_formatted}, {self.time_formatted} ({self.utc_offset})"


class TimeService:
    """Provides local time snapshots without blocking or network calls."""

    @staticmethod
    def now() -> TimeSnapshot:
        local_dt = datetime.now().astimezone()
        weekday_ru = _WEEKDAYS_RU[local_dt.weekday()]
        month_ru = _MONTHS_RU[local_dt.month - 1]
        date_formatted = f"{local_dt.day} {month_ru} {local_dt.year}"
        time_formatted = local_dt.strftime("%H:%M")

        # UTC offset formatting (+03:00)
        offset = local_dt.utcoffset()
        if offset is not None:
            total_seconds = int(offset.total_seconds())
            sign = "+" if total_seconds >= 0 else "-"
            abs_seconds = abs(total_seconds)
            hours, remainder = divmod(abs_seconds, 3600)
            minutes = remainder // 60
            utc_offset = f"UTC{sign}{hours:02d}:{minutes:02d}"
        else:
            utc_offset = "UTC"

        tz_name = local_dt.tzname() or utc_offset

        hour = local_dt.hour
        if 0 <= hour < 5:
            period: DayPeriod = "late_night"
            period_ru = "глубокая ночь"
        elif 5 <= hour < 7:
            period = "early_morning"
            period_ru = "раннее утро"
        elif 7 <= hour < 12:
            period = "morning"
            period_ru = "утро"
        elif 12 <= hour < 18:
            period = "afternoon"
            period_ru = "день"
        elif 18 <= hour < 23:
            period = "evening"
            period_ru = "вечер"
        else:
            period = "night"
            period_ru = "ночь"

        return TimeSnapshot(
            iso_timestamp=local_dt.isoformat(),
            date_formatted=date_formatted,
            time_formatted=time_formatted,
            weekday_ru=weekday_ru,
            day_period=period,
            day_period_ru=period_ru,
            timezone_name=tz_name,
            utc_offset=utc_offset,
        )
