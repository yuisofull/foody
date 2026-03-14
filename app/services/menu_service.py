from __future__ import annotations

from app.extractors.base import MenuExtractor
from app.models.menu import MenuItem
from app.models.restaurant import Restaurant
from app.providers.base import MenuProvider


class MenuService:
    """
    Service for resolving menu URLs and extracting structured menu items.
    """

    async def extract_menu_url(
        self,
        restaurant: Restaurant,
        providers: list[MenuProvider],
    ) -> list[str]:
        """
        ExtractMenuUrl(restaurant, []MenuProvider) -> []url

        Queries every provided MenuProvider and aggregates the full list of
        candidate URLs, preserving insertion order and removing duplicates.

        Args:
            restaurant: The target restaurant.
            providers: Ordered list of MenuProvider instances to try.

        Returns:
            A deduplicated list of menu URL strings (may be empty).
        """
        all_urls: list[str] = []
        for provider in providers:
            all_urls.extend(await provider.get_menu_url(restaurant))
        return list(dict.fromkeys(all_urls))

    async def extract_menu(
        self,
        menu_url: str,
        provider: MenuProvider,
        extractors: list[MenuExtractor],
    ) -> list[MenuItem]:
        """
        ExtractMenu(MenuURL, MenuProvider, []MenuExtractor) -> items

        Iterates through the provided MenuExtractors in order and returns the
        result from the first extractor that produces at least one item.

        Args:
            menu_url: The URL of the menu page.
            provider: The MenuProvider that supplied this URL.
            extractors: Ordered list of MenuExtractor instances to try.

        Returns:
            A list of MenuItem objects (may be empty if all extractors fail).
        """
        for extractor in extractors:
            items = await extractor.extract(menu_url, provider)
            if items:
                return items
        return []
