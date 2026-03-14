from __future__ import annotations

import json
import re
import uuid

import httpx
from openai import AsyncOpenAI

from app.config import get_settings
from app.extractors.base import MenuExtractor
from app.models.menu import MenuItem
from app.providers.base import MenuProvider


_SYSTEM_PROMPT = """You are a menu extraction assistant.

Given raw HTML/text from a restaurant menu page, extract only explicit menu items that are actually present in the content.

Return ONLY valid JSON.
Prefer returning an object with this shape:
{
  "items": [
    {
      "name": "string",
      "price": number or null,
      "description": "string or null",
      "category": "string or null",
      "tags": ["string", "..."],
      "estimated_calories_kcal": integer or null,
      "estimated_protein_g": number or null,
      "nutrition_confidence": "high" | "medium" | "low" | null,
      "nutrition_notes": "string or null"
    }
  ]
}

Rules:
- Extract only menu items explicitly present in the page content.
- Do not invent menu items, prices, descriptions, categories, or tags.
- Ignore navigation, addresses, opening hours, reviews, policies, and unrelated site text.
- Keep descriptions short and clean.
- Convert prices to numbers when possible. Remove currency symbols.
- If price is unclear or missing, return null.
- Tags should only contain explicit or strongly implied dietary/spice tags from the text, such as:
  vegan, vegetarian, gluten-free, spicy, halal
- For nutrition:
  - estimate calories in kcal and protein in grams for a typical serving
  - use only the item name and explicit description
  - do not present estimates as official values
  - if too unclear, return null for nutrition fields
  - set nutrition_confidence to: high, medium, or low
  - add short nutrition_notes explaining the basis of the estimate
- Return JSON only, with no markdown and no commentary.
"""


class AIMenuExtractor(MenuExtractor):
    """Extracts menu items by sending page content to an LLM."""

    MAX_CONTENT_CHARS = 120000

    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model

    @property
    def name(self) -> str:
        return "AI"

    async def extract(self, menu_url: str, provider: MenuProvider) -> list[MenuItem]:
        raw_content = await self._fetch_text(menu_url)
        if not raw_content:
            return []
        return await self._extract_with_llm(menu_url=menu_url, content=raw_content)

    async def _fetch_text(self, url: str) -> str | None:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                response = await client.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; FoodyBot/1.0)",
                        "Accept-Language": "en",
                    },
                )
                response.raise_for_status()
                return self._html_to_clean_text(response.text)[: self.MAX_CONTENT_CHARS]
        except httpx.HTTPError:
            return None

    def _html_to_clean_text(self, html: str) -> str:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(
            [
                "script",
                "style",
                "noscript",
                "svg",
                "canvas",
                "iframe",
                "form",
                "header",
                "footer",
                "nav",
            ]
        ):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{2,}", "\n\n", text)
        return text.strip()

    async def _extract_with_llm(self, menu_url: str, content: str) -> list[MenuItem]:
        prompt = f"""Source URL:
{menu_url}

Page content:
{content}
"""

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or ""
            return self._parse_response(raw)
        except Exception:
            return []

    def _parse_response(self, raw: str) -> list[MenuItem]:
        try:
            data = json.loads(raw)

            if isinstance(data, dict):
                for key in ("items", "menu", "menu_items", "data"):
                    if key in data and isinstance(data[key], list):
                        data = data[key]
                        break
                else:
                    for value in data.values():
                        if isinstance(value, list):
                            data = value
                            break

            if not isinstance(data, list):
                return []

            items: list[MenuItem] = []
            for entry in data:
                if not isinstance(entry, dict):
                    continue

                name = self._clean_string(entry.get("name"))
                if not name:
                    continue

                items.append(
                    MenuItem(
                        id=str(uuid.uuid4()),
                        name=name,
                        price=self._parse_price(entry.get("price")),
                        description=self._clean_string(entry.get("description")),
                        category=self._clean_string(entry.get("category")),
                        tags=self._parse_tags(entry.get("tags")),
                        estimated_calories_kcal=self._parse_int(entry.get("estimated_calories_kcal")),
                        estimated_protein_g=self._parse_float(entry.get("estimated_protein_g")),
                        nutrition_confidence=self._parse_confidence(entry.get("nutrition_confidence")),
                        nutrition_notes=self._clean_string(entry.get("nutrition_notes")),
                    )
                )

            return items
        except (json.JSONDecodeError, ValueError, TypeError):
            return []

    def _clean_string(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    def _parse_tags(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(tag).strip() for tag in value if str(tag).strip()]

    def _parse_price(self, value: object) -> float | None:
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return float(value)

        text = str(value).strip()
        if not text:
            return None

        match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
        if not match:
            return None

        try:
            return float(match.group(0))
        except ValueError:
            return None

    def _parse_float(self, value: object) -> float | None:
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return float(value)

        text = str(value).strip()
        if not text:
            return None

        match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
        if not match:
            return None

        try:
            return float(match.group(0))
        except ValueError:
            return None

    def _parse_int(self, value: object) -> int | None:
        parsed = self._parse_float(value)
        if parsed is None:
            return None
        return int(round(parsed))

    def _parse_confidence(self, value: object) -> str | None:
        text = self._clean_string(value)
        if not text:
            return None

        normalized = text.lower()
        if normalized in {"high", "medium", "low"}:
            return normalized
        return None