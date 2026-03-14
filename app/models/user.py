from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class GoalType(str, Enum):
    weight_loss = "weight_loss"
    muscle_gain = "muscle_gain"
    maintenance = "maintenance"
    general_health = "general_health"


class MacroSplits(BaseModel):
    protein: float = Field(..., ge=0, le=1, description="Fraction of calories from protein")
    carbs: float = Field(..., ge=0, le=1, description="Fraction of calories from carbohydrates")
    fat: float = Field(..., ge=0, le=1, description="Fraction of calories from fat")


class UserProfile(BaseModel):
    user_id: str = Field(..., description="Unique identifier for the user")
    goal_type: GoalType = Field(GoalType.general_health, description="Primary fitness/health goal")
    cal_target: float = Field(2000.0, ge=500, le=10000, description="Daily calorie target (kcal)")
    macro_splits: MacroSplits = Field(
        default_factory=lambda: MacroSplits(protein=0.3, carbs=0.4, fat=0.3),
        description="Desired macro split fractions (must sum to ~1.0)",
    )
    restrictions: list[str] = Field(
        default_factory=list,
        description="Dietary restrictions (e.g., vegan, halal, nut_allergy)",
    )
    budget_max: float | None = Field(None, ge=0, description="Maximum budget per meal")
    cuisine_preferences: list[str] = Field(
        default_factory=list,
        description="Preferred cuisine types",
    )
    liked_items: list[str] = Field(
        default_factory=list,
        description="IDs of previously liked items",
    )
    disliked_items: list[str] = Field(
        default_factory=list,
        description="IDs of previously disliked items",
    )
