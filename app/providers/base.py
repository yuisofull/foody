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
    async def get_menu_url(self, restaurant: Restaurant) -> str | None:
        """
        Attempt to resolve the menu URL for the given restaurant.

        Returns the URL string if found, or None if not available.
        """
