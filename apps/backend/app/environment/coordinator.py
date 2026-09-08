"""Situational Coordinator uniting time, location, weather, and news services.

Provides:
- Tier 1: Ambient micro-header (~25-35 tokens) injected into dynamic state.
- Tier 2: Intent-based on-demand deep context enrichment (weather forecast, news digest, web search).
- Zero double-roundtrip latency for LLM / Live Voice.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from apps.backend.app.environment.location_service import LocationService, LocationSnapshot
from apps.backend.app.environment.news_service import NewsService
from apps.backend.app.environment.search_service import SearchService
from apps.backend.app.environment.time_service import TimeService, TimeSnapshot
from apps.backend.app.environment.weather_service import WeatherService

logger = logging.getLogger(__name__)

# Intent regex patterns for fast deterministic Tier-2 activation (<1ms)
_WEATHER_QUERY_PATTERN = re.compile(
    r"(?:погод[аеу]|прогноз|температур[аеу]|осадк[иов]|дожд[ьяе]|снег[аом]?|ливн[ья]|жар[ае]|мор[оя]з|"
    r"холодно|тепло|градус(?:ов|а)?|weather|forecast|temperature|rain|snow)",
    re.IGNORECASE,
)

_WEATHER_CITY_PATTERN = re.compile(
    r"(?:в|для|по)\s+([а-яёa-z\-]{3,25})",
    re.IGNORECASE,
)

_NEWS_QUERY_PATTERN = re.compile(
    r"(?:новост[иейям]|вест[ией]|дайджест|что\s+в\s+мире|что\s+происходит|событи[яе]|сводк[аеу]|"
    r"что\s+нового\s+в\s+мире|главные\s+темы|news|headlines)",
    re.IGNORECASE,
)

_TECH_NEWS_SUBPATTERN = re.compile(
    r"(?:it|ай[ -]?ти|технолог|хабр|наук|гаджет|программ|ии|ai|tech)",
    re.IGNORECASE,
)

_SEARCH_QUERY_PATTERN = re.compile(
    r"(?:найди\s+(?:в\s+интернете|инфу|информацию)|погугли|загугли|проверь\s+в\s+сети|"
    r"курс\s+(?:доллара|евро|юаня|биткоина|btc|usd|eur|rub)|"
    r"кто\s+(?:выиграл|победил|чемпион)|search|lookup)",
    re.IGNORECASE,
)


class SituationalCoordinator:
    """Manages environmental services and dynamically provides context to the agent."""

    def __init__(
        self,
        time_service: TimeService | None = None,
        location_service: LocationService | None = None,
        weather_service: WeatherService | None = None,
        news_service: NewsService | None = None,
        search_service: SearchService | None = None,
    ) -> None:
        self.time_service = time_service or TimeService()
        self.location_service = location_service or LocationService()
        self.weather_service = weather_service or WeatherService()
        self.news_service = news_service or NewsService()
        self.search_service = search_service or SearchService()

    async def close(self) -> None:
        await self.location_service.close()
        await self.weather_service.close()
        await self.news_service.close()
        await self.search_service.close()

    async def get_ambient_header(
        self,
        manual_city: str | None = None,
        location_mode: str = "auto",
        weather_enabled: bool = True,
    ) -> str:
        """Returns the ultra-compact Tier 1 ambient header (~25-35 tokens).

        Format:
        [Контекст окружения: Вторник, 8 сентября 2026, 15:35 (UTC+03:00) | Москва | +13°C, пасмурно]
        """
        time_snap: TimeSnapshot = self.time_service.now()
        parts = [time_snap.ambient_string()]

        loc_snap: LocationSnapshot | None = None
        if weather_enabled or manual_city or location_mode == "auto":
            try:
                loc_snap = await self.location_service.resolve_location(
                    manual_city=manual_city,
                    location_mode=location_mode,
                )
                if loc_snap and loc_snap.city:
                    parts.append(loc_snap.city)
            except Exception as exc:
                logger.debug("Ambient location resolution error: %s", exc)

        if weather_enabled and loc_snap and loc_snap.latitude is not None and loc_snap.longitude is not None:
            try:
                weather_snap = await self.weather_service.get_weather(
                    loc_snap.latitude,
                    loc_snap.longitude,
                    city_name=loc_snap.city,
                )
                if weather_snap is not None:
                    parts.append(weather_snap.current.ambient_string())
            except Exception as exc:
                logger.debug("Ambient weather resolution error: %s", exc)

        return f"[Контекст окружения: {' | '.join(parts)}]"

    async def evaluate_and_enrich(
        self,
        user_text: str,
        *,
        manual_city: str | None = None,
        location_mode: str = "auto",
        weather_enabled: bool = True,
        news_enabled: bool = True,
        default_news_category: str = "all",
    ) -> str | None:
        """Determines if the user's turn requires deep situational context (Tier 2).

        Returns a structured reference block for Iris or None if not required.
        Executes with strict timeouts so the conversational turn never stalls.
        """
        clean_text = user_text.strip()
        if not clean_text:
            return None

        enrichment_parts: list[str] = []

        # 1. Weather Intent
        if weather_enabled and _WEATHER_QUERY_PATTERN.search(clean_text):
            weather_block = await self._handle_weather_intent(
                clean_text,
                manual_city=manual_city,
                location_mode=location_mode,
            )
            if weather_block:
                enrichment_parts.append(weather_block)

        # 2. News Intent
        if news_enabled and _NEWS_QUERY_PATTERN.search(clean_text):
            news_block = await self._handle_news_intent(
                clean_text,
                default_category=default_news_category,
            )
            if news_block:
                enrichment_parts.append(news_block)

        # 3. Search / Fact Lookup Intent
        if _SEARCH_QUERY_PATTERN.search(clean_text):
            search_block = await self._handle_search_intent(clean_text)
            if search_block:
                enrichment_parts.append(search_block)

        if not enrichment_parts:
            return None

        return "\n\n".join(enrichment_parts)

    async def _handle_weather_intent(
        self,
        user_text: str,
        manual_city: str | None,
        location_mode: str,
    ) -> str | None:
        target_city = manual_city

        # Check if user mentioned another city (e.g. "погода в сочи")
        city_match = _WEATHER_CITY_PATTERN.search(user_text)
        if city_match:
            candidate = city_match.group(1).strip().lower()
            # Ignore common non-city words following prepositions
            if candidate not in (
                "мире", "городе", "доме", "окне", "выходные", "субботу", "воскресенье", "улице", "сети", "интернете",
                "течение", "целом"
            ):
                target_city = candidate

        loc = await self.location_service.resolve_location(
            manual_city=target_city,
            location_mode=location_mode,
        )
        if not loc or loc.latitude is None or loc.longitude is None:
            return None

        weather = await self.weather_service.get_weather(
            loc.latitude,
            loc.longitude,
            city_name=loc.city,
        )
        if not weather:
            return f"[ИНФОРМАЦИЯ О ПОГОДЕ ДЛЯ IRIS: Данные о погоде для {loc.city} временно недоступны (оффлайн или ошибка сервиса).]"

        return f"[АКТУАЛЬНЫЕ ДАННЫЕ О ПОГОДЕ ДЛЯ IRIS]\n{weather.detailed_string()}"

    async def _handle_news_intent(self, user_text: str, default_category: str) -> str | None:
        category = default_category
        if _TECH_NEWS_SUBPATTERN.search(user_text):
            category = "tech"

        digest = await self.news_service.get_news(category=category, max_articles=6)
        if not digest or not digest.articles:
            return "[СВЕЖИЕ НОВОСТИ ДЛЯ IRIS: Ленты новостей сейчас недоступны.]"

        return f"[СВЕЖИЙ ДАЙДЖЕСТ НОВОСТЕЙ ДЛЯ IRIS]\n{digest.compact_summary(max_items=5)}"

    async def _handle_search_intent(self, user_text: str) -> str | None:
        # Extract the core query after search verbs
        match = _SEARCH_QUERY_PATTERN.search(user_text)
        query = user_text
        if match:
            pos = match.end()
            remainder = user_text[pos:].strip(" :?.,")
            if len(remainder) >= 3:
                query = remainder

        snapshot = await self.search_service.search(query)
        if not snapshot or (not snapshot.answer and not snapshot.results):
            return None

        return f"[СПРАВКА ВЕБ-ПОИСКА ДЛЯ IRIS]\n{snapshot.compact_summary(max_items=3)}"
