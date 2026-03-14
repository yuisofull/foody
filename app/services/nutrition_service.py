from __future__ import annotations

import json
from enum import Enum

import httpx
from openai import AsyncOpenAI

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
        self._openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._openai_model = settings.openai_model
        self._usda_api_key = settings.usda_api_key

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
        if estimator == Estimator.usda:
            return await self._estimate_usda(item)
        return await self._estimate_ai(item)

    async def _estimate_ai(self, item: MenuItem) -> NutritionEstimate:
        description = item.description or ""
        user_content = f"Item: {item.name}\nDescription: {description}"
        try:
            response = await self._openai_client.chat.completions.create(
                model=self._openai_model,
                messages=[
                    {"role": "system", "content": _AI_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or ""
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
            nutrients = {n["nutrientName"]: n["value"] for n in food.get("foodNutrients", [])}

            return NutritionEstimate(
                calories=_to_float(nutrients.get("Energy")),
                protein=_to_float(nutrients.get("Protein")),
                carbs=_to_float(nutrients.get("Carbohydrate, by difference")),
                fat=_to_float(nutrients.get("Total lipid (fat)")),
                confidence=NutritionConfidence.verified,
            )
        except (httpx.HTTPError, ValueError, KeyError):
            return NutritionEstimate(confidence=NutritionConfidence.estimated)


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
