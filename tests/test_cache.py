from __future__ import annotations

import pytest

from app.cache.restaurant_cache import RestaurantCache
from app.models.restaurant import Location, Restaurant


@pytest.fixture
def cache() -> RestaurantCache:
    return RestaurantCache(maxsize=100, ttl=60)


@pytest.fixture
def location() -> Location:
    return Location(lat=-33.8688, lng=151.2093)


@pytest.fixture
def restaurants(location) -> list[Restaurant]:
    return [
        Restaurant(
            id="r1",
            name="Cafe A",
            address="1 Main St",
            location=location,
        ),
        Restaurant(
            id="r2",
            name="Cafe B",
            address="2 Main St",
            location=location,
        ),
    ]


class TestRestaurantCache:
    def test_get_miss_returns_none(self, cache, location):
        result = cache.get(location, 500.0)
        assert result is None

    def test_set_and_get(self, cache, location, restaurants):
        cache.set(location, 500.0, restaurants)
        result = cache.get(location, 500.0)
        assert result is not None
        assert len(result) == 2

    def test_different_radius_is_different_key(self, cache, location, restaurants):
        cache.set(location, 500.0, restaurants)
        result = cache.get(location, 1000.0)
        assert result is None

    def test_invalidate_removes_entry(self, cache, location, restaurants):
        cache.set(location, 500.0, restaurants)
        cache.invalidate(location, 500.0)
        assert cache.get(location, 500.0) is None

    def test_clear_removes_all(self, cache, location, restaurants):
        cache.set(location, 500.0, restaurants)
        cache.set(Location(lat=0.0, lng=0.0), 1000.0, restaurants)
        cache.clear()
        assert cache.size == 0

    def test_size_tracks_entries(self, cache, location, restaurants):
        assert cache.size == 0
        cache.set(location, 500.0, restaurants)
        assert cache.size == 1
        cache.set(Location(lat=1.0, lng=1.0), 500.0, restaurants)
        assert cache.size == 2
