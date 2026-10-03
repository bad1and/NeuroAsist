"""Environment, time, weather and news diagnostics and preview routes."""
from __future__ import annotations

import logging
import base64
import json
from typing import Any

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, ConfigDict
from typing import Literal
from apps.backend.app.environment.news_service import NEWS_CATEGORIES
from apps.backend.app.environment.retrieval import parse_date

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
            "web_search_enabled": runtime_settings.web_search_enabled,
            "web_search_provider": getattr(runtime_settings, "web_search_provider", "free"),
        },
    }


@router.get("/environment/news")
async def get_environment_news(request: Request, category: str | None = None, limit: int = 8,
                               cursor: str | None = None) -> dict[str, Any]:
    """Returns latest news articles for UI preview."""
    coordinator = getattr(request.app.state, "situational_coordinator", None)
    runtime_settings = request.app.state.runtime_settings

    if coordinator is None:
        return {"articles": [], "category": "none"}

    cat = category or runtime_settings.news_category or "all"
    cat = cat.strip().lower()
    if cat not in NEWS_CATEGORIES:
        cat = "all"
    if not 1 <= limit <= 20:
        raise HTTPException(422, "News limit must be between 1 and 20")
    options = {}
    if cursor:
        try:
            if len(cursor) > 65536:
                raise ValueError()
            state = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            if not isinstance(state, dict) or state.get("category") != cat:
                raise ValueError()
            for key in ("shown_urls", "shown_titles"):
                values = state.get(key, [])
                if not isinstance(values, list) or len(values) > 200 or not all(isinstance(v, str) and len(v) <= 2048 for v in values):
                    raise ValueError()
            for key in ("since", "until"):
                value = state.get(key)
                if value is not None and (not isinstance(value, str) or not parse_date(value)):
                    raise ValueError()
            options = {"exclude_urls": state.get("shown_urls", []), "exclude_titles": state.get("shown_titles", []),
                       "since": state.get("since"), "until": state.get("until")}
        except (ValueError, TypeError, UnicodeError):
            raise HTTPException(422, "Invalid news cursor") from None
    digest = await coordinator.news_service.get_news(category=cat, max_articles=limit,
        refresh=runtime_settings.news_enabled if hasattr(runtime_settings, "news_enabled") else True, **options)
    next_cursor = None
    if digest.has_more and digest.articles:
        state = {k: digest.metadata()[k] for k in ("category", "shown_urls", "shown_titles", "since", "until")}
        next_cursor = base64.urlsafe_b64encode(json.dumps(state, ensure_ascii=False).encode()).decode()

    return {
        "category": digest.category,
        "updated_at": digest.updated_at,
        "stale": digest.stale,
        "cached": digest.cached,
        "next_cursor": next_cursor,
        "source_health": list(digest.source_health),
        "articles": [
            {
                "title": a.title,
                "source": a.source,
                "snippet": a.snippet,
                "published": a.published,
                "category": a.category,
                "url": a.url,
                "stale": a.stale,
            }
            for a in digest.articles
        ],
    }


class SearchProviderCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["brave", "tavily", "serper"]


@router.post("/environment/search/check")
async def check_search_provider(payload: SearchProviderCheck, request: Request) -> dict[str, Any]:
    coordinator = getattr(request.app.state, "situational_coordinator", None)
    if coordinator is None:
        return {"provider": payload.provider, "status": "unavailable"}
    return await coordinator.search_service.check_provider(payload.provider)
