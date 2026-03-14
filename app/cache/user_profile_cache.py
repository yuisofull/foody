from __future__ import annotations

from cachetools import TTLCache

from app.models.user import UserProfile


class UserProfileCache:
    """In-memory TTL cache for user profiles by user ID."""

    def __init__(self, maxsize: int = 5000, ttl: int = 900) -> None:
        self._cache: TTLCache[str, UserProfile] = TTLCache(maxsize=maxsize, ttl=ttl)
        self._hits = 0
        self._misses = 0

    def get(self, user_id: str) -> UserProfile | None:
        value = self._cache.get(user_id)
        if value is None:
            self._misses += 1
        else:
            self._hits += 1
        return value

    def set(self, user_id: str, profile: UserProfile) -> None:
        self._cache[user_id] = profile

    def invalidate(self, user_id: str) -> None:
        self._cache.pop(user_id, None)

    def clear(self) -> None:
        self._cache.clear()

    @property
    def stats(self) -> dict[str, int]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._cache),
        }
