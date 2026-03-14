from __future__ import annotations

from app.extractors.base import MenuExtractor
from app.models.menu import MenuItem
from app.models.restaurant import Restaurant
from app.providers.base import MenuProvider
from app.providers.restaurant_site import RestaurantSiteProvider


class MenuService:
    """
    Service for resolving menu URLs and extracting structured menu items.

    Providers and extractors are injected at construction time and used
    internally; callers do not need to supply them on each call.
    """

    def __init__(
        self,
        providers: list[MenuProvider],
        extractors: list[MenuExtractor],
    ) -> None:
        self._providers = providers
        self._extractors = extractors

    async def _extract_menu_url(self, restaurant: Restaurant) -> list[str]:
        """
        Internal helper: query every provider and return deduplicated menu URLs.

        Args:
            restaurant: The target restaurant.

        Returns:
            A deduplicated list of menu URL strings (may be empty).
        """
        all_urls: list[str] = []
        for provider in self._providers:
            all_urls.extend(await provider.get_menu_url(restaurant))
        return list(dict.fromkeys(all_urls))

    async def extract_menu(self, menu_url: str) -> list[MenuItem]:
        """
        ExtractMenu(MenuURL) -> items

        Iterates through the service's extractors in order and returns the
        result from the first extractor that produces at least one item.

        Args:
            menu_url: The URL of the menu page.

        Returns:
            A list of MenuItem objects (may be empty if all extractors fail).
        """
        # Use the first injected provider as context for extractors; fall back
        # to RestaurantSiteProvider when no providers were configured.
        provider = self._providers[0] if self._providers else RestaurantSiteProvider()
        for extractor in self._extractors:
            items = await extractor.extract(menu_url, provider)
            if items:
                return items
        return []

    async def get_menu_items(self, restaurant: Restaurant) -> list[MenuItem]:
        """
        Full pipeline: restaurant -> menu URLs -> menu items.

        Resolves candidate menu URLs for the restaurant using the internal
        providers, then attempts extraction with each URL in order, returning
        items from the first successful extraction.

        Args:
            restaurant: The target restaurant.

        Returns:
            A list of MenuItem objects (may be empty if no items are found).
        """
        urls = await self._extract_menu_url(restaurant)
        for url in urls:
            items = await self.extract_menu(url)
            if items:
                return items
        return []
