from __future__ import annotations

from cachetools import TTLCache

from app.models.restaurant import Location, Restaurant


class RestaurantCache:
    """
    In-memory TTL cache for restaurant search results.

    Cache keys are formed from (latitude, longitude, radius) tuples
    so that repeated queries for the same area are served from memory.
    """

    def __init__(self, maxsize: int = 1000, ttl: int = 300) -> None:
        self._cache: TTLCache[str, list[Restaurant]] = TTLCache(
            maxsize=maxsize, ttl=ttl
        )
        self._hits = 0
        self._misses = 0

    def _make_key(self, location: Location, radius: float) -> str:
        return f"{location.lat:.4f},{location.lng:.4f},{radius}"

    def get(self, location: Location, radius: float) -> list[Restaurant] | None:
        key = self._make_key(location, radius)
        value = self._cache.get(key)
        if value is None:
            self._misses += 1
        else:
            self._hits += 1
        return value

    def set(
        self, location: Location, radius: float, restaurants: list[Restaurant]
    ) -> None:
        self._cache[self._make_key(location, radius)] = restaurants

    def invalidate(self, location: Location, radius: float) -> None:
        key = self._make_key(location, radius)
        self._cache.pop(key, None)

    def clear(self) -> None:
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def stats(self) -> dict[str, int]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._cache),
        }
