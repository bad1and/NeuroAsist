"""User location resolution service.

Supports:
1. Manual city override from runtime settings (highest priority).
2. Auto-detection via IP geolocation or client timezone (cached for 24 hours).
3. Open-Meteo geocoding to resolve coordinates (lat/lon) for weather.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

LocationSource = Literal["manual", "ip_auto", "timezone_fallback", "unknown"]


@dataclass(frozen=True, slots=True)
class LocationSnapshot:
    city: str
    country: str
    latitude: float | None
    longitude: float | None
    timezone: str
    source: LocationSource

    def ambient_string(self) -> str:
        """Compact string representation for micro-context."""
        if self.city:
            return self.city
        return self.timezone or "Не определена"


# Common Russian and global timezone mappings as instant fallback
_TIMEZONE_TO_CITY = {
    "Europe/Moscow": "Москва",
    "Europe/Kaliningrad": "Калининград",
    "Europe/Samara": "Самара",
    "Asia/Yekaterinburg": "Екатеринбург",
    "Asia/Omsk": "Омск",
    "Asia/Novosibirsk": "Новосибирск",
    "Asia/Krasnoyarsk": "Красноярск",
    "Asia/Irkutsk": "Иркутск",
    "Asia/Yakutsk": "Якутск",
    "Asia/Vladivostok": "Владивосток",
    "Asia/Magadan": "Магадан",
    "Asia/Kamchatka": "Петропавловск-Камчатский",
    "Asia/Almaty": "Алматы",
    "Asia/Tashkent": "Ташкент",
    "Europe/Minsk": "Минск",
    "Europe/Kiev": "Киев",
    "Europe/Kyiv": "Киев",
    "Asia/Tbilisi": "Тбилиси",
    "Asia/Yerevan": "Ереван",
    "Asia/Baku": "Баку",
}


_RUSSIAN_CITY_INFLECTIONS: dict[str, str] = {
    "москве": "москва",
    "москву": "москва",
    "питере": "санкт-петербург",
    "питер": "санкт-петербург",
    "петербурге": "санкт-петербург",
    "петербург": "санкт-петербург",
    "казани": "казань",
    "самаре": "самара",
    "екатеринбурге": "екатеринбург",
    "новосибирске": "новосибирск",
    "ростове": "ростов-на-дону",
    "уфе": "уфа",
    "краснодаре": "краснодар",
    "владивостоке": "владивосток",
    "воронеже": "воронеж",
    "перми": "пермь",
    "волгограде": "волгоград",
    "омске": "омск",
    "челябинске": "челябинск",
    "красноярске": "красноярск",
    "сочи": "сочи",
    "калининграде": "калининград",
}

_CANONICAL_CITY_NAMES: dict[str, str] = {
    "москва": "Москва",
    "санкт-петербург": "Санкт-Петербург",
    "питер": "Санкт-Петербург",
    "новосибирск": "Новосибирск",
    "екатеринбург": "Екатеринбург",
    "казань": "Казань",
    "нижний новгород": "Нижний Новгород",
    "красноярск": "Красноярск",
    "челябинск": "Челябинск",
    "самара": "Самара",
    "ростов-на-дону": "Ростов-на-Дону",
    "уфа": "Уфа",
    "краснодар": "Краснодар",
    "омск": "Омск",
    "воронеж": "Воронеж",
    "пермь": "Пермь",
    "волгоград": "Волгоград",
    "сочи": "Сочи",
    "владивосток": "Владивосток",
    "калининград": "Калининград",
}


class LocationService:
    """Resolves and caches user geographical location for weather and contextual awareness."""

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client
        self._cache_lock = asyncio.Lock()
        self._cached_location: LocationSnapshot | None = None
        self._cached_city_query: str | None = None
        self._cache_time: float = 0.0
        self._cache_ttl_seconds: float = 24 * 3600  # 24 hours for IP auto-detect

        # Geocode cache for city names -> (lat, lon, country, tz)
        self._geocode_cache: dict[str, tuple[float, float, str, str]] = {
            "москва": (55.7558, 37.6173, "Россия", "Europe/Moscow"),
            "санкт-петербург": (59.9343, 30.3351, "Россия", "Europe/Moscow"),
            "питер": (59.9343, 30.3351, "Россия", "Europe/Moscow"),
            "новосибирск": (55.0084, 82.9357, "Россия", "Asia/Novosibirsk"),
            "екатеринбург": (56.8389, 60.6057, "Россия", "Asia/Yekaterinburg"),
            "казань": (55.8304, 49.0661, "Россия", "Europe/Moscow"),
            "нижний новгород": (56.2965, 43.9361, "Россия", "Europe/Moscow"),
            "красноярск": (56.0153, 92.8932, "Россия", "Asia/Krasnoyarsk"),
            "челябинск": (55.1644, 61.4368, "Россия", "Asia/Yekaterinburg"),
            "самара": (53.2415, 50.2212, "Россия", "Europe/Samara"),
            "ростов-на-дону": (47.2357, 39.7015, "Россия", "Europe/Moscow"),
            "уфа": (54.7388, 55.9721, "Россия", "Asia/Yekaterinburg"),
            "краснодар": (45.0393, 38.9872, "Россия", "Europe/Moscow"),
            "омск": (54.9885, 73.3242, "Россия", "Asia/Omsk"),
            "воронеж": (51.6755, 39.2089, "Россия", "Europe/Moscow"),
            "пермь": (58.0105, 56.2502, "Россия", "Asia/Yekaterinburg"),
            "волгоград": (48.7080, 44.5133, "Россия", "Europe/Volgograd"),
            "сочи": (43.6028, 39.7342, "Россия", "Europe/Moscow"),
            "владивосток": (43.1155, 131.8855, "Россия", "Asia/Vladivostok"),
            "калининград": (54.7104, 20.4522, "Россия", "Europe/Kaliningrad"),
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=3.0)
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    async def resolve_location(
        self,
        manual_city: str | None = None,
        location_mode: str = "auto",
    ) -> LocationSnapshot:
        """Resolve current location based on user configuration or auto-detection."""
        cleaned_city = (manual_city or "").strip()

        # If manual city specified and location_mode is not forced auto:
        if cleaned_city:
            return await self._resolve_city(cleaned_city, source="manual")

        # Check in-memory auto-detect cache
        now = time.monotonic()
        async with self._cache_lock:
            if (
                self._cached_location is not None
                and (now - self._cache_time) < self._cache_ttl_seconds
                and self._cached_city_query is None
            ):
                return self._cached_location

            # Auto detection
            snapshot = await self._detect_auto_location()
            self._cached_location = snapshot
            self._cached_city_query = None
            self._cache_time = now
            return snapshot

    async def _resolve_city(self, city_name: str, source: LocationSource = "manual") -> LocationSnapshot:
        """Geocode a city name into lat/lon coordinates and timezone."""
        raw_norm = city_name.lower().strip()
        norm = _RUSSIAN_CITY_INFLECTIONS.get(raw_norm, raw_norm)
        display_city = _CANONICAL_CITY_NAMES.get(norm, city_name.strip())

        if norm in self._geocode_cache:
            lat, lon, country, tz = self._geocode_cache[norm]
            return LocationSnapshot(
                city=display_city,
                country=country,
                latitude=lat,
                longitude=lon,
                timezone=tz,
                source=source,
            )

        # Geocode via Open-Meteo Geocoding API
        try:
            client = await self._get_client()
            resp = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city_name, "count": 1, "language": "ru", "format": "json"},
                timeout=2.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results")
                if results and len(results) > 0:
                    top = results[0]
                    lat = float(top.get("latitude", 0.0))
                    lon = float(top.get("longitude", 0.0))
                    country = str(top.get("country", ""))
                    tz = str(top.get("timezone", "UTC"))
                    resolved_city = str(top.get("name", city_name))
                    self._geocode_cache[norm] = (lat, lon, country, tz)
                    return LocationSnapshot(
                        city=resolved_city,
                        country=country,
                        latitude=lat,
                        longitude=lon,
                        timezone=tz,
                        source=source,
                    )
        except Exception as exc:
            logger.warning("Geocoding failed for '%s': %s", city_name, exc)

        # Fallback if geocoding failed
        return LocationSnapshot(
            city=city_name.capitalize(),
            country="",
            latitude=None,
            longitude=None,
            timezone="UTC",
            source=source,
        )

    async def _detect_auto_location(self) -> LocationSnapshot:
        """Detect user location via IP API with timezone fallback."""
        try:
            client = await self._get_client()
            resp = await client.get("https://ipapi.co/json/", timeout=2.5)
            if resp.status_code == 200:
                data = resp.json()
                city = data.get("city")
                country = data.get("country_name") or data.get("country") or ""
                lat = data.get("latitude")
                lon = data.get("longitude")
                tz = data.get("timezone") or "UTC"

                if city and lat is not None and lon is not None:
                    return LocationSnapshot(
                        city=str(city),
                        country=str(country),
                        latitude=float(lat),
                        longitude=float(lon),
                        timezone=str(tz),
                        source="ip_auto",
                    )
        except Exception as exc:
            logger.debug("IP geolocation primary lookup failed: %s", exc)

        # Fallback to system timezone mapping
        import datetime
        local_dt = datetime.datetime.now().astimezone()
        tz_str = local_dt.tzname() or ""
        matched_city = None
        for tz_key, city in _TIMEZONE_TO_CITY.items():
            if tz_key.lower() in tz_str.lower():
                matched_city = city
                break

        if not matched_city:
            # Default to Moscow if timezone is UTC+3 or MSK
            offset = local_dt.utcoffset()
            if offset and int(offset.total_seconds()) == 10800:
                matched_city = "Москва"

        if matched_city:
            norm = matched_city.lower()
            if norm in self._geocode_cache:
                lat, lon, country, tz = self._geocode_cache[norm]
                return LocationSnapshot(
                    city=matched_city,
                    country=country,
                    latitude=lat,
                    longitude=lon,
                    timezone=tz,
                    source="timezone_fallback",
                )

        return LocationSnapshot(
            city="Москва",
            country="Россия",
            latitude=55.7558,
            longitude=37.6173,
            timezone="Europe/Moscow",
            source="unknown",
        )
