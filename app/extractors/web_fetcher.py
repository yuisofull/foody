from __future__ import annotations

import re
import uuid

import httpx
from bs4 import BeautifulSoup

from app.extractors.base import MenuExtractor
from app.models.menu import MenuItem
from app.providers.base import MenuProvider


class WebFetchExtractor(MenuExtractor):
    """Extracts menu items by fetching and parsing HTML from the menu URL."""

    PRICE_PATTERN = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)")

    @property
    def name(self) -> str:
        return "WebFetch"

    async def extract(self, menu_url: str, provider: MenuProvider) -> list[MenuItem]:
        html = await self._fetch_html(menu_url)
        if not html:
            return []
        return self._parse_menu_items(html)

    async def _fetch_html(self, url: str) -> str | None:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; FoodyBot/1.0)"},
                )
                if response.status_code == 200:
                    return response.text
        except httpx.HTTPError:
            pass
        return None

    def _parse_menu_items(self, html: str) -> list[MenuItem]:
        soup = BeautifulSoup(html, "html.parser")
        items: list[MenuItem] = []

        # Heuristic: look for common menu item patterns
        for element in soup.find_all(
            ["div", "li", "article", "section"],
            class_=re.compile(r"menu.?item|dish|product|food.?item", re.IGNORECASE),
        ):
            item = self._extract_item_from_element(element)
            if item:
                items.append(item)

        # If no structured items found, fall back to heading + paragraph pairs
        if not items:
            items = self._extract_from_headings(soup)

        return items

    def _extract_item_from_element(self, element: BeautifulSoup) -> MenuItem | None:
        name_tag = element.find(
            ["h1", "h2", "h3", "h4", "span", "div"],
            class_=re.compile(r"name|title|item.?name", re.IGNORECASE),
        )
        name = name_tag.get_text(strip=True) if name_tag else None
        if not name:
            return None

        desc_tag = element.find(
            ["p", "span", "div"],
            class_=re.compile(r"desc|description|detail", re.IGNORECASE),
        )
        description = desc_tag.get_text(strip=True) if desc_tag else None

        price_tag = element.find(
            ["span", "div", "p"],
            class_=re.compile(r"price|cost|amount", re.IGNORECASE),
        )
        price: float | None = None
        if price_tag:
            price_text = price_tag.get_text(strip=True)
            match = self.PRICE_PATTERN.search(price_text)
            if match:
                price = float(match.group(1))

        return MenuItem(
            id=str(uuid.uuid4()),
            name=name,
            price=price,
            description=description,
            category=None,
            tags=[],
        )

    def _extract_from_headings(self, soup: BeautifulSoup) -> list[MenuItem]:
        items: list[MenuItem] = []
        for heading in soup.find_all(["h3", "h4"]):
            name = heading.get_text(strip=True)
            if not name or len(name) > 100:
                continue
            description: str | None = None
            sibling = heading.find_next_sibling(["p", "span"])
            if sibling:
                description = sibling.get_text(strip=True)

            # Look for a price near the heading
            price: float | None = None
            context_text = heading.get_text() + (description or "")
            match = self.PRICE_PATTERN.search(context_text)
            if match:
                price = float(match.group(1))

            items.append(
                MenuItem(
                    id=str(uuid.uuid4()),
                    name=name,
                    price=price,
                    description=description,
                    category=None,
                    tags=[],
                )
            )
        return items
