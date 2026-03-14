from __future__ import annotations

from cachetools import TTLCache

from app.models.nutrition import NutritionEstimate


class NutritionEstimationCache:
    """In-memory TTL cache for item-level nutrition estimates."""

    def __init__(self, maxsize: int = 5000, ttl: int = 900) -> None:
        self._cache: TTLCache[str, NutritionEstimate] = TTLCache(
            maxsize=maxsize, ttl=ttl
        )
        self._hits = 0
        self._misses = 0

    def get(self, item_hash: str) -> NutritionEstimate | None:
        value = self._cache.get(item_hash)
        if value is None:
            self._misses += 1
        else:
            self._hits += 1
        return value

    def set(self, item_hash: str, estimate: NutritionEstimate) -> None:
        self._cache[item_hash] = estimate

    def invalidate(self, item_hash: str) -> None:
        self._cache.pop(item_hash, None)

    def clear(self) -> None:
        self._cache.clear()

    @property
    def stats(self) -> dict[str, int]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._cache),
        }
