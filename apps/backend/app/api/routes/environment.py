"""Environment, time, weather and news diagnostics and preview routes."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/environment/status")
async def get_environment_status(request: Request) -> dict[str, Any]:
    """Returns current environment status: time, location, weather, and ambient header."""
    coordinator = getattr(request.app.state, "situational_coordinator", None)
    runtime_settings = request.app.state.runtime_settings

    if coordinator is None:
        return {"status": "unavailable"}

    ambient_header = await coordinator.get_ambient_header(
        manual_city=runtime_settings.location_city,
        location_mode=runtime_settings.location_mode,
        weather_enabled=runtime_settings.weather_enabled,
    )

    time_snap = coordinator.time_service.now()
    loc_snap = await coordinator.location_service.resolve_location(
        manual_city=runtime_settings.location_city,
        location_mode=runtime_settings.location_mode,
    )

    weather_snap = None
    if runtime_settings.weather_enabled and loc_snap.latitude is not None and loc_snap.longitude is not None:
        weather_snap = await coordinator.weather_service.get_weather(
            loc_snap.latitude,
            loc_snap.longitude,
            city_name=loc_snap.city,
        )

    return {
        "status": "active",
        "ambient_header": ambient_header,
        "time": {
            "iso": time_snap.iso_timestamp,
            "formatted_date": time_snap.date_formatted,
            "formatted_time": time_snap.time_formatted,
            "weekday": time_snap.weekday_ru,
            "day_period": time_snap.day_period_ru,
            "timezone": time_snap.timezone_name,
            "offset": time_snap.utc_offset,
        },
        "location": {
            "city": loc_snap.city,
            "country": loc_snap.country,
            "latitude": loc_snap.latitude,
            "longitude": loc_snap.longitude,
            "timezone": loc_snap.timezone,
            "source": loc_snap.source,
        },
        "weather": (
            {
                "temperature": weather_snap.current.temperature,
                "apparent_temperature": weather_snap.current.apparent_temperature,
                "condition": weather_snap.current.condition_ru,
                "humidity": weather_snap.current.humidity,
                "wind_speed": weather_snap.current.wind_speed,
                "precipitation": weather_snap.current.precipitation,
                "city": weather_snap.current.city_name,
                "detailed": weather_snap.detailed_string(),
            }
            if weather_snap
            else None
        ),
        "settings": {
            "location_mode": runtime_settings.location_mode,
            "location_city": runtime_settings.location_city,
            "weather_enabled": runtime_settings.weather_enabled,
            "news_enabled": runtime_settings.news_enabled,
            "news_category": runtime_settings.news_category,
        },
    }


@router.get("/environment/news")
async def get_environment_news(request: Request, category: str | None = None) -> dict[str, Any]:
    """Returns latest news articles for UI preview."""
    coordinator = getattr(request.app.state, "situational_coordinator", None)
    runtime_settings = request.app.state.runtime_settings

    if coordinator is None:
        return {"articles": [], "category": "none"}

    cat = category or runtime_settings.news_category or "all"
    digest = await coordinator.news_service.get_news(category=cat, max_articles=8)

    return {
        "category": digest.category,
        "articles": [
            {
                "title": a.title,
                "source": a.source,
                "snippet": a.snippet,
                "published": a.published,
                "category": a.category,
            }
            for a in digest.articles
        ],
    }
