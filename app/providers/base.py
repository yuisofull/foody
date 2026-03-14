from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.restaurant import Restaurant


class MenuProvider(ABC):
    """Abstract base class for menu URL providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of the provider."""

    @abstractmethod
    async def get_menu_url(self, restaurant: Restaurant) -> list[str]:
        """
        Attempt to resolve menu URLs for the given restaurant.

        Returns a list of candidate URLs (may be empty if none are found).
        """
