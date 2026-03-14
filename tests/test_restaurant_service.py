from __future__ import annotations

import pytest
import pytest_asyncio
import httpx

from unittest.mock import AsyncMock, MagicMock, patch

from app.models.restaurant import Location, Restaurant
from app.services.restaurant_service import RestaurantService
from app.cache.restaurant_cache import RestaurantCache


@pytest.fixture
def location() -> Location:
    return Location(lat=-33.8688, lng=151.2093)


@pytest.fixture
def sample_restaurant(location) -> Restaurant:
    return Restaurant(
        id="place_abc123",
        name="The Test Kitchen",
        address="1 Test St, Sydney NSW 2000",
        location=location,
        cuisine_types=["restaurant", "food"],
        rating=4.5,
        phone=None,
        website="https://testkitchen.example.com",
    )


@pytest.fixture
def mock_google_response() -> dict:
    return {
        "results": [
            {
                "place_id": "place_abc123",
                "name": "The Test Kitchen",
                "vicinity": "1 Test St, Sydney NSW 2000",
                "geometry": {"location": {"lat": -33.8688, "lng": 151.2093}},
                "types": ["restaurant", "food"],
                "rating": 4.5,
            },
            {
                "place_id": "place_def456",
                "name": "Burger Palace",
                "vicinity": "42 King St, Sydney NSW 2000",
                "geometry": {"location": {"lat": -33.870, "lng": 151.210}},
                "types": ["restaurant"],
                "rating": 3.8,
            },
        ],
        "status": "OK",
    }


class TestRestaurantService:
    def test_init_creates_cache(self):
        service = RestaurantService()
        assert service._cache is not None

    def test_init_with_custom_cache(self):
        custom_cache = RestaurantCache(maxsize=10, ttl=60)
        service = RestaurantService(cache=custom_cache)
        assert service._cache is custom_cache

    @pytest.mark.asyncio
    async def test_get_nearby_returns_cached(self, location):
        cache = RestaurantCache()
        cached_restaurants = [
            Restaurant(
                id="cached_1",
                name="Cached Restaurant",
                address="Cached Address",
                location=location,
            )
        ]
        cache.set(location, 1000.0, cached_restaurants)

        service = RestaurantService(cache=cache)
        result = await service.get_nearby_restaurants(location, 1000.0)

        assert len(result) == 1
        assert result[0].id == "cached_1"

    @pytest.mark.asyncio
    async def test_get_nearby_no_api_key_returns_empty(self, location):
        with patch("app.services.restaurant_service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                google_places_api_key="",
                restaurant_cache_maxsize=1000,
                restaurant_cache_ttl=300,
            )
            service = RestaurantService()
            result = await service.get_nearby_restaurants(location, 1000.0)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_nearby_populates_cache(self, location):
        cache = RestaurantCache()
        service = RestaurantService(cache=cache)

        # Pre-populate cache manually
        restaurants = [
            Restaurant(
                id="r1",
                name="R1",
                address="Addr1",
                location=location,
            )
        ]
        cache.set(location, 500.0, restaurants)

        result = await service.get_nearby_restaurants(location, 500.0)
        assert result == restaurants

    def test_parse_place_valid(self):
        service = RestaurantService()
        place = {
            "place_id": "abc",
            "name": "Cool Cafe",
            "vicinity": "10 Main St",
            "geometry": {"location": {"lat": 1.0, "lng": 2.0}},
            "types": ["cafe"],
            "rating": 4.2,
        }
        restaurant = service._parse_place(place)
        assert restaurant is not None
        assert restaurant.id == "abc"
        assert restaurant.name == "Cool Cafe"
        assert restaurant.location.lat == 1.0
        assert restaurant.rating == 4.2

    def test_parse_place_missing_name(self):
        service = RestaurantService()
        place = {
            "place_id": "abc",
            "geometry": {"location": {"lat": 1.0, "lng": 2.0}},
        }
        assert service._parse_place(place) is None

    def test_parse_place_missing_location(self):
        service = RestaurantService()
        place = {
            "place_id": "abc",
            "name": "No Location",
            "geometry": {},
        }
        assert service._parse_place(place) is None

    @pytest.mark.asyncio
    async def test_get_nearby_fetches_from_google(self, location, mock_google_response):
        cache = RestaurantCache()

        with patch("app.services.restaurant_service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                google_places_api_key="fake_key",
                restaurant_cache_maxsize=1000,
                restaurant_cache_ttl=300,
            )
            service = RestaurantService(cache=cache)
            service._api_key = "fake_key"

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = mock_google_response
                mock_response.raise_for_status = MagicMock()

                mock_client = AsyncMock()
                mock_client.post = AsyncMock(
                    side_effect=httpx.HTTPError("new api unavailable")
                )
                mock_client.get = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_class.return_value = mock_client

                result = await service.get_nearby_restaurants(location, 1000.0)

        assert len(result) == 2
        assert result[0].name == "The Test Kitchen"
        assert result[1].name == "Burger Palace"
