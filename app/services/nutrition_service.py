from __future__ import annotations

import hashlib
import json
from enum import Enum

import httpx

from app.cache.nutrition_cache import NutritionEstimationCache
from app.config import get_settings
from app.models.menu import MenuItem
from app.models.nutrition import NutritionConfidence, NutritionEstimate


class Estimator(str, Enum):
    ai = "ai"
    usda = "usda"


_AI_SYSTEM_PROMPT = """You are a nutrition estimation assistant. Given a menu item's name and description, estimate its nutritional content per serving.

Return ONLY a JSON object with no extra text:
{
  "calories": <number or null>,
  "protein": <number or null>,
  "carbs": <number or null>,
  "fat": <number or null>
}
All values are per serving. calories in kcal, macros in grams."""


class NutritionService:
    """
    Service for estimating the nutritional content of menu items.
    """

    USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

    def __init__(self) -> None:
        settings = get_settings()
        self._gemini_api_key = settings.gemini_api_key
        self._gemini_model = settings.gemini_model
        self._usda_api_key = settings.usda_api_key
        self._nutrition_cache = NutritionEstimationCache(
            maxsize=settings.nutrition_cache_maxsize,
            ttl=settings.nutrition_cache_ttl,
        )

    async def estimate_nutrition(
        self,
        item: MenuItem,
        estimator: Estimator = Estimator.ai,
    ) -> NutritionEstimate:
        """
        EstimateNutrition(item, Estimator) -> NutritionEstimate

        Args:
            item: The menu item to estimate nutrition for.
            estimator: Which estimator to use (ai or usda).

        Returns:
            A NutritionEstimate with calorie/macro values and a confidence level.
        """
        item_hash = _build_item_hash(item)
        cache_key = f"{item_hash}:{estimator.value}"
        cached = self._nutrition_cache.get(cache_key)
        if cached is not None:
            return cached

        if estimator == Estimator.usda:
            estimate = await self._estimate_usda(item)
        else:
            estimate = await self._estimate_ai(item)

        self._nutrition_cache.set(cache_key, estimate)
        return estimate

    async def _estimate_ai(self, item: MenuItem) -> NutritionEstimate:
        if not self._gemini_api_key:
            return NutritionEstimate(confidence=NutritionConfidence.estimated)

        description = item.description or ""
        user_content = f"Item: {item.name}\\nDescription: {description}"
        payload = {
            "system_instruction": {
                "parts": [{"text": _AI_SYSTEM_PROMPT}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_content}],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{self._gemini_model}:generateContent",
                    params={"key": self._gemini_api_key},
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            raw = _extract_gemini_text(data)
            data = json.loads(raw)
            return NutritionEstimate(
                calories=_to_float(data.get("calories")),
                protein=_to_float(data.get("protein")),
                carbs=_to_float(data.get("carbs")),
                fat=_to_float(data.get("fat")),
                confidence=NutritionConfidence.estimated,
            )
        except Exception:
            return NutritionEstimate(confidence=NutritionConfidence.estimated)

    async def _estimate_usda(self, item: MenuItem) -> NutritionEstimate:
        if not self._usda_api_key:
            return NutritionEstimate(confidence=NutritionConfidence.estimated)

        query = item.name
        params = {
            "query": query,
            "pageSize": 1,
            "api_key": self._usda_api_key,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.USDA_SEARCH_URL, params=params)
                response.raise_for_status()
                data = response.json()

            foods = data.get("foods", [])
            if not foods:
                return NutritionEstimate(confidence=NutritionConfidence.estimated)

            food = foods[0]
            nutrients = {
                n["nutrientName"]: n["value"] for n in food.get("foodNutrients", [])
            }

            return NutritionEstimate(
                calories=_to_float(nutrients.get("Energy")),
                protein=_to_float(nutrients.get("Protein")),
                carbs=_to_float(nutrients.get("Carbohydrate, by difference")),
                fat=_to_float(nutrients.get("Total lipid (fat)")),
                confidence=NutritionConfidence.verified,
            )
        except (httpx.HTTPError, ValueError, KeyError):
            return NutritionEstimate(confidence=NutritionConfidence.estimated)

    @property
    def cache_stats(self) -> dict[str, int]:
        return self._nutrition_cache.stats


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _build_item_hash(item: MenuItem) -> str:
    payload = f"{item.name.strip().lower()}|{(item.description or '').strip().lower()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _extract_gemini_text(payload: dict) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""

    first = candidates[0]
    content = first.get("content", {}) if isinstance(first, dict) else {}
    parts = content.get("parts", []) if isinstance(content, dict) else []
    if not isinstance(parts, list):
        return ""

    chunks: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str):
                chunks.append(text)

    raw = "\n".join(chunks).strip()
    if raw.startswith("```"):
        lines = [line for line in raw.splitlines() if not line.startswith("```")]
        return "\n".join(lines).strip()
    return raw
