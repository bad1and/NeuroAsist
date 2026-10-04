import asyncio
from unittest.mock import AsyncMock

import pytest

from apps.backend.app.environment.coordinator import SituationalCoordinator
from apps.backend.app.environment.location_service import LocationService, LocationSnapshot


def test_auto_mode_ignores_saved_city_and_manual_mode_restores_it():
    async def run():
        service = LocationService()
        automatic = LocationSnapshot("Казань", "RU", 55.8, 49.1, "Europe/Moscow", "ip_auto")
        service._detect_auto_location = AsyncMock(return_value=automatic)
        try:
            manual = await service.resolve_location(manual_city="Москва", location_mode="manual")
            assert manual.city == "Москва"
            assert manual.source == "manual"
            auto = await service.resolve_location(manual_city="Москва", location_mode="auto")
            assert auto == automatic
            service._detect_auto_location.assert_awaited_once()
            restored = await service.resolve_location(manual_city="Москва", location_mode="manual")
            assert restored == manual
        finally:
            await service.close()
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["auto", "manual"])
def test_explicit_weather_city_overrides_location_mode(mode):
    async def run():
        coordinator = SituationalCoordinator()
        coordinator.location_service.resolve_location = AsyncMock(return_value=
            LocationSnapshot("Сочи", "RU", 43.6, 39.7, "Europe/Moscow", "manual"))
        coordinator.weather_service.get_weather = AsyncMock(return_value=None)
        try:
            await coordinator._handle_weather_intent("Какая погода в Сочи?", "Москва", mode)
            coordinator.location_service.resolve_location.assert_awaited_once_with(
                manual_city="сочи", location_mode="manual")
        finally:
            await coordinator.close()
    asyncio.run(run())


def test_weather_without_explicit_city_respects_auto_mode():
    async def run():
        coordinator = SituationalCoordinator()
        coordinator.location_service.resolve_location = AsyncMock(return_value=
            LocationSnapshot("Казань", "RU", 55.8, 49.1, "Europe/Moscow", "ip_auto"))
        coordinator.weather_service.get_weather = AsyncMock(return_value=None)
        try:
            await coordinator._handle_weather_intent("Какая сейчас погода?", "Москва", "auto")
            coordinator.location_service.resolve_location.assert_awaited_once_with(
                manual_city="Москва", location_mode="auto")
        finally:
            await coordinator.close()
    asyncio.run(run())
