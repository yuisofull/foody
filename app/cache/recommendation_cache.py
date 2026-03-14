from __future__ import annotations

from cachetools import TTLCache

from app.models.nutrition import NutritionEstimate


class RecommendationCache:
    """In-memory TTL cache for recommendations by user+restaurant key."""

    def __init__(self, maxsize: int = 5000, ttl: int = 300) -> None:
        self._cache: TTLCache[
            str, list[tuple[str, float, NutritionEstimate | None]]
        ] = TTLCache(
            maxsize=maxsize,
            ttl=ttl,
        )
        self._hits = 0
        self._misses = 0

    @staticmethod
    def build_key(user_id: str, restaurant_id: str) -> str:
        return f"{user_id}::{restaurant_id}"

    def get(
        self, user_id: str, restaurant_id: str
    ) -> list[tuple[str, float, NutritionEstimate | None]] | None:
        key = self.build_key(user_id, restaurant_id)
        value = self._cache.get(key)
        if value is None:
            self._misses += 1
        else:
            self._hits += 1
        return value

    def set(
        self,
        user_id: str,
        restaurant_id: str,
        recommendations: list[tuple[str, float, NutritionEstimate | None]],
    ) -> None:
        self._cache[self.build_key(user_id, restaurant_id)] = recommendations

    def invalidate(self, user_id: str, restaurant_id: str) -> None:
        self._cache.pop(self.build_key(user_id, restaurant_id), None)

    def invalidate_user(self, user_id: str) -> int:
        keys_to_remove = [k for k in self._cache.keys() if k.startswith(f"{user_id}::")]
        for key in keys_to_remove:
            self._cache.pop(key, None)
        return len(keys_to_remove)

    def invalidate_restaurant(self, restaurant_id: str) -> int:
        suffix = f"::{restaurant_id}"
        keys_to_remove = [k for k in self._cache.keys() if k.endswith(suffix)]
        for key in keys_to_remove:
            self._cache.pop(key, None)
        return len(keys_to_remove)

    def clear(self) -> None:
        self._cache.clear()

    @property
    def stats(self) -> dict[str, int]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._cache),
        }
