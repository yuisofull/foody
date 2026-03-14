from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.cache.menu_cache import MenuExtractionCache
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
from app.services.recommendation_service import RecommendationService
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
_menu_cache = MenuExtractionCache(
    maxsize=_settings.menu_cache_maxsize,
    ttl=_settings.menu_cache_ttl,
)
_restaurant_service = RestaurantService(cache=_cache)
_default_providers = [
    MenulogProvider(),
    DoorDashProvider(),
    RestaurantSiteProvider(),
]
_default_extractors = [
    # WebFetchExtractor(),
    AIMenuExtractor(),
    OCRExtractor(),
]
_menu_service = MenuService(
    providers=_default_providers,
    extractors=_default_extractors,
    menu_cache=_menu_cache,
)
_nutrition_service = NutritionService()
_user_service = UserService()
_ranking_service = RankingService()
_recommendation_service = RecommendationService(
    menu_service=_menu_service,
    nutrition_service=_nutrition_service,
    ranking_service=_ranking_service,
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class NearbyRequest(BaseModel):
    location: Location
    radius: float = Field(1000.0, gt=0, le=50000, description="Search radius in metres")


class DiscoverRequest(BaseModel):
    location: Location
    radius: float = Field(1000.0, gt=0, le=50000, description="Search radius in metres")
    profile: UserProfile | None = Field(
        None,
        description="Optional user profile used for ranking recommendations per restaurant",
    )
    top_n: int = Field(
        3, ge=1, le=20, description="Top N recommendations per restaurant"
    )
    preferences: dict[str, str] | None = Field(
        None,
        description="Optional product-level preferences for future discover tuning",
    )


class RestaurantMenuResponse(BaseModel):
    restaurant_id: str
    items: list[MenuItem] = Field(default_factory=list)


class NutritionBatchRequest(BaseModel):
    items: list[MenuItem] = Field(
        default_factory=list,
        min_length=1,
        description="Menu items to estimate nutrition for",
    )
    estimator: Estimator = Estimator.ai


class NutritionItemResponse(BaseModel):
    id: str
    calories: float | None
    protein: float | None
    carbs: float | None
    fat: float | None
    confidence: str


class NutritionBatchResponse(BaseModel):
    items: list[NutritionItemResponse]


class UpsertUserProfileRequest(UserProfile):
    pass


class RecommendationRequest(BaseModel):
    user_id: str
    restaurant_id: str
    top_n: int = Field(5, ge=1, le=100)


class RecommendationItemResponse(BaseModel):
    name: str
    score: float
    nutrition: NutritionEstimate | None


class RecommendationResponse(BaseModel):
    restaurant_id: str
    recommendations: list[RecommendationItemResponse]


class DiscoverRestaurantResult(BaseModel):
    restaurant: Restaurant
    recommendations: list[RecommendationItemResponse]


class DiscoverResponse(BaseModel):
    results: list[DiscoverRestaurantResult]


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


@app.get("/restaurants/{restaurant_id}/menu", response_model=RestaurantMenuResponse)
async def get_restaurant_menu(restaurant_id: str) -> RestaurantMenuResponse:
    """Lookup a restaurant by ID and return extracted menu items."""
    restaurant = await _restaurant_service.get_restaurant_by_id(restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    items = await _menu_service.get_menu_items(restaurant)
    return RestaurantMenuResponse(restaurant_id=restaurant_id, items=items)


@app.post("/menu/nutrition", response_model=NutritionBatchResponse)
async def estimate_menu_nutrition(
    body: NutritionBatchRequest,
) -> NutritionBatchResponse:
    """Estimate nutrition for a list of menu items."""
    results: list[NutritionItemResponse] = []
    for item in body.items:
        estimate = await _nutrition_service.estimate_nutrition(
            item, estimator=body.estimator
        )
        results.append(
            NutritionItemResponse(
                id=item.id,
                calories=estimate.calories,
                protein=estimate.protein,
                carbs=estimate.carbs,
                fat=estimate.fat,
                confidence=estimate.confidence.value,
            )
        )
    return NutritionBatchResponse(items=results)


@app.post("/users/profile", response_model=UserProfile)
async def upsert_user_profile(profile: UpsertUserProfileRequest) -> UserProfile:
    """StoreUserProfile + AnalyzeUserPreferenceProfile"""
    enriched = _user_service.analyze_user_preference_profile(profile)
    _user_service.store_user_profile(enriched)
    _recommendation_service.invalidate_user_cache(enriched.user_id)
    return enriched


@app.get("/users/{user_id}", response_model=UserProfile)
async def get_user_profile(user_id: str) -> UserProfile:
    profile = _user_service.get_user_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="User profile not found")
    return profile


@app.post("/recommendations", response_model=RecommendationResponse)
async def recommend_menu(body: RecommendationRequest) -> RecommendationResponse:
    """
    Orchestrate all services: profile -> menu extraction -> nutrition -> ranking.
    """
    profile = _user_service.get_user_profile(body.user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="User profile not found")

    restaurant = await _restaurant_service.get_restaurant_by_id(body.restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    recommendations_data = await _recommendation_service.recommend_for_restaurant(
        profile=profile,
        restaurant=restaurant,
        top_n=body.top_n,
    )

    recommendations = [
        RecommendationItemResponse(name=name, score=score, nutrition=nutrition)
        for name, score, nutrition in recommendations_data
    ]

    return RecommendationResponse(
        restaurant_id=body.restaurant_id,
        recommendations=recommendations,
    )


@app.post("/discover", response_model=DiscoverResponse)
async def discover(body: DiscoverRequest) -> DiscoverResponse:
    """
    Smart discovery endpoint:
    location + profile/preferences -> restaurants + recommended dishes.
    """
    restaurants = await _restaurant_service.get_nearby_restaurants(
        body.location, body.radius
    )
    profile = body.profile
    if not profile:
        return DiscoverResponse(results=[])  # No profile = no recommendations for now

    results: list[DiscoverRestaurantResult] = []
    for restaurant in restaurants:
        recommendations_data = await _recommendation_service.recommend_for_restaurant(
            profile=profile,
            restaurant=restaurant,
            top_n=body.top_n,
        )

        recommendations = [
            RecommendationItemResponse(name=name, score=score, nutrition=nutrition)
            for name, score, nutrition in recommendations_data
        ]
        results.append(
            DiscoverRestaurantResult(
                restaurant=restaurant,
                recommendations=recommendations,
            )
        )

    return DiscoverResponse(results=results)
