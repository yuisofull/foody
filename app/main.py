from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

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
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

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


class DiscoverItemResponse(BaseModel):
    restaurant_id: str
    restaurant_name: str
    name: str
    score: float
    nutrition: NutritionEstimate | None


class DiscoverResponse(BaseModel):
    recommendations: list[DiscoverItemResponse]


class DiscoverJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class DiscoverEnqueueResponse(BaseModel):
    job_id: str
    status: DiscoverJobStatus
    poll_url: str


class DiscoverJobResponse(BaseModel):
    job_id: str
    status: DiscoverJobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: DiscoverResponse | None = None
    error: str | None = None


class _DiscoverJobRecord(BaseModel):
    job_id: str
    request: DiscoverRequest
    status: DiscoverJobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: DiscoverResponse | None = None
    error: str | None = None


_discover_jobs: dict[str, _DiscoverJobRecord] = {}
_discover_queue: asyncio.Queue[str] | None = None
_discover_worker_task: asyncio.Task[None] | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _compute_discover(body: DiscoverRequest) -> DiscoverResponse:
    restaurants = await _restaurant_service.get_nearby_restaurants(
        body.location, body.radius
    )
    profile = body.profile
    if not profile:
        return DiscoverResponse(recommendations=[])

    all_items: list[MenuItem] = []
    item_restaurant_map: dict[str, Restaurant] = {}
    for restaurant in restaurants:
        menu_items = await _menu_service.get_menu_items(restaurant)
        for item in menu_items:
            scoped_item = item.model_copy(update={"id": f"{restaurant.id}:{item.id}"})
            all_items.append(scoped_item)
            item_restaurant_map[scoped_item.id] = restaurant

    if not all_items:
        return DiscoverResponse(recommendations=[])

    ranked_items = await _recommendation_service.recommend_for_items(
        profile=profile,
        items=all_items,
        top_n=body.top_n,
    )

    recommendations: list[DiscoverItemResponse] = []
    for item_id, score, nutrition, item_name in ranked_items:
        restaurant = item_restaurant_map.get(item_id)
        if restaurant is None:
            continue
        recommendations.append(
            DiscoverItemResponse(
                restaurant_id=restaurant.id,
                restaurant_name=restaurant.name,
                name=item_name,
                score=score,
                nutrition=nutrition,
            )
        )

    return DiscoverResponse(recommendations=recommendations)


async def _discover_worker(queue: asyncio.Queue[str]) -> None:
    while True:
        job_id = await queue.get()
        job = _discover_jobs.get(job_id)
        if job is None:
            queue.task_done()
            continue

        job.status = DiscoverJobStatus.running
        job.started_at = _utc_now()
        _discover_jobs[job_id] = job

        try:
            job.result = await _compute_discover(job.request)
            job.status = DiscoverJobStatus.completed
            job.error = None
        except Exception as exc:
            job.status = DiscoverJobStatus.failed
            job.error = str(exc)
        finally:
            job.finished_at = _utc_now()
            _discover_jobs[job_id] = job
            queue.task_done()


@app.on_event("startup")
async def _start_discover_worker() -> None:
    global _discover_queue, _discover_worker_task
    _discover_queue = asyncio.Queue()
    if _discover_worker_task is None or _discover_worker_task.done():
        _discover_worker_task = asyncio.create_task(_discover_worker(_discover_queue))


@app.on_event("shutdown")
async def _stop_discover_worker() -> None:
    global _discover_queue, _discover_worker_task
    if _discover_worker_task is None:
        _discover_queue = None
        return

    _discover_worker_task.cancel()
    with suppress(asyncio.CancelledError):
        await _discover_worker_task
    _discover_worker_task = None
    _discover_queue = None


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


@app.post("/discover", response_model=DiscoverEnqueueResponse, status_code=202)
async def discover(body: DiscoverRequest) -> DiscoverEnqueueResponse:
    """
    Queue a discovery request for background processing.
    """
    job_id = str(uuid4())
    _discover_jobs[job_id] = _DiscoverJobRecord(
        job_id=job_id,
        request=body,
        status=DiscoverJobStatus.queued,
        created_at=_utc_now(),
    )
    if _discover_queue is None:
        raise HTTPException(status_code=503, detail="Discover worker is unavailable")

    await _discover_queue.put(job_id)
    return DiscoverEnqueueResponse(
        job_id=job_id,
        status=DiscoverJobStatus.queued,
        poll_url=f"/discover/jobs/{job_id}",
    )


@app.get("/discover/jobs/{job_id}", response_model=DiscoverJobResponse)
async def get_discover_job(job_id: str) -> DiscoverJobResponse:
    job = _discover_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Discover job not found")

    return DiscoverJobResponse(
        job_id=job.job_id,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        result=job.result,
        error=job.error,
    )
