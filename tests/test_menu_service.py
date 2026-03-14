from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.models.menu import MenuItem
from app.models.restaurant import Location, Restaurant
from app.providers.base import MenuProvider
from app.extractors.base import MenuExtractor
from app.services.menu_service import MenuService


class _FakeProvider(MenuProvider):
    def __init__(self, name: str, urls: list[str]) -> None:
        self._name = name
        self._urls = urls

    @property
    def name(self) -> str:
        return self._name

    async def get_menu_url(self, restaurant: Restaurant) -> list[str]:
        return self._urls


class _FakeExtractor(MenuExtractor):
    def __init__(self, name: str, items: list[MenuItem]) -> None:
        self._name = name
        self._items = items

    @property
    def name(self) -> str:
        return self._name

    async def extract(self, menu_url: str, provider: MenuProvider) -> list[MenuItem]:
        return self._items


@pytest.fixture
def restaurant() -> Restaurant:
    return Restaurant(
        id="r1",
        name="Taco Town",
        address="99 Taco Lane",
        location=Location(lat=0.0, lng=0.0),
        website="https://tacotown.example.com",
    )


@pytest.fixture
def sample_items() -> list[MenuItem]:
    return [
        MenuItem(id="i1", name="Beef Taco", price=5.50, description="Classic beef taco", category="Tacos", tags=[]),
        MenuItem(id="i2", name="Veggie Taco", price=4.90, description="Fresh veggie taco", category="Tacos", tags=["vegan"]),
    ]


class TestMenuService:
    @pytest.mark.asyncio
    async def test_extract_menu_url_aggregates_all_providers(self, restaurant):
        providers = [
            _FakeProvider("A", ["https://a.com/menu1", "https://a.com/menu2"]),
            _FakeProvider("B", ["https://b.com/menu"]),
        ]
        service = MenuService()
        result = await service.extract_menu_url(restaurant, providers)
        assert result == ["https://a.com/menu1", "https://a.com/menu2", "https://b.com/menu"]

    @pytest.mark.asyncio
    async def test_extract_menu_url_deduplicates_urls(self, restaurant):
        providers = [
            _FakeProvider("A", ["https://shared.com/menu"]),
            _FakeProvider("B", ["https://shared.com/menu", "https://b.com/menu"]),
        ]
        service = MenuService()
        result = await service.extract_menu_url(restaurant, providers)
        assert result == ["https://shared.com/menu", "https://b.com/menu"]

    @pytest.mark.asyncio
    async def test_extract_menu_url_skips_empty_provider(self, restaurant):
        providers = [
            _FakeProvider("A", []),
            _FakeProvider("B", ["https://b.com/menu"]),
        ]
        service = MenuService()
        result = await service.extract_menu_url(restaurant, providers)
        assert result == ["https://b.com/menu"]

    @pytest.mark.asyncio
    async def test_extract_menu_url_all_empty_returns_empty_list(self, restaurant):
        providers = [
            _FakeProvider("A", []),
            _FakeProvider("B", []),
        ]
        service = MenuService()
        result = await service.extract_menu_url(restaurant, providers)
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_menu_url_empty_providers(self, restaurant):
        service = MenuService()
        result = await service.extract_menu_url(restaurant, [])
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_menu_returns_first_non_empty(self, restaurant, sample_items):
        provider = _FakeProvider("P", ["https://example.com"])
        extractors = [
            _FakeExtractor("Empty", []),
            _FakeExtractor("Good", sample_items),
        ]
        service = MenuService()
        result = await service.extract_menu("https://example.com/menu", provider, extractors)
        assert len(result) == 2
        assert result[0].name == "Beef Taco"

    @pytest.mark.asyncio
    async def test_extract_menu_all_empty_returns_empty(self, restaurant):
        provider = _FakeProvider("P", ["https://example.com"])
        extractors = [
            _FakeExtractor("Empty1", []),
            _FakeExtractor("Empty2", []),
        ]
        service = MenuService()
        result = await service.extract_menu("https://example.com/menu", provider, extractors)
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_menu_no_extractors(self, restaurant):
        provider = _FakeProvider("P", ["https://example.com"])
        service = MenuService()
        result = await service.extract_menu("https://example.com/menu", provider, [])
        assert result == []
