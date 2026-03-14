from __future__ import annotations

from cachetools import TTLCache

from app.models.menu import MenuItem


class MenuExtractionCache:
    """In-memory TTL cache for extracted menu items by menu URL."""

    def __init__(self, maxsize: int = 1000, ttl: int = 300) -> None:
        self._cache: TTLCache[str, list[MenuItem]] = TTLCache(maxsize=maxsize, ttl=ttl)
        self._hits = 0
        self._misses = 0

    def get(self, menu_url: str) -> list[MenuItem] | None:
        value = self._cache.get(menu_url)
        if value is None:
            self._misses += 1
        else:
            self._hits += 1
        return value

    def set(self, menu_url: str, items: list[MenuItem]) -> None:
        self._cache[menu_url] = items

    def invalidate(self, menu_url: str) -> None:
        self._cache.pop(menu_url, None)

    def clear(self) -> None:
        self._cache.clear()

    @property
    def stats(self) -> dict[str, int]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._cache),
        }
