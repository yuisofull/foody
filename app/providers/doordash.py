from __future__ import annotations

import urllib.parse

import httpx

from app.models.restaurant import Restaurant
from app.providers.base import MenuProvider


class DoorDashProvider(MenuProvider):
    """Resolves menu URLs via the DoorDash platform (doordash.com)."""

    BASE_SEARCH_URL = "https://www.doordash.com/search/store"

    @property
    def name(self) -> str:
        return "DoorDash"

    async def get_menu_url(self, restaurant: Restaurant) -> str | None:
        query = urllib.parse.quote_plus(restaurant.name)
        search_url = f"{self.BASE_SEARCH_URL}/{query}/"
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                response = await client.get(search_url)
                if response.status_code == 200:
                    url = self._parse_first_store_url(response.text, restaurant.name)
                    return url
        except httpx.HTTPError:
            pass
        return None

    def _parse_first_store_url(self, html: str, restaurant_name: str) -> str | None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        name_lower = restaurant_name.lower()
        for a_tag in soup.find_all("a", href=True):
            href: str = a_tag["href"]
            text: str = a_tag.get_text(strip=True).lower()
            if name_lower in text and "/store/" in href:
                if href.startswith("http"):
                    return href
                return "https://www.doordash.com" + href
        return None
