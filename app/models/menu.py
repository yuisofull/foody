from __future__ import annotations

from pydantic import BaseModel, Field


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
