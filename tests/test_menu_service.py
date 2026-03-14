from __future__ import annotations

import pytest

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


def _make_service(providers=None, extractors=None) -> MenuService:
    return MenuService(
        providers=providers or [],
        extractors=extractors or [],
    )


class TestMenuService:
    @pytest.mark.asyncio
    async def test_extract_menu_url_aggregates_all_providers(self, restaurant):
        providers = [
            _FakeProvider("A", ["https://a.com/menu1", "https://a.com/menu2"]),
            _FakeProvider("B", ["https://b.com/menu"]),
        ]
        service = _make_service(providers=providers)
        result = await service._extract_menu_url(restaurant)
        assert result == ["https://a.com/menu1", "https://a.com/menu2", "https://b.com/menu"]

    @pytest.mark.asyncio
    async def test_extract_menu_url_deduplicates_urls(self, restaurant):
        providers = [
            _FakeProvider("A", ["https://shared.com/menu"]),
            _FakeProvider("B", ["https://shared.com/menu", "https://b.com/menu"]),
        ]
        service = _make_service(providers=providers)
        result = await service._extract_menu_url(restaurant)
        assert result == ["https://shared.com/menu", "https://b.com/menu"]

    @pytest.mark.asyncio
    async def test_extract_menu_url_skips_empty_provider(self, restaurant):
        providers = [
            _FakeProvider("A", []),
            _FakeProvider("B", ["https://b.com/menu"]),
        ]
        service = _make_service(providers=providers)
        result = await service._extract_menu_url(restaurant)
        assert result == ["https://b.com/menu"]

    @pytest.mark.asyncio
    async def test_extract_menu_url_all_empty_returns_empty_list(self, restaurant):
        providers = [
            _FakeProvider("A", []),
            _FakeProvider("B", []),
        ]
        service = _make_service(providers=providers)
        result = await service._extract_menu_url(restaurant)
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_menu_url_no_providers_returns_empty(self, restaurant):
        service = _make_service()
        result = await service._extract_menu_url(restaurant)
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_menu_returns_first_non_empty(self, sample_items):
        extractors = [
            _FakeExtractor("Empty", []),
            _FakeExtractor("Good", sample_items),
        ]
        provider = _FakeProvider("P", ["https://example.com"])
        service = _make_service(providers=[provider], extractors=extractors)
        result = await service.extract_menu("https://example.com/menu")
        assert len(result) == 2
        assert result[0].name == "Beef Taco"

    @pytest.mark.asyncio
    async def test_extract_menu_all_empty_returns_empty(self):
        extractors = [
            _FakeExtractor("Empty1", []),
            _FakeExtractor("Empty2", []),
        ]
        provider = _FakeProvider("P", ["https://example.com"])
        service = _make_service(providers=[provider], extractors=extractors)
        result = await service.extract_menu("https://example.com/menu")
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_menu_no_extractors_returns_empty(self):
        provider = _FakeProvider("P", ["https://example.com"])
        service = _make_service(providers=[provider])
        result = await service.extract_menu("https://example.com/menu")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_menu_items_full_pipeline(self, restaurant, sample_items):
        provider = _FakeProvider("P", ["https://example.com/menu"])
        extractor = _FakeExtractor("Good", sample_items)
        service = _make_service(providers=[provider], extractors=[extractor])
        result = await service.get_menu_items(restaurant)
        assert len(result) == 2
        assert result[0].name == "Beef Taco"

    @pytest.mark.asyncio
    async def test_get_menu_items_no_urls_returns_empty(self, restaurant):
        provider = _FakeProvider("P", [])
        extractor = _FakeExtractor("Good", [])
        service = _make_service(providers=[provider], extractors=[extractor])
        result = await service.get_menu_items(restaurant)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_menu_items_uses_first_successful_url(self, restaurant, sample_items):
        provider = _FakeProvider("P", ["https://bad.com/menu", "https://good.com/menu"])

        call_log: list[str] = []

        class _TrackingExtractor(MenuExtractor):
            @property
            def name(self) -> str:
                return "Tracking"

            async def extract(self, menu_url: str, provider: MenuProvider) -> list[MenuItem]:
                call_log.append(menu_url)
                if "good" in menu_url:
                    return sample_items
                return []

        service = _make_service(providers=[provider], extractors=[_TrackingExtractor()])
        result = await service.get_menu_items(restaurant)
        assert result == sample_items
        # Both URLs should have been tried, first one failed, second succeeded
        assert "https://bad.com/menu" in call_log
        assert "https://good.com/menu" in call_log

    @pytest.mark.asyncio
    async def test_providers_injected_not_passed_per_call(self, restaurant, sample_items):
        """Providers are set once at construction; callers need not supply them."""
        provider = _FakeProvider("InjectedProvider", ["https://injected.com/menu"])
        extractor = _FakeExtractor("Good", sample_items)
        service = MenuService(providers=[provider], extractors=[extractor])
        result = await service.get_menu_items(restaurant)
        assert result == sample_items

