from __future__ import annotations

import json
import uuid

import httpx
from openai import AsyncOpenAI

from app.config import get_settings
from app.extractors.base import MenuExtractor
from app.models.menu import MenuItem
from app.providers.base import MenuProvider


_SYSTEM_PROMPT = """You are a menu extraction assistant. Given raw HTML or text from a restaurant menu page, extract all menu items as structured JSON.

Return ONLY a JSON array with no extra text. Each item must have:
- "name": string (required)
- "price": number or null
- "description": string or null
- "category": string or null
- "tags": array of strings (e.g. ["vegan", "gluten-free", "spicy"])

Example:
[
  {
    "name": "Grilled Salmon",
    "price": 24.90,
    "description": "Fresh Atlantic salmon with seasonal vegetables",
    "category": "Mains",
    "tags": ["gluten-free"]
  }
]"""


class AIMenuExtractor(MenuExtractor):
    """Extracts menu items by sending page content to an LLM."""

    MAX_CONTENT_CHARS = 12000

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
        return await self._extract_with_llm(raw_content)

    async def _fetch_text(self, url: str) -> str | None:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; FoodyBot/1.0)"},
                )
                if response.status_code == 200:
                    from bs4 import BeautifulSoup

                    soup = BeautifulSoup(response.text, "html.parser")
                    # Remove scripts and styles to reduce noise
                    for tag in soup(["script", "style", "nav", "footer", "header"]):
                        tag.decompose()
                    text = soup.get_text(separator="\n", strip=True)
                    return text[: self.MAX_CONTENT_CHARS]
        except httpx.HTTPError:
            pass
        return None

    async def _extract_with_llm(self, content: str) -> list[MenuItem]:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": content},
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
            # The model may return {"items": [...]} or directly [...]
            if isinstance(data, dict):
                for key in ("items", "menu", "menu_items", "data"):
                    if key in data and isinstance(data[key], list):
                        data = data[key]
                        break
                else:
                    # Take the first list value if available
                    for v in data.values():
                        if isinstance(v, list):
                            data = v
                            break
            if not isinstance(data, list):
                return []
            items: list[MenuItem] = []
            for entry in data:
                if not isinstance(entry, dict) or not entry.get("name"):
                    continue
                items.append(
                    MenuItem(
                        id=str(uuid.uuid4()),
                        name=str(entry["name"]),
                        price=float(entry["price"]) if entry.get("price") is not None else None,
                        description=str(entry["description"]) if entry.get("description") else None,
                        category=str(entry["category"]) if entry.get("category") else None,
                        tags=[str(t) for t in entry.get("tags", []) if t],
                    )
                )
            return items
        except (json.JSONDecodeError, ValueError, TypeError):
            return []
