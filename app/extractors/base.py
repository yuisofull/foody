from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.menu import MenuItem
from app.providers.base import MenuProvider


class MenuExtractor(ABC):
    """Abstract base class for menu extractors."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this extractor."""

    @abstractmethod
    async def extract(
        self,
        menu_url: str,
        provider: MenuProvider,
    ) -> list[MenuItem]:
        """
        Extract menu items from the given URL.

        Args:
            menu_url: The URL of the menu page.
            provider: The MenuProvider that supplied this URL.

        Returns:
            A list of MenuItem objects, or an empty list if extraction fails.
        """
