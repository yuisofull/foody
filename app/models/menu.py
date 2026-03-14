from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class NutritionConfidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class MenuItem(BaseModel):
    id: str = Field(..., description="Unique identifier for the menu item")
    name: str = Field(..., description="Name of the menu item")
    price: float | None = Field(None, ge=0, description="Price in local currency")
    description: str | None = Field(None, description="Description of the item")
    category: str | None = Field(None, description="Menu category (e.g., Mains, Desserts)")
    tags: list[str] = Field(
        default_factory=list,
        description="Dietary/attribute tags (e.g., vegan, gluten-free, spicy)",
    )

    estimated_calories_kcal: int | None = Field(
        None,
        ge=0,
        description="Estimated calories in kcal",
    )
    estimated_protein_g: float | None = Field(
        None,
        ge=0,
        description="Estimated protein in grams",
    )
    nutrition_confidence: NutritionConfidence | None = Field(
        None,
        description="Confidence level of the nutrition estimate",
    )
    nutrition_notes: str | None = Field(
        None,
        description="Short note explaining the basis of the nutrition estimate",
    )   