from __future__ import annotations

from cachetools import TTLCache

from app.models.nutrition import NutritionEstimate


class MenuNutritionCache:
    """In-memory TTL cache for restaurant menu nutrition by restaurant ID."""

    def __init__(self, maxsize: int = 1000, ttl: int = 600) -> None:
        self._cache: TTLCache[str, dict[str, NutritionEstimate]] = TTLCache(
            maxsize=maxsize, ttl=ttl
        )
        self._hits = 0
        self._misses = 0

    def get(self, restaurant_id: str) -> dict[str, NutritionEstimate] | None:
        value = self._cache.get(restaurant_id)
        if value is None:
            self._misses += 1
        else:
            self._hits += 1
        return value

    def set(
        self, restaurant_id: str, nutrition_map: dict[str, NutritionEstimate]
    ) -> None:
        self._cache[restaurant_id] = nutrition_map

    def invalidate(self, restaurant_id: str) -> None:
        self._cache.pop(restaurant_id, None)

    def clear(self) -> None:
        self._cache.clear()

    @property
    def stats(self) -> dict[str, int]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._cache),
        }
