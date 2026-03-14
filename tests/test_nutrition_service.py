from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.menu import MenuItem
from app.models.nutrition import NutritionConfidence, NutritionEstimate
from app.services.nutrition_service import NutritionService, Estimator


@pytest.fixture
def burger_item() -> MenuItem:
    return MenuItem(
        id="item_burger",
        name="Classic Cheeseburger",
        price=12.90,
        description="Beef patty with cheddar, lettuce, tomato and house sauce",
        category="Burgers",
        tags=[],
    )


@pytest.fixture
def nutrition_service() -> NutritionService:
    with patch("app.services.nutrition_service.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            gemini_api_key="fake_key",
            gemini_model="gemini-1.5-flash",
            usda_api_key="fake_usda_key",
            nutrition_cache_maxsize=1000,
            nutrition_cache_ttl=300,
        )
        return NutritionService()


class TestNutritionService:
    @pytest.mark.asyncio
    async def test_estimate_ai_returns_estimate(self, nutrition_service, burger_item):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": '{"calories": 650, "protein": 35, "carbs": 48, "fat": 28}'
                            }
                        ]
                    }
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await nutrition_service.estimate_nutrition(
                burger_item, Estimator.ai
            )

        assert result.calories == 650.0
        assert result.protein == 35.0
        assert result.carbs == 48.0
        assert result.fat == 28.0
        assert result.confidence == NutritionConfidence.estimated

    @pytest.mark.asyncio
    async def test_estimate_ai_handles_exception(self, nutrition_service, burger_item):
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("API error"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await nutrition_service.estimate_nutrition(
                burger_item, Estimator.ai
            )

        assert result.confidence == NutritionConfidence.estimated
        assert result.calories is None

    @pytest.mark.asyncio
    async def test_estimate_usda_no_api_key(self, burger_item):
        with patch("app.services.nutrition_service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                gemini_api_key="",
                gemini_model="gemini-1.5-flash",
                usda_api_key="",
                nutrition_cache_maxsize=1000,
                nutrition_cache_ttl=300,
            )
            service = NutritionService()

        result = await service.estimate_nutrition(burger_item, Estimator.usda)
        assert result.confidence == NutritionConfidence.estimated
        assert result.calories is None

    @pytest.mark.asyncio
    async def test_estimate_usda_returns_verified(self, nutrition_service, burger_item):
        mock_usda_response = {
            "foods": [
                {
                    "description": "Cheeseburger",
                    "foodNutrients": [
                        {"nutrientName": "Energy", "value": 303},
                        {"nutrientName": "Protein", "value": 14.9},
                        {"nutrientName": "Carbohydrate, by difference", "value": 24.6},
                        {"nutrientName": "Total lipid (fat)", "value": 15.8},
                    ],
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_usda_response
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await nutrition_service.estimate_nutrition(
                burger_item, Estimator.usda
            )

        assert result.calories == 303.0
        assert result.protein == 14.9
        assert result.confidence == NutritionConfidence.verified

    @pytest.mark.asyncio
    async def test_estimate_ai_uses_cache_by_item_hash(
        self, nutrition_service, burger_item
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": '{"calories": 500, "protein": 20, "carbs": 30, "fat": 10}'
                            }
                        ]
                    }
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            create_mock = AsyncMock(return_value=mock_response)
            mock_client = AsyncMock()
            mock_client.post = create_mock
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            first = await nutrition_service.estimate_nutrition(
                burger_item, Estimator.ai
            )
            second = await nutrition_service.estimate_nutrition(
                burger_item, Estimator.ai
            )

        assert first.calories == 500.0
        assert second.calories == 500.0
        assert create_mock.await_count == 1
