from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.cache.restaurant_cache import RestaurantCache
from app.config import get_settings
from app.extractors.ai_extractor import AIMenuExtractor
from app.extractors.ocr_extractor import OCRExtractor
from app.extractors.web_fetcher import WebFetchExtractor
from app.models.menu import MenuItem
from app.models.nutrition import NutritionEstimate
from app.models.restaurant import Location, Restaurant
from app.models.user import UserProfile
from app.providers.doordash import DoorDashProvider
from app.providers.menulog import MenulogProvider
from app.providers.restaurant_site import RestaurantSiteProvider
from app.services.menu_service import MenuService
from app.services.nutrition_service import Estimator, NutritionService
from app.services.ranking_service import RankingService
from app.services.restaurant_service import RestaurantService
from app.services.user_service import UserService

app = FastAPI(
    title="Foody API",
    description=(
        "AI-powered food discovery backend. Finds nearby restaurants, "
        "extracts and structures menus, estimates nutrition, and recommends "
        "items tailored to your goals."
    ),
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# Shared instances
# ---------------------------------------------------------------------------
_settings = get_settings()
_cache = RestaurantCache(
    maxsize=_settings.restaurant_cache_maxsize,
    ttl=_settings.restaurant_cache_ttl,
)
_restaurant_service = RestaurantService(cache=_cache)
_default_providers = [
    MenulogProvider(),
    DoorDashProvider(),
    RestaurantSiteProvider(),
]
_default_extractors = [
    WebFetchExtractor(),
    AIMenuExtractor(),
    OCRExtractor(),
]
_menu_service = MenuService(providers=_default_providers, extractors=_default_extractors)
_nutrition_service = NutritionService()
_user_service = UserService()
_ranking_service = RankingService()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class NearbyRequest(BaseModel):
    location: Location
    radius: float = Field(1000.0, gt=0, le=50000, description="Search radius in metres")


class ExtractMenuRequest(BaseModel):
    menu_url: str = Field(..., description="URL of the menu page")


class NutritionRequest(BaseModel):
    item: MenuItem
    estimator: Estimator = Estimator.ai


class DiscoverRequest(BaseModel):
    location: Location
    radius: float = Field(1000.0, gt=0, le=50000, description="Search radius in metres")


class DiscoveredItem(BaseModel):
    item: MenuItem
    nutrition: NutritionEstimate


class RankingRequest(BaseModel):
    profile: UserProfile
    items: list[MenuItem] = Field(
        default_factory=list,
        description="Menu items to rank. When empty, provide location and radius to discover items.",
    )
    n: int = Field(10, ge=1, le=100, description="Number of top items to return")
    nutrition_map: dict[str, NutritionEstimate] | None = Field(
        None,
        description="Optional pre-computed nutrition keyed by item ID",
    )
    location: Location | None = Field(
        None,
        description="User location for on-the-fly item discovery when items list is empty",
    )
    radius: float = Field(
        1000.0,
        gt=0,
        le=50000,
        description="Search radius in metres (used with location for discovery)",
    )


class RankedItemResponse(BaseModel):
    item: MenuItem
    score: float
    nutrition: NutritionEstimate | None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/restaurants/nearby", response_model=list[Restaurant])
async def get_nearby_restaurants(body: NearbyRequest) -> list[Restaurant]:
    """GetRestaurantNearby(location, radius) -> []restaurants"""
    return await _restaurant_service.get_nearby_restaurants(body.location, body.radius)


@app.post("/menu/extract", response_model=list[MenuItem])
async def extract_menu(body: ExtractMenuRequest) -> list[MenuItem]:
    """ExtractMenu(MenuURL) -> items"""
    return await _menu_service.extract_menu(body.menu_url)


@app.post("/menu/discover", response_model=list[DiscoveredItem])
async def discover_menu(body: DiscoverRequest) -> list[DiscoveredItem]:
    """
    Full discovery pipeline: location -> nearby restaurants -> menu items -> nutrition estimates.

    For each nearby restaurant, resolves menu URLs, extracts items, and estimates
    nutrition.  Returns all discovered items with their nutrition data and notifies
    the caller that discovery is complete via the response.
    """
    restaurants = await _restaurant_service.get_nearby_restaurants(body.location, body.radius)
    return await _discover_items_for_restaurants(restaurants)


@app.post("/nutrition/estimate", response_model=NutritionEstimate)
async def estimate_nutrition(body: NutritionRequest) -> NutritionEstimate:
    """EstimateNutrition(item, Estimator) -> NutritionEstimate"""
    return await _nutrition_service.estimate_nutrition(body.item, body.estimator)


@app.get("/user/{user_id}/profile", response_model=UserProfile)
async def get_user_profile(user_id: str) -> UserProfile:
    profile = _user_service.get_user_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="User profile not found")
    return profile


@app.put("/user/{user_id}/profile", response_model=UserProfile)
async def upsert_user_profile(user_id: str, profile: UserProfile) -> UserProfile:
    """StoreUserProfile + AnalyzeUserPreferenceProfile"""
    if profile.user_id != user_id:
        raise HTTPException(
            status_code=400,
            detail="user_id in path must match user_id in body",
        )
    enriched = _user_service.analyze_user_preference_profile(profile)
    _user_service.store_user_profile(enriched)
    return enriched


@app.delete("/user/{user_id}/profile")
async def delete_user_profile(user_id: str) -> dict[str, str]:
    deleted = _user_service.delete_user_profile(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User profile not found")
    return {"status": "deleted"}


@app.post("/menu/rank", response_model=list[RankedItemResponse])
async def rank_menu(body: RankingRequest) -> list[RankedItemResponse]:
    """
    RankingTopMenu(user_profile, []items, N) -> top N items

    Items can be supplied directly in the request body.  When the items list is
    empty and a location is provided, the full discovery pipeline is run first
    (nearby restaurants -> menu items -> nutrition) and those items are ranked.
    """
    items = list(body.items)
    nutrition_map: dict[str, NutritionEstimate] = dict(body.nutrition_map or {})

    if not items and body.location is not None:
        # Run discovery pipeline to obtain items and build nutrition map
        restaurants = await _restaurant_service.get_nearby_restaurants(body.location, body.radius)
        discovered = await _discover_items_for_restaurants(restaurants)
        for discovered_item in discovered:
            nutrition_map[discovered_item.item.id] = discovered_item.nutrition
            items.append(discovered_item.item)

    ranked = _ranking_service.rank_top_menu(
        profile=body.profile,
        items=items,
        n=body.n,
        nutrition_map=nutrition_map,
    )
    return [
        RankedItemResponse(item=r.item, score=r.score, nutrition=r.nutrition)
        for r in ranked
    ]


async def _discover_items_for_restaurants(restaurants: list[Restaurant]) -> list[DiscoveredItem]:
    """Run the menu extraction + nutrition estimation pipeline for a list of restaurants."""
    result: list[DiscoveredItem] = []
    for restaurant in restaurants:
        items = await _menu_service.get_menu_items(restaurant)
        for item in items:
            nutrition = await _nutrition_service.estimate_nutrition(item)
            result.append(DiscoveredItem(item=item, nutrition=nutrition))
    return result
