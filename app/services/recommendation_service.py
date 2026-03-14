from __future__ import annotations

from app.cache.menu_nutrition_cache import MenuNutritionCache
from app.cache.recommendation_cache import RecommendationCache
from app.config import get_settings
from app.models.menu import MenuItem
from app.models.nutrition import NutritionEstimate
from app.models.restaurant import Restaurant
from app.models.user import UserProfile
from app.services.menu_service import MenuService
from app.services.nutrition_service import Estimator, NutritionService
from app.services.ranking_service import RankingService


class RecommendationService:
    """Coordinates recommendation flow and owns recommendation-related caches."""

    def __init__(
        self,
        menu_service: MenuService,
        nutrition_service: NutritionService,
        ranking_service: RankingService,
        recommendation_cache: RecommendationCache | None = None,
        menu_nutrition_cache: MenuNutritionCache | None = None,
    ) -> None:
        settings = get_settings()
        self._menu_service = menu_service
        self._nutrition_service = nutrition_service
        self._ranking_service = ranking_service
        self._recommendation_cache = recommendation_cache or RecommendationCache(
            maxsize=settings.recommendation_cache_maxsize,
            ttl=settings.recommendation_cache_ttl,
        )
        self._menu_nutrition_cache = menu_nutrition_cache or MenuNutritionCache(
            maxsize=settings.menu_nutrition_cache_maxsize,
            ttl=settings.menu_nutrition_cache_ttl,
        )

    async def recommend_for_restaurant(
        self,
        profile: UserProfile,
        restaurant: Restaurant,
        top_n: int,
    ) -> list[tuple[str, float, NutritionEstimate | None]]:
        cached = self._recommendation_cache.get(profile.user_id, restaurant.id)
        if cached is not None and len(cached) >= top_n:
            return cached[:top_n]

        items = await self._menu_service.get_menu_items(restaurant)
        nutrition_map = await self._build_nutrition_map(restaurant.id, items)
        ranked = self._ranking_service.rank_top_menu(
            profile=profile,
            items=items,
            n=top_n,
            nutrition_map=nutrition_map,
        )
        recommendations = [
            (ranked_item.item.name, ranked_item.score, ranked_item.nutrition)
            for ranked_item in ranked
        ]
        self._recommendation_cache.set(
            profile.user_id,
            restaurant.id,
            recommendations,
        )
        return recommendations

    async def _build_nutrition_map(
        self,
        restaurant_id: str,
        items: list[MenuItem],
        estimator: Estimator = Estimator.ai,
    ) -> dict[str, NutritionEstimate]:
        cached_map = self._menu_nutrition_cache.get(restaurant_id) or {}
        missing_items = [item for item in items if item.id not in cached_map]

        if not missing_items:
            return {item.id: cached_map[item.id] for item in items}

        nutrition_map = dict(cached_map)
        for item in missing_items:
            nutrition_map[item.id] = await self._nutrition_service.estimate_nutrition(
                item,
                estimator=estimator,
            )

        self._menu_nutrition_cache.set(restaurant_id, nutrition_map)
        return nutrition_map

    def invalidate_user_cache(self, user_id: str) -> None:
        self._recommendation_cache.invalidate_user(user_id)
