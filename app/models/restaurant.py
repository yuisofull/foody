from __future__ import annotations

from pydantic import BaseModel, Field


class Location(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude")
    lng: float = Field(..., ge=-180, le=180, description="Longitude")


class Restaurant(BaseModel):
    id: str = Field(..., description="Unique identifier for the restaurant")
    name: str = Field(..., description="Restaurant name")
    address: str = Field(..., description="Full address")
    location: Location = Field(..., description="Geographic coordinates")
    cuisine_types: list[str] = Field(default_factory=list, description="Types of cuisine")
    rating: float | None = Field(None, ge=0, le=5, description="Average rating out of 5")
    phone: str | None = Field(None, description="Contact phone number")
    website: str | None = Field(None, description="Restaurant website URL")
