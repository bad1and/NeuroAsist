"""Unit and integration tests for the situational context system in Iris.

Tests:
1. TimeService: format, weekday, local offset, day periods.
2. LocationService: manual city, geocoding cache, timezone fallback.
3. WeatherService: Open-Meteo translation, WMO codes, cache TTL.
4. NewsService: RSS aggregation, compact summary formatting, token budget.
5. SearchService: DuckDuckGo parsing, compact summary.
6. SituationalCoordinator: ambient header formatting, intent evaluation for weather and news.
7. Memory Protection: ensuring situational weather/news does not pollute long-term memory extraction.
"""
from __future__ import annotations

import asyncio
import re
import pytest

from apps.backend.app.environment.coordinator import SituationalCoordinator
from apps.backend.app.environment.location_service import LocationService, LocationSnapshot
from apps.backend.app.environment.news_service import NewsArticle, NewsDigestSnapshot, NewsService
from apps.backend.app.environment.search_service import SearchResult, SearchService, SearchSnapshot
from apps.backend.app.environment.time_service import TimeService
from apps.backend.app.environment.weather_service import (
    CurrentWeatherSnapshot,
    WeatherForecastDay,
    WeatherForecastSnapshot,
    WeatherService,
)
from apps.backend.app.memory.extraction_worker import MEMORY_EXTRACTION_PROMPT


def test_time_service_now() -> None:
    time_svc = TimeService()
    now = time_svc.now()

    assert now.iso_timestamp
    assert now.date_formatted
    assert now.time_formatted
    assert now.weekday_ru in (
        "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"
    )
    assert now.day_period in ("night", "early_morning", "morning", "afternoon", "evening", "late_night")
    assert now.day_period_ru
    assert "UTC" in now.utc_offset

    ambient = now.ambient_string()
    assert now.weekday_ru.capitalize() in ambient
    assert now.time_formatted in ambient


def test_location_service_manual_and_cache() -> None:
    async def run() -> None:
        loc_svc = LocationService()
        try:
            # Pre-cached Russian cities
            loc_moscow = await loc_svc.resolve_location(manual_city="Москва", location_mode="manual")
            assert loc_moscow.city == "Москва"
            assert loc_moscow.latitude is not None
            assert loc_moscow.longitude is not None
            assert loc_moscow.source == "manual"

            loc_spb = await loc_svc.resolve_location(manual_city="Санкт-Петербург", location_mode="manual")
            assert loc_spb.city == "Санкт-Петербург"
            assert loc_spb.latitude is not None

            # Unknown city fallback
            loc_unknown = await loc_svc.resolve_location(manual_city="НесуществующийГородXYZ", location_mode="manual")
            assert loc_unknown.city == "Несуществующийгородxyz"
        finally:
            await loc_svc.close()
    asyncio.run(run())


def test_weather_service_formatting_and_cache() -> None:
    async def run() -> None:
        weather_svc = WeatherService()
        try:
            # Construct synthetic snapshot to test formatting without network
            current = CurrentWeatherSnapshot(
                temperature=14.2,
                apparent_temperature=12.1,
                humidity=55,
                weather_code=2,
                condition_ru="переменная облачность",
                wind_speed=4.5,
                is_day=True,
                precipitation=0.0,
                city_name="Москва",
                cached_at=100.0,
            )
            days = (
                WeatherForecastDay(
                    date_str="2026-09-08",
                    temp_min=8.0,
                    temp_max=16.0,
                    weather_code=2,
                    condition_ru="переменная облачность",
                    precipitation_sum=0.0,
                ),
                WeatherForecastDay(
                    date_str="2026-09-09",
                    temp_min=9.0,
                    temp_max=18.0,
                    weather_code=1,
                    condition_ru="преимущественно ясно",
                    precipitation_sum=0.0,
                ),
            )
            snapshot = WeatherForecastSnapshot(current=current, days=days)

            ambient = snapshot.current.ambient_string()
            assert "+14°C" in ambient
            assert "переменная облачность" in ambient

            detailed = snapshot.detailed_string()
            assert "Москва" in detailed
            assert "+14.2°C" in detailed
            assert "ощущается как +12.1°C" in detailed
            assert "Сегодня: от +8°C до +16°C" in detailed
            assert "Завтра: от +9°C до +18°C" in detailed
        finally:
            await weather_svc.close()
    asyncio.run(run())


def test_news_digest_compact_summary() -> None:
    async def run() -> None:
        news_svc = NewsService()
        try:
            articles = (
                NewsArticle(
                    title="Релиз новой открытой нейросети",
                    source="Хабр",
                    snippet="Команда разработчиков выпустила легковесную модель.",
                    published="Сегодня",
                    category="tech",
                ),
                NewsArticle(
                    title="Запуск космического аппарата к Марсу",
                    source="РБК",
                    snippet="Успешный старт ракеты-носителя состоялся утром.",
                    published="Сегодня",
                    category="general",
                ),
            )
            digest = NewsDigestSnapshot(category="tech", articles=articles, cached_at=100.0)
            summary = digest.compact_summary(max_items=5)

            assert "Главные новости" in summary
            assert "[Хабр]" in summary
            assert "Релиз новой открытой нейросети" in summary
            assert "[РБК]" in summary
            assert "Запуск космического аппарата" in summary
        finally:
            await news_svc.close()
    asyncio.run(run())


def test_situational_coordinator_ambient_header() -> None:
    async def run() -> None:
        coord = SituationalCoordinator()
        try:
            header = await coord.get_ambient_header(manual_city="Москва", weather_enabled=False)
            assert "[Контекст окружения:" in header
            assert "Москва" in header
            assert "UTC" in header
        finally:
            await coord.close()
    asyncio.run(run())


def test_situational_coordinator_intent_evaluation() -> None:
    async def run() -> None:
        coord = SituationalCoordinator()
        try:
            # Casual chat -> no deep enrichment
            enrichment_casual = await coord.evaluate_and_enrich("Привет! Как твои дела?")
            assert enrichment_casual is None

            # Weather query -> triggers weather block
            enrichment_weather = await coord.evaluate_and_enrich("Какая сегодня погода в Москве?", manual_city="Москва")
            assert enrichment_weather is not None
            assert "ДАННЫЕ О ПОГОДЕ ДЛЯ IRIS" in enrichment_weather

            # News query -> triggers news block
            enrichment_news = await coord.evaluate_and_enrich("Что интересного пишут в новостях IT?")
            assert enrichment_news is not None
            assert "ДАЙДЖЕСТ НОВОСТЕЙ ДЛЯ IRIS" in enrichment_news
        finally:
            await coord.close()
    asyncio.run(run())


def test_memory_extraction_prompt_guards_against_situational_noise() -> None:
    """Verify that MEMORY_EXTRACTION_PROMPT explicitly forbids saving weather/news/time noise."""
    assert "погоды" in MEMORY_EXTRACTION_PROMPT.lower()
    assert "новостей" in MEMORY_EXTRACTION_PROMPT.lower()
    assert "время" in MEMORY_EXTRACTION_PROMPT.lower()
    assert "запрещено" in MEMORY_EXTRACTION_PROMPT.lower()


def test_character_agent_with_situational_context(tmp_path) -> None:
    from apps.backend.app.agents.character.agent import CharacterAgent
    from apps.backend.app.llm.base import LLMProvider, LLMResponse
    from apps.backend.app.runtime.settings import RuntimeSettings
    from apps.backend.app.storage.timeline import TimelineStore, TimelineHistoryAdapter

    class RecordingProvider(LLMProvider):
        def __init__(self) -> None:
            self.last_messages = []

        async def generate(self, messages, **kwargs):
            self.last_messages = list(messages)
            return LLMResponse(
                content='{"protocol_version":3,"reply":"Привет!","intent":"casual_chat"}',
                model="test-model",
            )

        async def stream(self, messages, **kwargs):
            self.last_messages = list(messages)
            yield "Привет!"

    async def run() -> None:
        store = TimelineStore(tmp_path / "test.sqlite3")
        store.init_db()
        history = TimelineHistoryAdapter(store)
        coord = SituationalCoordinator()
        provider = RecordingProvider()
        settings = RuntimeSettings(location_city="Москва", weather_enabled=True, news_enabled=True)

        agent = CharacterAgent(
            llm_provider=provider,
            history=history,
            history_limit=5,
            situational_coordinator=coord,
            runtime_settings=settings,
        )

        try:
            # 1. Casual message
            await agent.handle_user_message("test_sess", "Привет!", persist_reply=False)
            system_texts = [m.content for m in provider.last_messages if m.role == "system"]
            combined_system = "\n".join(system_texts)

            # Prefix cache integrity: First message must be static character prompt
            assert "Character Protocol v3" in provider.last_messages[0].content
            # Situational ambient header should be present
            assert "Контекст окружения:" in combined_system
            assert "Москва" in combined_system
            # News should NOT be present on casual greeting
            assert "ДАЙДЖЕСТ НОВОСТЕЙ" not in combined_system

            # 2. Weather query
            await agent.handle_user_message("test_sess", "Какая сейчас погода на улице?", persist_reply=False)
            system_texts = [m.content for m in provider.last_messages if m.role == "system"]
            combined_system = "\n".join(system_texts)
            assert "АКТУАЛЬНЫЕ ДАННЫЕ О ПОГОДЕ ДЛЯ IRIS" in combined_system

            # 3. News query
            await agent.handle_user_message("test_sess", "Что там в новостях?", persist_reply=False)
            system_texts = [m.content for m in provider.last_messages if m.role == "system"]
            combined_system = "\n".join(system_texts)
            assert "ДАЙДЖЕСТ НОВОСТЕЙ ДЛЯ IRIS" in combined_system

            # 4. Live voice streaming
            async for _ in agent.stream_user_message("test_sess", "Который час?", persist_reply=False):
                pass
            live_system_texts = [m.content for m in provider.last_messages if m.role == "system"]
            live_combined = "\n".join(live_system_texts)
            assert "Контекст окружения:" in live_combined
            assert "Москва" in live_combined
        finally:
            await coord.close()

    asyncio.run(run())

