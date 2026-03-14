from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
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
from app.services.ranking_service import RankedItem, RankingService
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
_menu_service = MenuService()
_nutrition_service = NutritionService()
_user_service = UserService()
_ranking_service = RankingService()

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


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class NearbyRequest(BaseModel):
    location: Location
    radius: float = Field(1000.0, gt=0, le=50000, description="Search radius in metres")


class MenuUrlRequest(BaseModel):
    restaurant: Restaurant
    providers: list[str] = Field(
        default=["Menulog", "DoorDash", "RestaurantSite"],
        description="Provider names to try in order",
    )


class MenuUrlResponse(BaseModel):
    urls: list[str]


class ExtractMenuRequest(BaseModel):
    menu_url: str = Field(..., description="URL of the menu page")
    provider_name: str = Field("RestaurantSite", description="Name of the provider that supplied the URL")
    extractors: list[str] = Field(
        default=["WebFetch", "AI"],
        description="Extractor names to try in order",
    )


class NutritionRequest(BaseModel):
    item: MenuItem
    estimator: Estimator = Estimator.ai


class RankingRequest(BaseModel):
    profile: UserProfile
    items: list[MenuItem]
    n: int = Field(10, ge=1, le=100, description="Number of top items to return")
    nutrition_map: dict[str, NutritionEstimate] | None = Field(
        None,
        description="Optional pre-computed nutrition keyed by item ID",
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


@app.post("/restaurant/menu-url", response_model=MenuUrlResponse)
async def extract_menu_url(body: MenuUrlRequest) -> MenuUrlResponse:
    """ExtractMenuUrl(restaurant, []MenuProvider) -> []url"""
    providers = _resolve_providers(body.providers)
    urls = await _menu_service.extract_menu_url(body.restaurant, providers)
    return MenuUrlResponse(urls=urls)


@app.post("/menu/extract", response_model=list[MenuItem])
async def extract_menu(body: ExtractMenuRequest) -> list[MenuItem]:
    """ExtractMenu(MenuURL, MenuProvider, []MenuExtractor) -> items"""
    provider = _resolve_single_provider(body.provider_name)
    extractors = _resolve_extractors(body.extractors)
    return await _menu_service.extract_menu(body.menu_url, provider, extractors)


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
    """RankingTopMenu(user_profile, []items, N) -> top N items"""
    ranked = _ranking_service.rank_top_menu(
        profile=body.profile,
        items=body.items,
        n=body.n,
        nutrition_map=body.nutrition_map,
    )
    return [
        RankedItemResponse(item=r.item, score=r.score, nutrition=r.nutrition)
        for r in ranked
    ]


# ---------------------------------------------------------------------------
# Provider / extractor resolution helpers
# ---------------------------------------------------------------------------

_PROVIDER_REGISTRY = {
    "Menulog": MenulogProvider(),
    "DoorDash": DoorDashProvider(),
    "RestaurantSite": RestaurantSiteProvider(),
}

_EXTRACTOR_REGISTRY = {
    "WebFetch": WebFetchExtractor(),
    "AI": AIMenuExtractor(),
    "OCR": OCRExtractor(),
}


def _resolve_providers(names: list[str]):
    providers = []
    for name in names:
        p = _PROVIDER_REGISTRY.get(name)
        if p:
            providers.append(p)
    return providers or list(_PROVIDER_REGISTRY.values())


def _resolve_single_provider(name: str):
    return _PROVIDER_REGISTRY.get(name, RestaurantSiteProvider())


def _resolve_extractors(names: list[str]):
    extractors = []
    for name in names:
        e = _EXTRACTOR_REGISTRY.get(name)
        if e:
            extractors.append(e)
    return extractors or [WebFetchExtractor(), AIMenuExtractor()]
