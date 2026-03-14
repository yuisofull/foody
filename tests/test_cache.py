from __future__ import annotations

import pytest

from app.cache.menu_cache import MenuExtractionCache
from app.cache.menu_nutrition_cache import MenuNutritionCache
from app.cache.nutrition_cache import NutritionEstimationCache
from app.cache.recommendation_cache import RecommendationCache
from app.cache.restaurant_cache import RestaurantCache
from app.cache.user_profile_cache import UserProfileCache
from app.models.menu import MenuItem
from app.models.nutrition import NutritionEstimate
from app.models.restaurant import Location, Restaurant
from app.models.user import UserProfile


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


class TestAdditionalCaches:
    def test_menu_extraction_cache(self):
        cache = MenuExtractionCache(maxsize=10, ttl=60)
        url = "https://example.com/menu"
        items = [MenuItem(id="i1", name="Pizza")]
        cache.set(url, items)
        assert cache.get(url) == items

    def test_nutrition_estimation_cache(self):
        cache = NutritionEstimationCache(maxsize=10, ttl=60)
        key = "hash-key"
        estimate = NutritionEstimate(calories=100)
        cache.set(key, estimate)
        assert cache.get(key) == estimate

    def test_menu_nutrition_cache(self):
        cache = MenuNutritionCache(maxsize=10, ttl=60)
        nutrition_map = {"i1": NutritionEstimate(calories=120)}
        cache.set("restaurant-1", nutrition_map)
        assert cache.get("restaurant-1") == nutrition_map

    def test_recommendation_cache(self):
        cache = RecommendationCache(maxsize=10, ttl=60)
        recommendations = [("Chicken Salad", 98.5, NutritionEstimate(calories=350))]
        cache.set("user-1", "restaurant-1", recommendations)
        assert cache.get("user-1", "restaurant-1") == recommendations

    def test_user_profile_cache(self):
        cache = UserProfileCache(maxsize=10, ttl=60)
        profile = UserProfile(user_id="u1")
        cache.set("u1", profile)
        assert cache.get("u1") == profile
