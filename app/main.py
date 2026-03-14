from __future__ import annotations

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.cache.menu_cache import MenuExtractionCache
from app.cache.menu_nutrition_cache import MenuNutritionCache
from app.cache.recommendation_cache import RecommendationCache
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
_menu_cache = MenuExtractionCache(
    maxsize=_settings.menu_cache_maxsize,
    ttl=_settings.menu_cache_ttl,
)
_menu_nutrition_cache = MenuNutritionCache(
    maxsize=_settings.menu_nutrition_cache_maxsize,
    ttl=_settings.menu_nutrition_cache_ttl,
)
_recommendation_cache = RecommendationCache(
    maxsize=_settings.recommendation_cache_maxsize,
    ttl=_settings.recommendation_cache_ttl,
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
_menu_service = MenuService(
    providers=_default_providers,
    extractors=_default_extractors,
    menu_cache=_menu_cache,
)
_nutrition_service = NutritionService()
_user_service = UserService()
_ranking_service = RankingService()


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
    restaurant = await _get_restaurant_by_id(restaurant_id)
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
    _recommendation_cache.invalidate_user(enriched.user_id)
    _user_service.invalidate_profile_cache(enriched.user_id)
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

    restaurant = await _get_restaurant_by_id(body.restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    cached_recommendations = _recommendation_cache.get(body.user_id, body.restaurant_id)
    if cached_recommendations is not None and len(cached_recommendations) >= body.top_n:
        return RecommendationResponse(
            restaurant_id=body.restaurant_id,
            recommendations=[
                RecommendationItemResponse(name=name, score=score, nutrition=nutrition)
                for name, score, nutrition in cached_recommendations[: body.top_n]
            ],
        )

    items = await _menu_service.get_menu_items(restaurant)
    nutrition_map = await _build_nutrition_map(body.restaurant_id, items)
    ranked = _ranking_service.rank_top_menu(
        profile=profile,
        items=items,
        n=body.top_n,
        nutrition_map=nutrition_map,
    )
    recommendations = [
        RecommendationItemResponse(
            name=ranked_item.item.name,
            score=ranked_item.score,
            nutrition=ranked_item.nutrition,
        )
        for ranked_item in ranked
    ]
    _recommendation_cache.set(
        body.user_id,
        body.restaurant_id,
        [(item.name, item.score, item.nutrition) for item in recommendations],
    )

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
        cached_recommendations = _recommendation_cache.get(
            profile.user_id, restaurant.id
        )
        if (
            cached_recommendations is not None
            and len(cached_recommendations) >= body.top_n
        ):
            results.append(
                DiscoverRestaurantResult(
                    restaurant=restaurant,
                    recommendations=[
                        RecommendationItemResponse(
                            name=name, score=score, nutrition=nutrition
                        )
                        for name, score, nutrition in cached_recommendations[
                            : body.top_n
                        ]
                    ],
                )
            )
            continue

        items = await _menu_service.get_menu_items(restaurant)
        nutrition_map = await _build_nutrition_map(restaurant.id, items)
        ranked = _ranking_service.rank_top_menu(
            profile=profile,
            items=items,
            n=body.top_n,
            nutrition_map=nutrition_map,
        )
        recommendations = [
            RecommendationItemResponse(
                name=ranked_item.item.name,
                score=ranked_item.score,
                nutrition=ranked_item.nutrition,
            )
            for ranked_item in ranked
        ]
        _recommendation_cache.set(
            profile.user_id,
            restaurant.id,
            [(item.name, item.score, item.nutrition) for item in recommendations],
        )
        results.append(
            DiscoverRestaurantResult(
                restaurant=restaurant,
                recommendations=recommendations,
            )
        )

    return DiscoverResponse(results=results)


async def _build_nutrition_map(
    restaurant_id: str,
    items: list[MenuItem],
    estimator: Estimator = Estimator.ai,
) -> dict[str, NutritionEstimate]:
    cached_map = _menu_nutrition_cache.get(restaurant_id) or {}
    missing_items = [item for item in items if item.id not in cached_map]

    if not missing_items:
        return {item.id: cached_map[item.id] for item in items}

    nutrition_map = dict(cached_map)
    for item in missing_items:
        nutrition_map[item.id] = await _nutrition_service.estimate_nutrition(
            item, estimator=estimator
        )

    _menu_nutrition_cache.set(restaurant_id, nutrition_map)
    return nutrition_map


async def _get_restaurant_by_id(restaurant_id: str) -> Restaurant | None:
    """
    Resolve a restaurant by Google Place ID via Place Details API.

    This keeps workflow endpoints (`/restaurants/{id}/menu`, `/recommendations`)
    independent from client-side provider/extractor details.
    """
    if not _settings.google_places_api_key:
        return None

    resource_name = (
        restaurant_id
        if restaurant_id.startswith("places/")
        else f"places/{restaurant_id}"
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # First try Places API v1 details for both resource-name and plain IDs.
            try:
                response = await client.get(
                    f"https://places.googleapis.com/v1/{resource_name}",
                    headers={
                        "X-Goog-Api-Key": _settings.google_places_api_key,
                        "X-Goog-FieldMask": (
                            "id,displayName,formattedAddress,location,types,"
                            "rating,internationalPhoneNumber,websiteUri"
                        ),
                    },
                )
                response.raise_for_status()
                data = response.json()

                location = data.get("location", {})
                lat = location.get("latitude")
                lng = location.get("longitude")
                name = data.get("displayName", {}).get("text")
                if name is not None and lat is not None and lng is not None:
                    return Restaurant(
                        id=data.get("id", restaurant_id),
                        name=name,
                        address=data.get("formattedAddress", ""),
                        location=Location(lat=float(lat), lng=float(lng)),
                        cuisine_types=data.get("types", []),
                        rating=data.get("rating"),
                        phone=data.get("internationalPhoneNumber"),
                        website=data.get("websiteUri"),
                    )
            except (httpx.HTTPError, ValueError):
                # Fall back to legacy Place Details API.
                pass

            params = {
                "place_id": restaurant_id,
                "fields": (
                    "place_id,name,formatted_address,geometry/location,"
                    "types,rating,formatted_phone_number,website"
                ),
                "key": _settings.google_places_api_key,
            }
            response = await client.get(
                "https://maps.googleapis.com/maps/api/place/details/json",
                params=params,
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError):
        return None

    if data.get("status") != "OK":
        return None

    place = data.get("result", {})
    geometry = place.get("geometry", {}).get("location", {})
    lat = geometry.get("lat")
    lng = geometry.get("lng")
    name = place.get("name")
    if name is None or lat is None or lng is None:
        return None

    return Restaurant(
        id=place.get("place_id", restaurant_id),
        name=name,
        address=place.get("formatted_address", ""),
        location=Location(lat=float(lat), lng=float(lng)),
        cuisine_types=place.get("types", []),
        rating=place.get("rating"),
        phone=place.get("formatted_phone_number"),
        website=place.get("website"),
    )
