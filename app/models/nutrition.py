from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class NutritionConfidence(str, Enum):
    estimated = "estimated"
    verified = "verified"


class NutritionEstimate(BaseModel):
    calories: float | None = Field(None, ge=0, description="Calories (kcal)")
    protein: float | None = Field(None, ge=0, description="Protein (g)")
    carbs: float | None = Field(None, ge=0, description="Carbohydrates (g)")
    fat: float | None = Field(None, ge=0, description="Fat (g)")
    confidence: NutritionConfidence = Field(
        NutritionConfidence.estimated,
        description="Confidence level of the estimate",
    )
