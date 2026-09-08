"""Weather service integrating Open-Meteo API.

Features:
- Free, no API keys required.
- In-memory caching with 30-minute TTL.
- Strict 1.5-second timeout with graceful fallback.
- Accurate translation of WMO weather codes to natural Russian.
- Compact formatting for ambient micro-header and detailed forecast for on-demand turns.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time

import httpx

logger = logging.getLogger(__name__)

# WMO Weather interpretation codes (WW)
_WMO_CODE_RU = {
    0: "ясно",
    1: "преимущественно ясно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "изморозь, туман",
    51: "лёгкая морось",
    53: "умеренная морось",
    55: "плотная морось",
    56: "ледяная морось",
    57: "густая ледяная морось",
    61: "небольшой дождь",
    63: "умеренный дождь",
    65: "сильный дождь",
    66: "ледяной дождь",
    67: "сильный ледяной дождь",
    71: "небольшой снегопад",
    73: "снегопад",
    75: "сильный снегопад",
    77: "снежные зёрна",
    80: "кратковременный дождь",
    81: "ливень",
    82: "сильный ливень",
    85: "небольшой снежный заряд",
    86: "сильный снежный заряд",
    95: "гроза",
    96: "гроза с небольшим градом",
    99: "гроза с крупным градом",
}


@dataclass(frozen=True, slots=True)
class CurrentWeatherSnapshot:
    temperature: float
    apparent_temperature: float
    humidity: int
    weather_code: int
    condition_ru: str
    wind_speed: float
    is_day: bool
    precipitation: float
    city_name: str
    cached_at: float

    def ambient_string(self) -> str:
        """Compact string representation for micro-context (~10-15 tokens)."""
        sign = "+" if self.temperature > 0 else ""
        temp_str = f"{sign}{round(self.temperature)}°C"
        return f"{temp_str}, {self.condition_ru}"

    def detailed_string(self) -> str:
        """Detailed string representation for on-demand query."""
        sign = "+" if self.temperature > 0 else ""
        temp_str = f"{sign}{round(self.temperature, 1)}°C"
        app_sign = "+" if self.apparent_temperature > 0 else ""
        app_str = f"{app_sign}{round(self.apparent_temperature, 1)}°C"
        wind_str = f"{round(self.wind_speed, 1)} м/с"
        precip_str = "без осадков" if self.precipitation <= 0.0 else f"осадки {self.precipitation} мм"
        city_prefix = f"в г. {self.city_name}" if self.city_name else "за окном"
        return (
            f"Погода {city_prefix}: сейчас {temp_str} (ощущается как {app_str}), "
            f"{self.condition_ru}, {precip_str}, ветер {wind_str}, влажность {self.humidity}%."
        )


@dataclass(frozen=True, slots=True)
class WeatherForecastDay:
    date_str: str
    temp_min: float
    temp_max: float
    weather_code: int
    condition_ru: str
    precipitation_sum: float


@dataclass(frozen=True, slots=True)
class WeatherForecastSnapshot:
    current: CurrentWeatherSnapshot
    days: tuple[WeatherForecastDay, ...]

    def detailed_string(self) -> str:
        parts = [self.current.detailed_string()]
        if self.days:
            forecast_parts = []
            labels = ["Сегодня", "Завтра", "Послезавтра"]
            for idx, day in enumerate(self.days[:3]):
                label = labels[idx] if idx < len(labels) else day.date_str
                min_sign = "+" if day.temp_min > 0 else ""
                max_sign = "+" if day.temp_max > 0 else ""
                forecast_parts.append(
                    f"{label}: от {min_sign}{round(day.temp_min)}°C до {max_sign}{round(day.temp_max)}°C, {day.condition_ru}"
                )
            parts.append("Прогноз: " + "; ".join(forecast_parts) + ".")
        return " ".join(parts)


class WeatherService:
    """Fetches and caches weather forecasts from Open-Meteo API."""

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client
        self._cache_lock = asyncio.Lock()
        self._cache: dict[tuple[float, float], tuple[WeatherForecastSnapshot, float]] = {}
        self._cache_ttl_seconds = 30 * 60  # 30 minutes

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=2.0)
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    async def get_weather(
        self,
        latitude: float | None,
        longitude: float | None,
        city_name: str = "",
    ) -> WeatherForecastSnapshot | None:
        """Get current weather and forecast for coordinates with 30-min in-memory caching."""
        if latitude is None or longitude is None:
            return None

        key = (round(latitude, 2), round(longitude, 2))
        now = time.monotonic()

        async with self._cache_lock:
            cached_entry = self._cache.get(key)
            if cached_entry is not None:
                snapshot, timestamp = cached_entry
                if (now - timestamp) < self._cache_ttl_seconds:
                    return snapshot

            # Fetch fresh from Open-Meteo
            try:
                client = await self._get_client()
                resp = await client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": latitude,
                        "longitude": longitude,
                        "current": (
                            "temperature_2m,relative_humidity_2m,apparent_temperature,"
                            "is_day,precipitation,weather_code,wind_speed_10m"
                        ),
                        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
                        "timezone": "auto",
                        "forecast_days": 3,
                    },
                    timeout=1.5,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    current_raw = data.get("current", {})
                    weather_code = int(current_raw.get("weather_code", 0))
                    condition_ru = _WMO_CODE_RU.get(weather_code, "умеренная погода")

                    current_snapshot = CurrentWeatherSnapshot(
                        temperature=float(current_raw.get("temperature_2m", 0.0)),
                        apparent_temperature=float(current_raw.get("apparent_temperature", 0.0)),
                        humidity=int(current_raw.get("relative_humidity_2m", 50)),
                        weather_code=weather_code,
                        condition_ru=condition_ru,
                        wind_speed=float(current_raw.get("wind_speed_10m", 0.0)),
                        is_day=bool(current_raw.get("is_day", 1)),
                        precipitation=float(current_raw.get("precipitation", 0.0)),
                        city_name=city_name,
                        cached_at=now,
                    )

                    daily_raw = data.get("daily", {})
                    dates = daily_raw.get("time", [])
                    maxs = daily_raw.get("temperature_2m_max", [])
                    mins = daily_raw.get("temperature_2m_min", [])
                    codes = daily_raw.get("weather_code", [])
                    precips = daily_raw.get("precipitation_sum", [])

                    forecast_days: list[WeatherForecastDay] = []
                    for i in range(min(len(dates), len(maxs), len(mins))):
                        d_code = int(codes[i]) if i < len(codes) else 0
                        forecast_days.append(
                            WeatherForecastDay(
                                date_str=str(dates[i]),
                                temp_min=float(mins[i]),
                                temp_max=float(maxs[i]),
                                weather_code=d_code,
                                condition_ru=_WMO_CODE_RU.get(d_code, "переменные условия"),
                                precipitation_sum=float(precips[i]) if i < len(precips) else 0.0,
                            )
                        )

                    snapshot = WeatherForecastSnapshot(
                        current=current_snapshot,
                        days=tuple(forecast_days),
                    )
                    self._cache[key] = (snapshot, now)
                    return snapshot
            except Exception as exc:
                logger.warning("Weather fetch failed for (%s, %s): %s", latitude, longitude, exc)
                # If cached version exists (even if older than TTL), return it during network outage
                if cached_entry is not None:
                    return cached_entry[0]

        return None
